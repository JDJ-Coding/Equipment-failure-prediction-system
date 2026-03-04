# 소성로 히터 고장예지 대시보드

리튬이온 배터리 소성로(Kiln) 히터 설비 데이터를 분석하고
실시간 모니터링 + 고장예지를 제공하는 웹 대시보드입니다.

---

## 🚀 빠른 시작

### 방법 1: 로컬 개발 실행

#### 백엔드 (FastAPI)
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

#### 프론트엔드 (React + Vite)
```bash
cd frontend
npm install
npm run dev
# http://localhost:3000 에서 접속
```

### 방법 2: Docker Compose
```bash
cd dashboard
docker-compose up --build
# 프론트엔드: http://localhost:3000
# API:        http://localhost:8000/docs
```

---

## 📁 디렉토리 구조

```
dashboard/
├── backend/
│   ├── main.py           # FastAPI 앱 + API 엔드포인트
│   ├── data_pipeline.py  # 데이터 파싱·전처리·이상탐지
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── UploadPage.jsx    # CSV 업로드 화면
│   │   │   ├── RealtimePage.jsx  # 실시간 대시보드
│   │   │   ├── AnalyticsPage.jsx # 분석 (히트맵, 상관관계)
│   │   │   └── AlertsPage.jsx    # 이상 알람 & 타임라인
│   │   └── hooks/useApi.js
│   ├── package.json
│   ├── vite.config.js
│   ├── nginx.conf
│   └── Dockerfile
└── docker-compose.yml
```

---

## 🔌 API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/upload` | CSV 업로드 + 전체 분석 |
| POST | `/api/load-sample` | 서버 샘플 파일 로드 |
| GET  | `/api/summary` | 요약 통계 |
| GET  | `/api/alerts` | 이상 알람 목록 |
| GET  | `/api/timeseries` | 시계열 데이터 |
| GET  | `/api/heatmap` | 존별×시간대 히트맵 |
| GET  | `/api/correlation` | 변수 간 상관관계 |
| GET  | `/api/meta` | 데이터 메타 정보 |

상세 API 문서: http://localhost:8000/docs

---

## 📊 대시보드 페이지

### 1. 업로드 페이지 (`/`)
- CSV 드래그&드롭 업로드
- 서버 샘플 파일 로드
- 분석 완료 시 주요 지표 미리보기

### 2. 실시간 대시보드 (`/realtime`)
- 5개 KPI 카드: 최고 온도, 최대 전류, SCR 출력, 모터 상태
- 온도 5분 평균 트렌드 (Recharts 라인 차트)
- 히터 저항 노화율 바 차트
- 장비 선택 (RHK-A / RHK-B)

### 3. 분석 대시보드 (`/analytics`)
- 히터 존별 × 시간대 히트맵 (전류/온도/저항/출력)
- 변수 간 상관관계 매트릭스
- 핵심 관찰사항 & 권고 조치 카드

### 4. 알람 페이지 (`/alerts`)
- CRITICAL / WARNING 필터
- 이상 알람 타임라인 (발생 시각, 규칙, 측정값)
- 7가지 룰 기준 설명

---

## ⚙️ 고장예지 룰

| 룰 | 기준 | 심각도 |
|----|------|--------|
| 히터 단선 | 전류 < 평균×0.3 | CRITICAL |
| SCR 출력 초과 | 출력 > 95% | CRITICAL |
| 모터/팬 정지 | 상태 1→0 전환 | CRITICAL |
| 절연불량 | 전류 > 평균×1.3 | WARNING |
| 저항 증가 | 저항 > 기준×1.1 | WARNING |
| SCR 출력 근접 | 출력 85~95% | WARNING |
| 온도 급변 | 변화율 > ±10°C/분 | WARNING |
