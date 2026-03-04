"""
analysis.py - 설비 건강도 분석 모듈

기능:
  - 롤링 통계 (10/30/60분 이동 평균·표준편차·최대값)
  - 이상 탐지 (Z-score + IQR 결합 방식)
  - 건강도 점수 산출 (0~100, 센서 카테고리 가중 평균)
  - 전체 설비 정비 우선순위 요약 테이블
  - 한국어 설비별 분석 리포트 생성
"""

import pandas as pd
import numpy as np
from preprocess import categorize_sensors, get_sensor_display_name

# ─────────────────────────────────────────────
# 이상 탐지 파라미터
# ─────────────────────────────────────────────
Z_THRESHOLD    = 3.0   # Z-score 이상 판단 기준
IQR_MULTIPLIER = 1.5   # IQR 방식 배수

# ─────────────────────────────────────────────
# 건강도 가중치 (센서 카테고리별)
# 온도 > 전류 > 전력/압력 > 출력률/전압 > 나머지
# ─────────────────────────────────────────────
CATEGORY_WEIGHTS = {
    '온도(℃)':     3.0,
    '전류(A)':     2.5,
    '전력(kW/W)': 2.0,
    '압력':        2.0,
    '출력률(%)':   1.5,
    '전압(V)':    1.5,
    '유량':        1.0,
    '모터/상태':   1.0,
    '기타':        0.5,
}

# 건강도 레벨 기준
HEALTH_LEVELS = [
    (80, '양호',   '정상 운전 중'),
    (60, '주의',   '일부 센서 이상 감지'),
    (40, '경고',   '다수 센서 이상, 점검 필요'),
    ( 0, '위험',   '즉각적인 정비 필요'),
]

RECOMMENDATIONS = {
    '양호': '정기 점검 주기 유지 (월 1회)',
    '주의': '2주 내 예방 점검 권고',
    '경고': '1주 내 정밀 점검 필요',
    '위험': '즉시 가동 중단 및 긴급 정비 요망',
}


# ─────────────────────────────────────────────
# 핵심 함수들
# ─────────────────────────────────────────────

def compute_rolling_stats(df: pd.DataFrame,
                          windows: list = [10, 30, 60]) -> dict:
    """
    롤링 통계 계산

    Parameters
    ----------
    df      : 설비 DataFrame (인덱스=datetime, 1분 간격)
    windows : 롤링 윈도우 크기 목록 (단위: 분 = 행 수)

    Returns
    -------
    dict[int, dict]
        {10: {'mean': df, 'std': df, 'max': df}, 30: ..., 60: ...}
    """
    # 분산이 있는 컬럼만 대상 (상수 센서 제외)
    numeric_df = df.select_dtypes(include=[np.number])
    varying = numeric_df.loc[:, numeric_df.std() > 0]

    result = {}
    for w in windows:
        roll = varying.rolling(window=w, min_periods=1)
        result[w] = {
            'mean': roll.mean(),
            'std':  roll.std().fillna(0),
            'max':  roll.max(),
        }
    return result


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Z-score + IQR 결합 방식 이상 탐지

    Rules:
      - Z-score 절댓값 > Z_THRESHOLD  → 이상
      - IQR 방식: value < Q1 - IQR_MULTIPLIER×IQR
                  OR value > Q3 + IQR_MULTIPLIER×IQR → 이상
      - std = 0 (상수) 컬럼 → 이상 없음 처리
      - 이진(0/1) 컬럼 (모터 상태 등) → 이상 없음 처리

    Returns
    -------
    bool DataFrame (True = 이상)
    """
    numeric_df = df.select_dtypes(include=[np.number])
    anomaly_df = pd.DataFrame(False, index=numeric_df.index,
                              columns=numeric_df.columns)

    for col in numeric_df.columns:
        series = numeric_df[col].dropna()
        if len(series) < 4:
            continue
        if series.std() == 0:
            continue

        # 이진 컬럼 스킵 (모터 ON/OFF, ELB 상태 등)
        unique_vals = set(series.unique())
        if unique_vals.issubset({0.0, 1.0}):
            continue

        # Z-score 이상
        z = np.abs((series - series.mean()) / series.std())
        z_anomaly = z > Z_THRESHOLD

        # IQR 이상
        Q1 = series.quantile(0.25)
        Q3 = series.quantile(0.75)
        iqr = Q3 - Q1
        if iqr > 0:
            iqr_anomaly = (series < Q1 - IQR_MULTIPLIER * iqr) | \
                          (series > Q3 + IQR_MULTIPLIER * iqr)
        else:
            iqr_anomaly = pd.Series(False, index=series.index)

        combined = z_anomaly | iqr_anomaly
        anomaly_df.loc[combined.index, col] = combined

    return anomaly_df


def compute_health_score(df: pd.DataFrame,
                         anomaly_df: pd.DataFrame) -> dict:
    """
    설비 건강도 점수 산출 (0~100)

    알고리즘:
      1. 센서별 이상률 = 이상 횟수 / 전체 행 수
      2. 센서 점수 = 100 × (1 - 이상률)
      3. 최근 RECENT_WINDOW 분 이상률이 높으면 최대 20점 추가 감점
      4. 카테고리 가중치로 가중 평균 → 설비 건강도

    Returns
    -------
    dict:
      'score'              : float (0~100), 분석 불가면 None
      'sensor_scores'      : pd.Series (컬럼명 → 센서 점수)
      'sensor_anomaly_cnt' : pd.Series (컬럼명 → 이상 발생 횟수)
      'anomaly_rate'       : float (전체 이상률)
    """
    RECENT_WINDOW = 60  # 최근 60분 가중

    numeric_cols = df.select_dtypes(include=[np.number]).columns
    active_cols  = anomaly_df.columns.intersection(numeric_cols)

    if active_cols.empty:
        return {'score': None, 'sensor_scores': pd.Series(dtype=float),
                'sensor_anomaly_cnt': pd.Series(dtype=int),
                'anomaly_rate': 0.0}

    total = len(df)
    sensor_scores      = {}
    sensor_anomaly_cnt = {}
    weights            = {}

    for col in active_cols:
        cnt = int(anomaly_df[col].sum())
        sensor_anomaly_cnt[col] = cnt
        rate = cnt / total if total > 0 else 0

        # 기본 점수
        score = 100.0 * (1.0 - rate)

        # 최근 가중 감점
        recent_rate = anomaly_df[col].tail(RECENT_WINDOW).mean()
        score = max(0.0, score - recent_rate * 20.0)

        sensor_scores[col] = round(score, 2)
        cat = categorize_sensors(col)
        weights[col] = CATEGORY_WEIGHTS.get(cat, 1.0)

    scores_arr  = np.array(list(sensor_scores.values()))
    weights_arr = np.array([weights[c] for c in sensor_scores])

    if weights_arr.sum() == 0:
        health = float(np.mean(scores_arr))
    else:
        health = float(np.average(scores_arr, weights=weights_arr))

    overall_anomaly_rate = float(anomaly_df[active_cols].values.mean())

    return {
        'score':              round(max(0.0, min(100.0, health)), 1),
        'sensor_scores':      pd.Series(sensor_scores, name='건강도'),
        'sensor_anomaly_cnt': pd.Series(sensor_anomaly_cnt, name='이상횟수'),
        'anomaly_rate':       overall_anomaly_rate,
    }


def get_top_risk_sensors(health_result: dict, n: int = 5,
                         df: pd.DataFrame = None) -> list:
    """
    건강도가 낮은 상위 n개 위험 센서 반환 (+ 정상범위/실제값 정보)

    Returns
    -------
    list of dict:
      [{'sensor': col_name, 'display': 짧은이름,
        'score': 건강도, 'category': 카테고리,
        'anomaly_count': 이상횟수,
        'normal_min': 정상범위 하한, 'normal_max': 정상범위 상한,
        'avg_value': 평균값, 'actual_min': 실측 최소,
        'actual_max': 실측 최대, 'total_rows': 전체 행수}, ...]
    """
    scores = health_result.get('sensor_scores', pd.Series(dtype=float))
    counts = health_result.get('sensor_anomaly_cnt', pd.Series(dtype=int))

    if scores.empty:
        return []

    worst = scores.nsmallest(n)
    result = []
    for col, score in worst.items():
        info = {
            'sensor':        col,
            'display':       get_sensor_display_name(col),
            'score':         round(score, 1),
            'category':      categorize_sensors(col),
            'anomaly_count': int(counts.get(col, 0)),
        }
        # 정상범위 및 실측값 정보 추가
        if df is not None and col in df.columns:
            series = df[col].dropna()
            Q1 = series.quantile(0.25)
            Q3 = series.quantile(0.75)
            iqr = Q3 - Q1
            info['normal_min'] = round(Q1 - IQR_MULTIPLIER * iqr, 1)
            info['normal_max'] = round(Q3 + IQR_MULTIPLIER * iqr, 1)
            info['avg_value']  = round(series.mean(), 1)
            info['actual_min'] = round(series.min(), 1)
            info['actual_max'] = round(series.max(), 1)
            info['total_rows'] = len(series)
        result.append(info)
    return result


def score_to_level(score: float) -> tuple:
    """건강도 점수 → (레벨명, 설명) 반환"""
    for threshold, level, desc in HEALTH_LEVELS:
        if score >= threshold:
            return level, desc
    return '위험', '즉각적인 정비 필요'


def generate_korean_report(equip_name: str,
                           health_result: dict,
                           df: pd.DataFrame) -> str:
    """
    설비별 한국어 이상예지 분석 리포트 생성

    Parameters
    ----------
    equip_name    : 설비 표시명
    health_result : compute_health_score() 반환값
    df            : 설비 DataFrame

    Returns
    -------
    str (여러 줄 한국어 리포트)
    """
    score = health_result.get('score')
    if score is None:
        return f"[{equip_name}] 분석 가능한 데이터가 없습니다. (전체 0값 또는 미가동)"

    level, desc = score_to_level(score)
    anomaly_rate = health_result.get('anomaly_rate', 0.0)

    # 트렌드 분석: 초기 60분 vs 최근 60분 이상률 비교
    anomaly_df = _make_anomaly_flag_series(health_result, df)
    early_rate  = anomaly_df.head(60).mean() if len(anomaly_df) >= 120 else anomaly_df.mean()
    recent_rate = anomaly_df.tail(60).mean()
    if recent_rate > early_rate * 1.25:
        trend = '⚠ 악화 추세 (최근 이상률 상승)'
    elif recent_rate < early_rate * 0.75:
        trend = '✅ 개선 추세 (최근 이상률 감소)'
    else:
        trend = '→ 안정적 유지'

    top_risks = get_top_risk_sensors(health_result, n=3)

    lines = [
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"[{equip_name}] 건강도: {score:.1f}/100  |  상태: {level} – {desc}",
        f"분석 기간: {df.index[0].strftime('%Y-%m-%d %H:%M')} ~ "
        f"{df.index[-1].strftime('%H:%M')}  |  "
        f"전체 이상감지율: {anomaly_rate*100:.1f}%",
        f"트렌드: {trend}",
        "",
        "▶ 주요 위험 센서 TOP 3",
    ]

    for i, risk in enumerate(top_risks, 1):
        pct = risk['anomaly_count'] / len(df) * 100
        lines.append(
            f"  {i}. {risk['display']}  [{risk['category']}]"
            f" | 건강도 {risk['score']:.1f}/100 | 이상 {risk['anomaly_count']}건 ({pct:.1f}%)"
        )

    lines += [
        "",
        f"권고사항: {RECOMMENDATIONS[level]}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    return '\n'.join(lines)


def _make_anomaly_flag_series(health_result: dict,
                               df: pd.DataFrame) -> pd.Series:
    """건강도 결과에서 행별 이상 여부 시리즈 생성 (내부 헬퍼)"""
    counts = health_result.get('sensor_anomaly_cnt', pd.Series(dtype=int))
    if counts.empty:
        return pd.Series(0.0, index=df.index)
    # 대략적인 행별 이상률: anomaly_rate 단일값으로 균등 분포 가정
    rate = health_result.get('anomaly_rate', 0.0)
    return pd.Series(rate, index=df.index)


def summarize_all_equipment(equipment_dict: dict) -> pd.DataFrame:
    """
    전체 설비 정비 우선순위 요약 테이블 생성

    Parameters
    ----------
    equipment_dict : {설비명: DataFrame} (preprocess.extract_equipment 결과)

    Returns
    -------
    pd.DataFrame (건강도 오름차순 정렬)
    컬럼: 설비명 | 건강도 | 상태 | 주요위험센서 | 이상감지율(%) | 권고사항
    """
    rows = []
    for name, df in equipment_dict.items():
        if df.empty:
            continue
        try:
            anomaly_df = detect_anomalies(df)
            health     = compute_health_score(df, anomaly_df)
        except Exception:
            continue

        score = health.get('score')
        if score is None:
            continue

        level, _ = score_to_level(score)
        top1 = get_top_risk_sensors(health, n=1, df=df)
        worst_sensor = top1[0]['display'] if top1 else '-'
        anomaly_pct  = round(health.get('anomaly_rate', 0.0) * 100, 1)

        # 주요 위험센서 상세 정보
        worst_detail = ''
        if top1:
            r = top1[0]
            if 'normal_max' in r:
                worst_detail = (
                    f"정상: {r.get('normal_min','-')}~{r.get('normal_max','-')} | "
                    f"실제 최대: {r.get('actual_max','-')}"
                )

        rows.append({
            '설비명':        name,
            '건강도':        score,
            '상태':          level,
            '주요위험센서':   worst_sensor,
            '위험센서 상세':  worst_detail,
            '이상감지율(%)': anomaly_pct,
            '권고사항':      RECOMMENDATIONS[level],
        })

    if not rows:
        return pd.DataFrame(columns=['설비명', '건강도', '상태',
                                     '주요위험센서', '위험센서 상세',
                                     '이상감지율(%)', '권고사항'])

    return pd.DataFrame(rows).sort_values('건강도').reset_index(drop=True)


def build_ppt_summary(priority_df: pd.DataFrame,
                      analysis_dt: str = None) -> list:
    """
    PPT용 핵심 5줄 요약 텍스트 생성

    Parameters
    ----------
    priority_df : summarize_all_equipment() 반환 DataFrame
    analysis_dt : 분석 일시 문자열 (None이면 현재 시각 사용)

    Returns
    -------
    list of str (5개 문장)
    """
    import datetime
    if analysis_dt is None:
        analysis_dt = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    if priority_df.empty:
        return ["분석 가능한 설비 데이터가 없습니다."]

    n_equip      = len(priority_df)
    avg_health   = round(priority_df['건강도'].mean(), 1)
    critical_cnt = int((priority_df['건강도'] < 60).sum())
    worst_row    = priority_df.iloc[0]
    best_row     = priority_df.iloc[-1]

    return [
        f"[소성로 설비 이상예지 분석 요약]  분석일시: {analysis_dt}",
        f"▶ 총 {n_equip}개 설비 분석 완료, 평균 건강도 {avg_health}/100",
        f"▶ 즉시 점검 필요 설비 {critical_cnt}개 (건강도 60점 미만)",
        (f"▶ 최우선 정비 대상: {worst_row['설비명']} "
         f"(건강도 {worst_row['건강도']:.1f}, "
         f"주요 이상 센서: {worst_row['주요위험센서']})"),
        f"▶ 최양호 설비: {best_row['설비명']} (건강도 {best_row['건강도']:.1f})",
    ]
