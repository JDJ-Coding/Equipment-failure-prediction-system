"""
소성로 히터 데이터 전처리 파이프라인
- CP949 인코딩, 세미콜론 구분자, 2행 헤더 처리
- 이상치 탐지, 피처 엔지니어링, 고장예지 룰 적용
"""

import io
import re
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────
# 1. 파일 파싱
# ─────────────────────────────────────────────

def load_csv(source) -> pd.DataFrame:
    """
    소성로 히터 CSV 파일 로드.
    source: 파일 경로(str/Path) 또는 bytes 객체(업로드된 파일)
    """
    if isinstance(source, (str, Path)):
        with open(source, "r", encoding="cp949", newline="") as f:
            raw = f.read()
    else:
        raw = source.decode("cp949")

    lines = raw.split("\r\n")
    if not lines or len(lines) < 3:
        raise ValueError("데이터 행이 부족합니다 (최소 3행 필요)")

    # 1행: 시스템 ID 태그 (Time;[115:0];...)
    # 2행: 한국어 컬럼명 (time;#01_예비소성 ...)
    # 3행~: 실제 데이터
    col_ids = lines[0].split(";")
    col_names_raw = lines[1].split(";")

    # 중복 컬럼명에 _2, _3 suffix 붙여 유니크하게 만들기
    col_names = []
    seen: dict = {}
    for name in col_names_raw:
        if name in seen:
            seen[name] += 1
            col_names.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 1
            col_names.append(name)

    data_block = "\n".join(lines[2:])

    df = pd.read_csv(
        io.StringIO(data_block),
        sep=";",
        header=None,
        names=col_names,
        low_memory=False,
    )

    # 시간 컬럼 파싱 (DD.MM.YYYY HH:MM:SS.ffffff)
    df.rename(columns={col_names[0]: "timestamp"}, inplace=True)
    df["timestamp"] = pd.to_datetime(
        df["timestamp"], format="%d.%m.%Y %H:%M:%S.%f", errors="coerce"
    )
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)

    # 숫자 변환
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


# ─────────────────────────────────────────────
# 2. 컬럼 분류
# ─────────────────────────────────────────────

EQUIPMENT_PATTERNS = {
    "RHK-A":   r"#01_A_본소성|RHK#A",
    "RHK-B":   r"#01_B_본소성|RHK#B",
    "PTK예비":  r"#01_예비소성|\[NCF1\]_예비소성|\[NCF1",
    "PNCF연속": r"PNCF1|PNCF01",
}

EQUIPMENT_LABELS = {
    "RHK-A":   "본소성 A라인 (RHK-A)",
    "RHK-B":   "본소성 B라인 (RHK-B)",
    "PTK예비":  "예비소성 (PTK)",
    "PNCF연속": "연속소성 (PNCF)",
}

SENSOR_PATTERNS = {
    "온도": r"온도|TEMP",
    "전류": r"전류",
    "전압": r"전압",
    "전력": r"전력",
    "저항": r"저항",
    "출력": r"출력 \[%\]|SCR.*출력|_출력 \[",
    "동작상태": r"동작 상태|동작상태",
    "차압": r"차압",
    "알람": r"알람",
}

def classify_columns(df: pd.DataFrame) -> dict:
    """컬럼을 장비/센서 유형별로 분류하여 반환"""
    mapping = {"장비": {}, "센서": {}}

    for equip_name, pattern in EQUIPMENT_PATTERNS.items():
        cols = [c for c in df.columns if re.search(pattern, c)]
        if cols:
            mapping["장비"][equip_name] = cols

    for sensor_name, pattern in SENSOR_PATTERNS.items():
        cols = [c for c in df.columns if re.search(pattern, c)]
        if cols:
            mapping["센서"][sensor_name] = cols

    return mapping


def get_active_columns(df: pd.DataFrame, threshold: float = 0.0) -> list:
    """전부 0이 아닌 활성 컬럼만 반환"""
    return [c for c in df.columns if df[c].abs().max() > threshold]


def get_analog_columns(df: pd.DataFrame, threshold: float = 0.0) -> list:
    """활성 컬럼 중 디지털(0/1) 이진 신호를 제외한 아날로그 컬럼만 반환"""
    result = []
    for c in df.columns:
        col_vals = df[c].dropna()
        if len(col_vals) == 0 or col_vals.abs().max() <= threshold:
            continue
        unique_vals = set(col_vals.unique())
        if unique_vals.issubset({0.0, 1.0, 0, 1}):
            continue  # 디지털(0/1) 신호 제외
        result.append(c)
    return result


# ─────────────────────────────────────────────
# 3. 이상치 처리
# ─────────────────────────────────────────────

PLC_ERROR_VALUE = 65535  # PLC 통신 오류 코드

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    이상치 처리:
    - PLC 오류값(65535) → NaN
    - 음수 온도 → NaN
    - 극단값(±5σ) → NaN
    이후 선형 보간 적용
    """
    df = df.copy()

    # PLC 통신 오류값 제거
    df.replace(PLC_ERROR_VALUE, np.nan, inplace=True)
    df[df > 60000] = np.nan

    # 온도 컬럼 음수 제거
    temp_cols = [c for c in df.columns if re.search(r"온도|TEMP", c)]
    for col in temp_cols:
        df.loc[df[col] < 0, col] = np.nan

    # 극단값 처리 (5σ 기준)
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        mean = df[col].mean()
        std = df[col].std()
        if std > 0:
            mask = (df[col] - mean).abs() > 5 * std
            df.loc[mask, col] = np.nan

    # 선형 보간 (최대 5분까지)
    df.interpolate(method="time", limit=5, inplace=True)

    return df


# ─────────────────────────────────────────────
# 4. 피처 엔지니어링
# ─────────────────────────────────────────────

def add_features(df: pd.DataFrame, window_min: int = 60) -> pd.DataFrame:
    """
    파생 변수 생성:
    - 롤링 평균/표준편차 (1시간 윈도우)
    - Z-스코어 (이상 감지용)
    - 변화율 (분당)
    - 저항 이상도 비율
    """
    df = df.copy()
    w = window_min  # 60분 = 60행 (1분 간격)

    current_cols = [c for c in df.columns if "전류" in c and df[c].abs().max() > 0]
    resist_cols  = [c for c in df.columns if "저항" in c and df[c].abs().max() > 0]
    temp_cols    = [c for c in df.columns if re.search(r"온도|TEMP", c) and df[c].abs().max() > 0]

    # 전류: 롤링 통계 + Z-score
    for col in current_cols[:20]:  # 성능상 대표 컬럼만
        safe = re.sub(r'[^\w]', '_', col)
        rm = df[col].rolling(w, min_periods=1).mean()
        rs = df[col].rolling(w, min_periods=1).std().fillna(1)
        df[f"feat_zscore_{safe}"] = ((df[col] - rm) / rs).clip(-10, 10)
        df[f"feat_rate_{safe}"] = df[col].diff(1)

    # 저항: 기준값 대비 증가율
    for col in resist_cols[:20]:
        safe = re.sub(r'[^\w]', '_', col)
        baseline = df[col].rolling(w * 24, min_periods=1).min()
        df[f"feat_resist_ratio_{safe}"] = (df[col] / baseline.replace(0, np.nan)).clip(0, 10)

    # 온도: 변화율
    for col in temp_cols[:20]:
        safe = re.sub(r'[^\w]', '_', col)
        df[f"feat_temp_rate_{safe}"] = df[col].diff(1)

    return df


# ─────────────────────────────────────────────
# 5. 고장예지 룰 엔진
# ─────────────────────────────────────────────

def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    룰 기반 이상 탐지.
    반환: alerts DataFrame (timestamp, equipment, zone, rule, value, severity)
    """
    alerts = []

    current_cols = [c for c in df.columns if "전류" in c and not c.startswith("feat_")]
    resist_cols  = [c for c in df.columns if "저항" in c and not c.startswith("feat_")]
    output_cols  = [c for c in df.columns if re.search(r"출력 \[%\]|_출력 \[", c) and not c.startswith("feat_")]
    status_cols  = [c for c in df.columns if "동작 상태" in c or "동작상태" in c]
    temp_cols    = [c for c in df.columns if re.search(r"온도|TEMP", c) and not c.startswith("feat_") and df[c].abs().max() > 0]

    # 룰 1: 히터 단선 (전류 정상 평균의 30% 미만)
    for col in current_cols:
        mean_val = df[col].mean()
        if mean_val < 1:
            continue
        breach = df[df[col] < mean_val * 0.3]
        for ts, row in breach.iterrows():
            alerts.append({
                "timestamp": ts, "column": col,
                "rule": "히터 단선 의심",
                "value": round(row[col], 2),
                "threshold": round(mean_val * 0.3, 2),
                "severity": "CRITICAL"
            })

    # 룰 2: 절연 불량 (전류 정상 평균의 130% 초과)
    for col in current_cols:
        mean_val = df[col].mean()
        if mean_val < 1:
            continue
        breach = df[df[col] > mean_val * 1.3]
        for ts, row in breach.iterrows():
            alerts.append({
                "timestamp": ts, "column": col,
                "rule": "절연불량 의심 (전류 과대)",
                "value": round(row[col], 2),
                "threshold": round(mean_val * 1.3, 2),
                "severity": "WARNING"
            })

    # 룰 3: 저항 이상 (기준값 대비 10% 초과)
    for col in resist_cols:
        baseline = df[col].quantile(0.05)
        if baseline < 0.01:
            continue
        breach = df[df[col] > baseline * 1.1]
        for ts, row in breach.iterrows():
            alerts.append({
                "timestamp": ts, "column": col,
                "rule": "히터 저항 증가 (노화 의심)",
                "value": round(row[col], 3),
                "threshold": round(baseline * 1.1, 3),
                "severity": "WARNING"
            })

    # 룰 4: SCR 출력 한계
    for col in output_cols:
        breach_warn = df[(df[col] > 85) & (df[col] <= 95)]
        breach_crit = df[df[col] > 95]
        for ts, row in breach_warn.iterrows():
            alerts.append({
                "timestamp": ts, "column": col,
                "rule": "SCR 출력 한계 접근 (교체 검토)",
                "value": round(row[col], 1),
                "threshold": 85.0,
                "severity": "WARNING"
            })
        for ts, row in breach_crit.iterrows():
            alerts.append({
                "timestamp": ts, "column": col,
                "rule": "SCR 출력 한계 초과",
                "value": round(row[col], 1),
                "threshold": 95.0,
                "severity": "CRITICAL"
            })

    # 룰 5: 모터/팬 정지 (1→0 전환)
    for col in status_cols:
        transitions = (df[col].diff() == -1)
        for ts in df.index[transitions]:
            alerts.append({
                "timestamp": ts, "column": col,
                "rule": "모터/팬 정지 감지",
                "value": 0,
                "threshold": 1,
                "severity": "CRITICAL"
            })

    # 룰 6: 온도 급변 (분당 ±10°C)
    for col in temp_cols[:30]:
        rate = df[col].diff(1)
        breach = df[rate.abs() > 10]
        for ts, row in breach.iterrows():
            alerts.append({
                "timestamp": ts, "column": col,
                "rule": "온도 급변 감지",
                "value": round(row[col], 1),
                "threshold": 10.0,
                "severity": "WARNING"
            })

    alerts_df = pd.DataFrame(alerts)
    if not alerts_df.empty:
        alerts_df.sort_values("timestamp", inplace=True)
        alerts_df.reset_index(drop=True, inplace=True)
    return alerts_df


# ─────────────────────────────────────────────
# 6. 집계 / 요약
# ─────────────────────────────────────────────

def summarize(df: pd.DataFrame, col_map: dict) -> dict:
    """대시보드용 요약 통계 계산"""
    summary = {}

    # 온도 요약
    temp_cols = col_map["센서"].get("온도", [])
    active_temp = [c for c in temp_cols if df[c].abs().max() > 0]
    if active_temp:
        temp_data = df[active_temp]
        summary["temperature"] = {
            "max": float(temp_data.max().max()),
            "min": float(temp_data[temp_data > 0].min().min()),
            "mean": float(temp_data[temp_data > 0].stack().mean()),
            "latest": {c: float(df[c].iloc[-1]) for c in active_temp[:5]},
        }

    # 전류 요약
    cur_cols = col_map["센서"].get("전류", [])
    active_cur = [c for c in cur_cols if df[c].abs().max() > 0]
    if active_cur:
        cur_data = df[active_cur]
        summary["current"] = {
            "max": float(cur_data.max().max()),
            "mean": float(cur_data[cur_data > 0].stack().mean()),
        }

    # 저항 요약 (노화 지표)
    res_cols = col_map["센서"].get("저항", [])
    active_res = [c for c in res_cols if df[c].abs().max() > 0]
    if active_res:
        resist_data = df[active_res]
        baseline = resist_data.quantile(0.05)
        ratio = (resist_data.iloc[-1] / baseline.replace(0, np.nan) - 1) * 100
        summary["resistance_aging"] = {
            col: round(float(r), 1)
            for col, r in ratio.items()
            if not np.isnan(r) and r > 0
        }

    # SCR 출력 요약
    out_cols = col_map["센서"].get("출력", [])
    active_out = [c for c in out_cols if df[c].abs().max() > 0]
    if active_out:
        out_data = df[active_out].iloc[-1]
        summary["scr_output"] = {
            "max": float(out_data.max()),
            "mean": float(out_data[out_data > 0].mean()),
            "warning_count": int((out_data > 85).sum()),
        }

    # 동작상태 요약
    status_cols = col_map["센서"].get("동작상태", [])
    if status_cols:
        latest_status = df[status_cols].iloc[-1]
        summary["operation"] = {
            "total": len(status_cols),
            "running": int(latest_status.sum()),
            "stopped": int((latest_status == 0).sum()),
        }

    return summary


def get_timeseries(df: pd.DataFrame, columns: list, resample: str = "5min") -> dict:
    """선택 컬럼의 시계열 데이터 반환 (리샘플링)"""
    result = {}
    available = [c for c in columns if c in df.columns]
    if not available:
        return result

    resampled = df[available].resample(resample).mean()
    result["timestamps"] = [str(ts) for ts in resampled.index]
    for col in available:
        result[col] = [
            round(v, 3) if not np.isnan(v) else None
            for v in resampled[col].tolist()
        ]
    return result


# ─────────────────────────────────────────────
# 7. 메인 파이프라인
# ─────────────────────────────────────────────

def run_pipeline(source) -> dict:
    """전체 파이프라인 실행 → 대시보드용 데이터 반환"""
    # 1) 로드
    df_raw = load_csv(source)

    # 2) 활성 컬럼만 선택
    active_cols = get_active_columns(df_raw)
    df = df_raw[active_cols].copy()

    # 3) 정제
    df = clean_data(df)

    # 4) 컬럼 분류
    col_map = classify_columns(df)

    # 5) 피처 엔지니어링
    df_feat = add_features(df)

    # 6) 이상 탐지
    alerts_df = detect_anomalies(df)

    # 7) 요약 통계
    summary = summarize(df, col_map)

    # 8) 대표 온도 시계열 (상위 10개)
    temp_cols_active = [c for c in col_map["센서"].get("온도", []) if df[c].abs().max() > 0][:10]
    ts_data = get_timeseries(df, temp_cols_active, resample="5min")

    # 9) 알람 직렬화
    alerts_list = []
    if not alerts_df.empty:
        alerts_list = alerts_df.head(200).to_dict(orient="records")
        for a in alerts_list:
            if hasattr(a["timestamp"], "isoformat"):
                a["timestamp"] = a["timestamp"].isoformat()

    return {
        "meta": {
            "rows": len(df),
            "active_columns": len(active_cols),
            "start": str(df.index.min()),
            "end": str(df.index.max()),
            "equipment": list(col_map["장비"].keys()),
        },
        "summary": summary,
        "alerts": alerts_list,
        "alert_count": len(alerts_df),
        "timeseries": ts_data,
        "column_map": {k: list(v.keys()) for k, v in col_map.items()},
    }
