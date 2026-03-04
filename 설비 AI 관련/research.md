# 설비 이상예지 대시보드 — 심층 기술 분석 보고서

## 1. 코드베이스 전체 구조

```
설비 AI 관련/
├── dashboard.py   (691 lines) — Streamlit 메인 앱, UI 전체 조율
├── analysis.py    (431 lines) — 건강도 분석, 이상 탐지 순수 Python 로직
├── preprocess.py  (298 lines) — 파일 로드, 수치 정제, 설비 분리
```

**데이터 흐름:**
```
파일 업로드(bytes)
    ↓ cached_load()
load_raw() → clean_numeric() → extract_equipment()
    → {설비명: DataFrame_JSON} 딕셔너리
    ↓ cached_analysis(equip_json)
detect_anomalies() → compute_health_score() → compute_rolling_stats()
    → {anomaly_json, health_score, rolling_mean_10/30/60, ...}
    ↓ 복원 및 UI 렌더링
건강도 게이지 / 위험 센서 TOP5 / 시계열 차트 / 리포트 / 우선순위 테이블
```

---

## 2. UI 패널 목록 (렌더링 순서 기준)

| # | 패널 | 파일:라인 | 함수/위젯 |
|---|------|-----------|-----------|
| 1 | 메인 타이틀 | dashboard.py:439 | `st.title()` |
| 2 | 쉬운 설명 Expander | dashboard.py:529 | `render_easy_explanation()` → `st.expander()` |
| 3 | 건강도 게이지 (좌) | dashboard.py:535~546 | `st.plotly_chart(render_gauge())` |
| 4 | 위험 센서 TOP5 (우) | dashboard.py:553~555 | `render_top_risks()` → HTML 카드 |
| 5 | 시계열 차트 | dashboard.py:560~592 | `st.multiselect()` + `st.plotly_chart()` |
| 6 | 한국어 리포트 | dashboard.py:595~598 | `st.expander()` + `st.text()` (조건부) |
| 7 | 전체 설비 우선순위 표 | dashboard.py:601~668 | `st.dataframe()` (조건부) |
| 8 | PPT 5줄 요약 | dashboard.py:671~676 | `st.markdown()` (조건부) |
| 9 | 푸터 | dashboard.py:681~686 | `st.caption()` |

---

## 3. Streamlit 패널 커스터마이즈 기술 분석

### 근본적 제약
Streamlit은 **서버 사이드 렌더링(SSR)** 방식으로 동작한다.
- UI 요소의 **위치는 코드 실행 순서**에 의해 결정
- 인터랙션 발생 → Python 스크립트 **전체 top-to-bottom 재실행**
- 진짜 드래그&드롭은 React 기반 커스텀 컴포넌트로만 가능

### 현재 구현 (on/off만 가능)
```python
# 사이드바 체크박스 (dashboard.py:503~505)
show_report   = st.checkbox('한국어 분석 리포트', value=True)
show_priority = st.checkbox('전체 설비 정비 우선순위', value=True)
show_ppt      = st.checkbox('PPT 5줄 요약', value=False)
```
→ 표시/숨김 제어만 가능, 순서 변경 불가

### session_state 기반 패널 관리 (구현 가능)
```python
if 'panel_order' not in st.session_state:
    st.session_state.panel_order = ['gauge_risks', 'timeseries', 'report', 'priority']

# UP/DOWN 버튼으로 순서 변경 → st.rerun() 호출
# 렌더링 시 순서 배열을 따라 함수 호출
for pid in st.session_state.panel_order:
    if st.session_state.panel_visible.get(pid, True):
        RENDERERS[pid]()
```

### 외부 라이브러리 옵션
| 라이브러리 | 기능 | 기존 Plotly 호환 | 평가 |
|---|---|---|---|
| streamlit-elements | 드래그+리사이즈 | ❌ 불가 | 기존 위젯과 호환 안 됨 |
| streamlit-sortables | 순서 변경만 | ✅ 가능 | 현실적 선택 |
| 순수 session_state | 버튼식 순서 변경 | ✅ 완전 호환 | 가장 안정적 |

**권장: streamlit-sortables + session_state 조합**

---

## 4. 타이틀 가림 문제 원인

### 현재 코드 (dashboard.py:47)
```css
.block-container { padding-top: 1rem; padding-bottom: 1rem; }
```

### 문제 구조
```
브라우저 뷰포트
┌──────────────────────────────────────┐
│ Streamlit 고정 헤더 바 (높이 ~3~4rem)│ ← position: fixed
├──────────────────────────────────────┤
│ block-container (padding-top: 1rem)  │ ← 헤더보다 작아서 가려짐!
│  ┌────────────────────────────────┐  │
│  │ 🏭 설비 이상예지 모니터링...   │  │ ← 타이틀이 헤더 뒤에 숨음
```

### 원인
1. padding-top: 1rem이 헤더 높이(~3.5rem)보다 작음
2. Streamlit 1.38+에서 선택자가 `.stAppViewBlockContainer`로 변경되어 CSS 자체가 무시될 수 있음

### 해결책
```css
/* 버전별 선택자 병행 사용 */
.block-container { padding-top: 3.5rem; }
.stAppViewBlockContainer { padding-top: 3.5rem; }
section.stMain .block-container { padding-top: 3.5rem; }
```

---

## 5. layout='wide' 동작 방식

| 속성 | centered (기본) | wide |
|---|---|---|
| `max-width` | ~730px | 제한 없음 (화면 전체 폭) |
| 좌우 padding | 1rem | ~5rem |
| `padding-top` | 영향 없음 | 영향 없음 |

**타이틀 가림 문제와 layout='wide'는 독립적 — padding-top만의 문제**
