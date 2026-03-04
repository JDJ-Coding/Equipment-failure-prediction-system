# 구현 계획: 패널 커스터마이즈 + 타이틀 가림 해결

## 요청 사항
1. 대시보드 패널을 사용자가 자유롭게 표시/숨김, 순서 변경
2. Main Title 텍스트가 가려지는 문제 해결

---

## 접근 방식 선택

### 패널 커스터마이즈: session_state 기반 (채택)

| 방식 | 장점 | 단점 |
|------|------|------|
| **session_state (채택)** | 추가 설치 없음, Plotly 완전 호환 | 드래그 UX 아님 (버튼 방식) |
| streamlit-elements | 진짜 드래그&리사이즈 | Plotly 차트와 호환 안 됨 |
| streamlit-sortables | 시각적 드래그 | 결국 session_state 필요, 외부 CDN 의존 |

**추가 설치 필요 없음.** 기존 패키지(streamlit, pandas, numpy, plotly)로 구현.

---

## 구현 단계

### Step 1 — CSS padding-top 수정 (타이틀 가림 해결)
**파일:** `dashboard.py:47`
**원인:** `padding-top: 1rem`이 Streamlit 고정 헤더 높이(~3.5rem)보다 작아서 타이틀가 가려짐

```
수정 전: .block-container { padding-top: 1rem;   padding-bottom: 1rem; }
수정 후: .block-container { padding-top: 3.5rem; padding-bottom: 1rem; }
```

---

### Step 2 — 패널 상수 정의 추가
**파일:** `dashboard.py` (main() 함수 위에 추가)

관리할 패널 6개:
- `easy_explain` : ❓ 건강도/이상감지 설명
- `gauge_risks`  : 📊 건강도 게이지 + 위험센서 TOP5
- `timeseries`   : 📈 센서 시계열 차트
- `report`       : 📋 한국어 분석 리포트
- `priority`     : 🗂️ 전체 설비 우선순위 표
- `ppt_summary`  : 📊 PPT 5줄 요약

```python
PANEL_DEFINITIONS = {
    'easy_explain': {'label': '❓ 건강도/이상감지 설명',         'default_visible': True},
    'gauge_risks':  {'label': '📊 건강도 게이지 + 위험센서 TOP5','default_visible': True},
    'timeseries':   {'label': '📈 센서 시계열 차트',              'default_visible': True},
    'report':       {'label': '📋 한국어 분석 리포트',            'default_visible': True},
    'priority':     {'label': '🗂️ 전체 설비 우선순위 표',         'default_visible': True},
    'ppt_summary':  {'label': '📊 PPT 5줄 요약',                 'default_visible': False},
}
DEFAULT_PANEL_ORDER = ['easy_explain','gauge_risks','timeseries','report','priority','ppt_summary']
```

---

### Step 3 — session_state 초기화
**파일:** `dashboard.py:438` (main() 함수 첫 줄에 삽입)

```python
def main():
    if 'panel_order' not in st.session_state:
        st.session_state.panel_order = DEFAULT_PANEL_ORDER.copy()
    if 'panel_visible' not in st.session_state:
        st.session_state.panel_visible = {
            pid: PANEL_DEFINITIONS[pid]['default_visible'] for pid in PANEL_DEFINITIONS
        }
    st.title('🏭 설비 이상예지 모니터링 대시보드')
```

---

### Step 4 — 사이드바 패널 커스터마이즈 UI 교체
**파일:** `dashboard.py:501~505` (기존 show_report/show_priority/show_ppt 체크박스 교체)

```
기존:
  st.subheader('📋 표시 옵션')
  show_report   = st.checkbox(...)
  show_priority = st.checkbox(...)
  show_ppt      = st.checkbox(...)

변경:
  st.subheader('🎛️ 패널 커스터마이즈')
  st.caption('체크박스: 표시/숨김 | ▲▼: 순서 변경')

  각 패널마다 [체크박스 | ▲ | ▼] 3열 레이아웃
  + [🔄 초기화] 버튼
```

▲▼ 버튼 클릭 → `panel_order` 배열 swap → `st.rerun()` 으로 순서 즉시 반영

---

### Step 5 — 메인 콘텐츠를 패널 루프로 재구성
**파일:** `dashboard.py:529~676`

기존 순서 고정 렌더링 → panel_order 배열 순환 루프로 교체:

```python
for pid in st.session_state.panel_order:
    if not st.session_state.panel_visible.get(pid, True):
        continue

    if   pid == 'easy_explain': render_easy_explanation()
    elif pid == 'gauge_risks':  # 기존 게이지+위험센서 코드 동일
    elif pid == 'timeseries':   # 기존 시계열 코드 동일
    elif pid == 'report':       # 기존 리포트 코드 동일
    elif pid == 'priority':     # 기존 우선순위+PPT 코드 동일
```

기존 로직 변경 없음 — 구조(순서)만 변경.

---

## 수정 파일 요약

| 파일 | 수정 범위 | 내용 |
|------|-----------|------|
| `dashboard.py:47` | 1라인 변경 | padding-top: 1rem → 3.5rem |
| `dashboard.py:435~437` | 15라인 추가 | PANEL_DEFINITIONS, DEFAULT_PANEL_ORDER 상수 |
| `dashboard.py:438~446` | 10라인 추가 | session_state 초기화 |
| `dashboard.py:501~505` | 5라인 → 40라인 교체 | 사이드바 패널 커스터마이즈 UI |
| `dashboard.py:529~676` | 구조 재구성 | 패널 루프 방식으로 전환 (로직 동일) |

`analysis.py`, `preprocess.py` 수정 없음.

---

## 트레이드오프 및 고려사항

1. **순서 변경 시 전체 재렌더링**: ▲▼ 클릭 → st.rerun() → 앱 전체 재실행. Streamlit 구조상 불가피. 캐시(@st.cache_data) 덕분에 데이터 재계산은 없음.

2. **ppt_summary 패널**: 현재 priority 패널 내부에 중첩(dashboard.py:671~676). 독립 패널로 완전 분리하면 priority_df 재계산 비용 발생. → priority 내부에 유지하고 panel_visible['ppt_summary'] 값만 전달하는 방식으로 처리.

3. **padding-top 3.5rem**: Streamlit 기본 테마 기준. 버전에 따라 헤더 높이가 다를 수 있으나 3.5rem은 안전한 범용값. 더 확실한 방법은 헤더를 완전히 숨기는 CSS 추가 (선택적 적용).
