"""
소성로 히터 설비 고장예지 대시보드 - FastAPI 백엔드
"""

import json
import io
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from data_pipeline import (
    run_pipeline,
    load_csv,
    clean_data,
    classify_columns,
    detect_anomalies,
    summarize,
    get_timeseries,
    get_active_columns,
    get_analog_columns,
    EQUIPMENT_PATTERNS,
    EQUIPMENT_LABELS,
)

# ─────────────────────────────────────────────
app = FastAPI(
    title="소성로 히터 고장예지 시스템",
    description="리튬이온 배터리 소성로 히터 설비 데이터 분석 및 고장예지 API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
# 인메모리 캐시 (업로드된 데이터)
# ─────────────────────────────────────────────
_cache: dict = {}

SAMPLE_PATH = Path(__file__).parent.parent.parent / \
    "설비 AI 관련" / "Sample 데이터" / "소성로 히터 csv파일.txt"


def _load_cached(key: str = "default") -> Optional[dict]:
    return _cache.get(key)


def _set_cache(data: dict, key: str = "default"):
    _cache[key] = data


# ─────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────

@app.get("/", summary="헬스 체크")
def root():
    return {"status": "ok", "message": "소성로 히터 고장예지 API"}


@app.post("/api/upload", summary="CSV 파일 업로드 및 전체 분석")
async def upload_csv(file: UploadFile = File(...)):
    """
    CSV 파일을 업로드하면 전처리 → 이상탐지 → 요약 통계를 반환합니다.
    """
    if not file.filename.endswith((".csv", ".txt")):
        raise HTTPException(status_code=400, detail="CSV 또는 TXT 파일만 허용됩니다")

    content = await file.read()
    try:
        result = run_pipeline(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파이프라인 오류: {str(e)}")

    _set_cache({"raw_bytes": content, "result": result})
    return JSONResponse(content=_make_serializable(result))


@app.post("/api/load-sample", summary="샘플 파일 로드")
def load_sample():
    """서버에 저장된 샘플 CSV를 로드합니다."""
    if not SAMPLE_PATH.exists():
        raise HTTPException(status_code=404, detail=f"샘플 파일 없음: {SAMPLE_PATH}")

    try:
        result = run_pipeline(str(SAMPLE_PATH))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    with open(SAMPLE_PATH, "rb") as f:
        _set_cache({"raw_bytes": f.read(), "result": result})

    return JSONResponse(content=_make_serializable(result))


@app.get("/api/summary", summary="요약 통계 조회")
def get_summary():
    """업로드된 데이터의 요약 통계를 반환합니다."""
    cached = _load_cached()
    if not cached:
        raise HTTPException(status_code=404, detail="데이터 없음. /api/upload 먼저 호출하세요")
    return JSONResponse(content=_make_serializable(cached["result"]["summary"]))


@app.get("/api/alerts", summary="이상 알람 목록")
def get_alerts(
    severity: Optional[str] = Query(None, description="CRITICAL 또는 WARNING"),
    limit: int = Query(100, ge=1, le=1000),
):
    """탐지된 이상 알람 목록을 반환합니다."""
    cached = _load_cached()
    if not cached:
        raise HTTPException(status_code=404, detail="데이터 없음")

    alerts = cached["result"]["alerts"]
    if severity:
        alerts = [a for a in alerts if a.get("severity") == severity.upper()]

    return {"total": len(alerts), "items": alerts[:limit]}


@app.get("/api/timeseries", summary="시계열 데이터 조회")
def get_ts(
    columns: Optional[str] = Query(None, description="콤마 구분 컬럼명"),
    resample: str = Query("5min", description="리샘플 주기 (예: 1min, 5min, 15min, 1h)"),
    equipment: Optional[str] = Query(None, description="장비 필터: RHK-A, RHK-B"),
):
    """시계열 차트용 데이터를 반환합니다."""
    cached = _load_cached()
    if not cached:
        raise HTTPException(status_code=404, detail="데이터 없음")

    raw_bytes = cached["raw_bytes"]
    df_raw = load_csv(raw_bytes)
    active = get_active_columns(df_raw)
    df = clean_data(df_raw[active])
    analog = set(get_analog_columns(df))

    import re as _re
    if columns:
        col_list = [c.strip() for c in columns.split(",")]
    else:
        if equipment and equipment in EQUIPMENT_PATTERNS:
            ep = EQUIPMENT_PATTERNS[equipment]
            col_list = [c for c in df.columns
                        if _re.search(ep, c)
                        and ("온도" in c or "TEMP" in c)
                        and c in analog][:10]
        else:
            col_list = [c for c in df.columns
                        if ("온도" in c or "TEMP" in c) and c in analog][:10]

    ts_data = get_timeseries(df, col_list, resample=resample)
    return JSONResponse(content=_make_serializable(ts_data))


@app.get("/api/heatmap", summary="히터 존별 히트맵 데이터")
def get_heatmap(
    metric: str = Query("전류", description="측정값 유형: 전류, 온도, 저항, 출력"),
    equipment: str = Query("RHK-A", description="장비: RHK-A, RHK-B"),
):
    """히터 존별 시간대 히트맵 데이터 반환"""
    cached = _load_cached()
    if not cached:
        raise HTTPException(status_code=404, detail="데이터 없음")

    import re
    raw_bytes = cached["raw_bytes"]
    df_raw = load_csv(raw_bytes)
    active = get_active_columns(df_raw)
    df = clean_data(df_raw[active])
    df.index = pd.to_datetime(df.index)
    analog = set(get_analog_columns(df))

    # 장비 패턴
    ep = EQUIPMENT_PATTERNS.get(equipment, EQUIPMENT_PATTERNS["RHK-A"])

    cols = [c for c in df.columns
            if re.search(ep, c) and metric in c and c in analog and df[c].abs().max() > 0]

    if not cols:
        return {"zones": [], "hours": [], "data": []}

    # 시간대별 평균
    df_sel = df[cols]
    df_sel = df_sel.resample("1h").mean()

    hours = [str(ts) for ts in df_sel.index]
    zones = [c.split("_")[-1].split(" ")[0] for c in cols]  # 간략화

    data = []
    for i, col in enumerate(cols):
        row = [round(v, 2) if not np.isnan(v) else None for v in df_sel[col].tolist()]
        data.append({"zone": zones[i], "column": col, "values": row})

    return {"zones": zones, "hours": hours, "data": data}


@app.get("/api/correlation", summary="상관관계 매트릭스")
def get_correlation(
    equipment: str = Query("RHK-A"),
    metric: str = Query("전류"),
    limit: int = Query(15, le=30),
):
    """선택 장비의 변수 간 상관관계 매트릭스 반환"""
    cached = _load_cached()
    if not cached:
        raise HTTPException(status_code=404, detail="데이터 없음")

    import re
    raw_bytes = cached["raw_bytes"]
    df_raw = load_csv(raw_bytes)
    active = get_active_columns(df_raw)
    df = clean_data(df_raw[active])

    ep = EQUIPMENT_PATTERNS.get(equipment, EQUIPMENT_PATTERNS["RHK-A"])
    cols = [c for c in df.columns
            if re.search(ep, c) and metric in c and df[c].abs().max() > 0][:limit]

    if len(cols) < 2:
        return {"columns": [], "matrix": []}

    corr = df[cols].corr().round(3)
    short_names = [c.split("_")[-1][:20] for c in cols]

    return {
        "columns": short_names,
        "full_columns": cols,
        "matrix": corr.values.tolist(),
    }


@app.get("/api/equipment", summary="설비별 현황")
def get_equipment_status():
    """모든 설비의 가동 현황 및 컬럼 수 반환"""
    cached = _load_cached()
    if not cached:
        raise HTTPException(status_code=404, detail="데이터 없음")

    import re
    raw_bytes = cached["raw_bytes"]
    df_raw = load_csv(raw_bytes)

    result = []
    for name, pat in EQUIPMENT_PATTERNS.items():
        cols = [c for c in df_raw.columns if re.search(pat, c)]
        active = [c for c in cols if df_raw[c].abs().max() > 0]
        analog = get_analog_columns(df_raw[active]) if active else []
        is_active = len(active) > 10

        result.append({
            "id": name,
            "label": EQUIPMENT_LABELS.get(name, name),
            "total_cols": len(cols),
            "active_cols": len(active),
            "analog_cols": len(analog),
            "status": "가동중" if is_active else "비가동",
        })

    return result


@app.get("/api/meta", summary="데이터 메타 정보")
def get_meta():
    cached = _load_cached()
    if not cached:
        raise HTTPException(status_code=404, detail="데이터 없음")
    return cached["result"]["meta"]


# ─────────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────────

def _make_serializable(obj):
    """numpy/pandas 타입을 JSON 직렬화 가능하게 변환"""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
