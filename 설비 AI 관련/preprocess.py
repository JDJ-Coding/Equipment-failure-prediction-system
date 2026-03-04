"""
preprocess.py - 소성로 설비 센서 데이터 전처리 모듈

지원 형식:
  - CSV/TXT: 세미콜론 구분, cp949 인코딩, 헤더 2행
  - Excel (.xlsx): 헤더 1행 또는 2행 자동 감지

설비 자동 인식: 컬럼명에서 #NN_ 패턴을 추출하여 설비별 DataFrame 분리
"""

import io
import re
import pandas as pd
import numpy as np

# ─────────────────────────────────────────────
# 설비 인식 패턴 (컬럼명 기준 정규식)
# 새 설비 추가 시 이 목록에 튜플 추가
# ─────────────────────────────────────────────
EQUIPMENT_PATTERNS = [
    ('RHK-A',    r'^#01_A_'),
    ('RHK-B',    r'^#01_B_'),
    ('PTK-히터', r'^#01_.+PTK'),
    ('NCF1',     r'^\[NCF1\]_|^NCF1\s'),
    ('PNCF1',    r'^PNCF1\s|^PNCF01\s'),
    ('RHK#A',    r'^RHK#A\s'),
    ('RHK#B',    r'^RHK#B\s'),
]

# PLC 오버플로 오류 코드 임계값 (이 값 이상이면 NaN 처리)
ERROR_THRESHOLD = 60000

# 센서 카테고리 분류 규칙
SENSOR_CATEGORY_RULES = [
    ('온도(℃)',     [r'TEMP PV', r'온도']),
    ('전류(A)',     [r'\[A\]', r'전류\(A\)', r'SCR.*A\]']),
    ('전력(kW/W)', [r'\[kW\]', r'\[W\]', r'전력\(kW\)', r'전력\(W\)']),
    ('전압(V)',    [r'\[V\]', r'전압\(V\)']),
    ('출력률(%)',   [r'\[%\]', r'출력률', r'제어출력']),
    ('압력',        [r'\[mmH2O\]', r'\[Pa\]', r'압력']),
    ('유량',        [r'\[%/FLOW\]', r'FLOW', r'유량']),
    ('모터/상태',   [r'Motor', r'motor', r'Switch', r'ELB']),
]


# ─────────────────────────────────────────────
# 핵심 함수들
# ─────────────────────────────────────────────

def load_raw(source, file_ext: str = 'txt') -> tuple:
    """
    데이터 파일 로드

    Parameters
    ----------
    source : str | file-like
        파일 경로 또는 업로드된 파일 객체 (st.file_uploader 결과)
    file_ext : str
        파일 확장자 ('txt', 'csv', 'xlsx')

    Returns
    -------
    (idx_header, desc_header, df_raw)
        idx_header  : [115:0], [115:1] ... 형태의 인덱스 컬럼명 리스트
        desc_header : #01_PTK_Heater... 형태의 설명 컬럼명 리스트
        df_raw      : 원시 데이터 DataFrame (문자열, 컬럼명 = desc_header)
    """
    if file_ext == 'xlsx':
        return _load_excel(source)
    else:
        return _load_csv(source)


def _load_csv(source) -> tuple:
    """CSV/TXT 파일 로드 (세미콜론 구분, cp949, 헤더 2행)"""
    # 파일 객체인지 경로인지 구분
    if hasattr(source, 'read'):
        # 업로드된 파일 객체 → bytes 읽기
        raw_bytes = source.read()
        lines = raw_bytes.decode('cp949').splitlines()
        idx_header  = lines[0].strip().split(';')
        desc_header = lines[1].strip().split(';')
        data_text = '\n'.join(lines[2:])
        df = pd.read_csv(
            io.StringIO(data_text),
            sep=';', header=None, dtype=str, low_memory=False
        )
    else:
        # 파일 경로 문자열
        with open(source, encoding='cp949') as f:
            idx_header  = f.readline().strip().split(';')
            desc_header = f.readline().strip().split(';')
            df = pd.read_csv(f, sep=';', header=None, dtype=str, low_memory=False)

    # 컬럼명 = desc_header 로 지정 (길이 불일치 방어)
    n_cols = len(df.columns)
    df.columns = desc_header[:n_cols]

    # 중복 컬럼명 → 인덱스 ID 붙여서 유일화
    if df.columns.duplicated().any():
        df.columns = _deduplicate_columns(df.columns.tolist(), idx_header[:n_cols])

    return idx_header, desc_header, df


def _load_excel(source) -> tuple:
    """Excel(.xlsx) 파일 로드, 헤더 1/2행 자동 감지"""
    df_raw = pd.read_excel(source, header=None, dtype=str, engine='openpyxl')
    df_raw = df_raw.fillna('')  # NaN → 빈 문자열

    # 첫 행이 [115:0] 같은 인덱스 형태면 2행 헤더로 판단
    first_cell = str(df_raw.iloc[0, 1]) if df_raw.shape[1] > 1 else ''
    if first_cell.startswith('['):
        idx_header  = df_raw.iloc[0].tolist()
        desc_header = df_raw.iloc[1].tolist()
        df = df_raw.iloc[2:].reset_index(drop=True)
    else:
        idx_header  = []
        desc_header = df_raw.iloc[0].tolist()
        df = df_raw.iloc[1:].reset_index(drop=True)

    df.columns = desc_header[:len(df.columns)]

    if df.columns.duplicated().any():
        df.columns = _deduplicate_columns(df.columns.tolist(), idx_header[:len(df.columns)])

    return idx_header, desc_header, df


def _deduplicate_columns(cols: list, idx_header: list) -> list:
    """중복 컬럼명 유일화: 중복 시 인덱스 ID를 접미사로 붙임"""
    seen = {}
    result = []
    for i, col in enumerate(cols):
        if col in seen:
            suffix = idx_header[i] if i < len(idx_header) else str(i)
            result.append(f"{col}__{suffix}")
        else:
            result.append(col)
            seen[col] = True
    return result


def clean_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """
    문자열 DataFrame을 수치형으로 변환하고 전처리

    1. Time 컬럼 → datetime 파싱 (DD.MM.YYYY HH:MM:SS.ffffff)
    2. 나머지 컬럼 → float 변환
    3. >= ERROR_THRESHOLD 값 → NaN (PLC 오버플로 코드 제거)
    4. 결측치: ffill → bfill
    5. 전부 NaN 컬럼, 전부 0 컬럼 제거

    Returns
    -------
    pd.DataFrame (인덱스 = datetime)
    """
    df = df.copy()

    # Time 컬럼 찾기 (대소문자 무관)
    time_col = None
    for c in df.columns:
        if str(c).strip().lower() == 'time':
            time_col = c
            break

    if time_col is None:
        raise ValueError("Time 컬럼을 찾을 수 없습니다. 컬럼명을 확인해주세요.")

    # Time 파싱
    df[time_col] = pd.to_datetime(
        df[time_col],
        format='%d.%m.%Y %H:%M:%S.%f',
        errors='coerce'
    )
    df = df.dropna(subset=[time_col]).sort_values(time_col).reset_index(drop=True)
    df = df.set_index(time_col)
    df.index.name = 'Time'

    # 수치 변환
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # PLC 오버플로 오류 코드 제거
    df = df.where(df < ERROR_THRESHOLD, other=np.nan)

    # 결측치 처리
    df = df.ffill().bfill()

    # 전부 NaN 컬럼 제거
    df = df.dropna(axis=1, how='all')

    # 전부 0 컬럼 제거 (미가동 설비 센서)
    nonzero_mask = (df.abs() > 1e-6).any(axis=0)
    df = df.loc[:, nonzero_mask]

    return df


def extract_equipment(df: pd.DataFrame) -> dict:
    """
    컬럼명 패턴으로 설비별 DataFrame 분리

    Parameters
    ----------
    df : 전처리 완료된 DataFrame (인덱스=datetime)

    Returns
    -------
    dict[str, pd.DataFrame]
        키: 설비 표시명 ('RHK-A', 'RHK-B', ...)
        값: 해당 설비의 센서 DataFrame
        (실제 데이터가 있는 설비만 포함)
    """
    equipment_dict = {}
    assigned_cols = set()

    for display_name, pattern in EQUIPMENT_PATTERNS:
        matched = [c for c in df.columns if re.search(pattern, str(c))]
        if not matched:
            continue

        sub_df = df[matched].copy()
        assigned_cols.update(matched)

        # 전부 0인 컬럼 제거
        active = (sub_df.abs() > 1e-6).any(axis=0)
        sub_df = sub_df.loc[:, active]

        if sub_df.empty:
            continue  # 해당 설비는 미가동 → 포함 안 함

        equipment_dict[display_name] = sub_df

    # 패턴에 매칭되지 않은 활성 컬럼 → '기타' 그룹
    remaining = [c for c in df.columns if c not in assigned_cols]
    if remaining:
        rest_df = df[remaining]
        active = (rest_df.abs() > 1e-6).any(axis=0)
        rest_df = rest_df.loc[:, active]
        if not rest_df.empty:
            equipment_dict['기타'] = rest_df

    return equipment_dict


def categorize_sensors(col_name: str) -> str:
    """
    컬럼명에서 센서 물리 카테고리 반환

    Returns: '온도(℃)', '전류(A)', '전력(kW/W)', '전압(V)',
             '출력률(%)', '압력', '유량', '모터/상태', '기타'
    """
    for category, patterns in SENSOR_CATEGORY_RULES:
        for p in patterns:
            if re.search(p, col_name, re.IGNORECASE):
                return category
    return '기타'


def get_sensor_display_name(col_name: str) -> str:
    """
    컬럼명에서 설비 접두사와 D-레지스터 주소 제거 후 간결한 이름 반환

    예) '#01_A_소성로 RHK_SCR H1U 전류(A) (D7000)' → 'SCR H1U 전류(A)'
    """
    name = str(col_name)
    # 설비 접두사 제거: #01_A_, #01_B_, [NCF1]_ 등
    name = re.sub(r'^#\d+_[A-Z]?_?', '', name)
    name = re.sub(r'^\[NCF\d+\]_', '', name)
    name = re.sub(r'^PNCF\d+\s+PTK\s+', '', name)
    name = re.sub(r'^RHK#[AB]\s+', '', name)
    # 소성로, 설비명 등 중간 텍스트 제거
    name = re.sub(r'^소성로\s+RHK_', '', name)
    name = re.sub(r'^소성로\s+PTK_', '', name)
    # D-레지스터 주소 제거: (D6300) 등
    name = re.sub(r'\s*\(D\d+\)\s*$', '', name)
    return name.strip() or col_name


def get_categories_by_equipment(equip_df: pd.DataFrame) -> dict:
    """
    설비 DataFrame의 컬럼들을 카테고리별로 그룹화

    Returns
    -------
    dict[str, list[str]]
        키: 카테고리명, 값: 해당 카테고리 컬럼명 리스트
    """
    categories = {}
    for col in equip_df.columns:
        cat = categorize_sensors(col)
        categories.setdefault(cat, []).append(col)
    # 정렬: 중요한 카테고리 먼저
    priority_order = ['온도(℃)', '전류(A)', '전력(kW/W)', '전압(V)',
                      '출력률(%)', '압력', '유량', '모터/상태', '기타']
    return {cat: categories[cat] for cat in priority_order if cat in categories}
