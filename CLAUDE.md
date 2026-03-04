# CLAUDE.md — Equipment Failure Prediction System

This file provides AI assistants with a comprehensive guide to the codebase, conventions, and development workflows for this project.

---

## Project Overview

An industrial equipment health monitoring web application for Korean manufacturing facilities (primarily sintering furnaces). It ingests multi-sensor CSV/Excel data, applies statistical anomaly detection, computes health scores (0-100) per equipment unit, and visualizes results in an interactive dashboard.

**Primary use case:** Predictive maintenance scheduling — identify which machines need inspection before failure occurs.

---

## Repository Structure

```
Equipment-failure-prediction-system/
├── CLAUDE.md                        ← This file
├── .gitignore
└── 설비 AI 관련/                    ← "Equipment AI Related" (main project root)
    ├── app.py                       ← PRIMARY entry point (Plotly Dash, drag/resize grid)
    ├── analysis.py                  ← Health scoring & anomaly detection logic
    ├── preprocess.py                ← Data loading & preprocessing pipeline
    ├── assets/
    │   └── custom.css               ← Dark theme styling (used by Dash)
    ├── Sample 데이터/               ← "Sample Data"
    │   ├── 소성로 히터 csv파일.txt  ← Sample TXT sensor data (cp949)
    │   └── 본소성 히터 csv 파일.xlsx ← Sample Excel sensor data
    ├── 사용자 사용방법.md           ← End-user guide (Korean)
    └── 관리자 사용방법.md           ← Admin/developer guide (Korean)
```

> Note: The top-level project directory name uses Korean characters. Always reference files from the repo root or use absolute paths to avoid shell encoding issues.

---

## Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.9+ |
| Primary UI | Plotly Dash | 4.0+ |
| Drag/resize grid | dash-draggable | 0.1.2+ |
| UI components | dash-bootstrap-components | 2.0+ |
| Charts | Plotly | 6.0+ |
| Data manipulation | Pandas | 2.0+ |
| Numerics | NumPy | 1.24+ |
| ML utilities | scikit-learn | 1.3+ |
| Excel support | openpyxl | 3.1+ |

**No requirements.txt exists.** Install dependencies with:
```bash
pip install dash dash-bootstrap-components dash-draggable pandas numpy plotly scikit-learn openpyxl
```

---

## Running the Application

```bash
# Navigate to project directory
cd "설비 AI 관련"

# Primary dashboard (Plotly Dash — drag/resize/add/remove panels)
python app.py
# → http://127.0.0.1:8050

# Network-accessible deployment
python app.py  # edit host/port in app.run() call at bottom of file
```

Once running, upload a CSV/TXT/XLSX file from `Sample 데이터/` to test functionality.

---

## Architecture & Data Flow

```
User uploads file (CSV/TXT/XLSX)
         │
         ▼
preprocess.py
  load_raw(source, file_ext)
    → (idx_headers, desc_headers, raw_df)
  clean_numeric(raw_df)
    → preprocessed_df  [datetime-indexed, numeric]
  extract_equipment(df)
    → {equipment_name: equipment_df, ...}
         │
         ▼ [per equipment]
analysis.py
  detect_anomalies(df)
    → anomaly_df  [boolean DataFrame]
  compute_health_score(df, anomaly_df)
    → {score, sensor_scores, anomaly_rates}
  compute_rolling_stats(df, windows=[10,30,60])
    → rolling means per window
         │
         ▼
app.py
  Renders gauge, risk cards, time series, report, priority table
```

---

## Module Responsibilities

### `preprocess.py` — Data Loading & Normalization

**Key functions:**
- `load_raw(source, file_ext)` — Reads CSV/TXT (cp949 encoding, semicolon-delimited) or XLSX; handles 2-row headers (index IDs + sensor descriptions)
- `clean_numeric(df)` — Parses `DD.MM.YYYY HH:MM:SS.ffffff` timestamps, converts columns to numeric, removes PLC overflow codes (`> ERROR_THRESHOLD = 60000`)
- `extract_equipment(df)` — Splits DataFrame by equipment ID using regex patterns in `EQUIPMENT_PATTERNS`
- `categorize_sensors(col_name)` — Classifies sensor by name pattern (temperature, current, voltage, etc.)
- `get_sensor_display_name(col_name)` — Cleans column names for display

**Important constants:**
```python
ERROR_THRESHOLD = 60000        # PLC overflow sentinel value — rows with this are dropped
EQUIPMENT_PATTERNS = [...]     # Regex patterns: RHK-A, RHK-B, PTK-히터, NCF1, PNCF1, ...
SENSOR_CATEGORY_RULES = [...]  # Sensor type classification by column name patterns
```

### `analysis.py` — Health Scoring & Anomaly Detection

**Key functions:**
- `detect_anomalies(df)` — Combined Z-score (threshold 3.0) + IQR (multiplier 1.5) method; skips binary (on/off) columns
- `compute_health_score(df, anomaly_df)` — Weighted average of sensor scores with recent-state penalty
- `compute_rolling_stats(df, windows)` — 10/30/60-minute rolling means for trend analysis
- `get_top_risk_sensors(health_result, n=5, df)` — Returns N worst sensors with anomaly rates
- `generate_korean_report(equip_name, health_result, df)` — Generates formatted Korean-language maintenance report
- `summarize_all_equipment(equipment_dict)` — Priority ranking table across all equipment

**Health score algorithm:**
```
For each sensor:
  anomaly_rate = anomaly_count / total_rows
  sensor_score = 100 * (1 - anomaly_rate)
  # Recent penalty: if last 60-min anomaly rate is elevated, subtract up to 20 points
  sensor_score -= recent_60min_rate * 20  (floor 0)

Equipment score = weighted_average(sensor_scores, weights=CATEGORY_WEIGHTS)
```

**Category weights (higher = more influential on score):**
```python
CATEGORY_WEIGHTS = {
    'temperature': 3.0,
    'current':     2.5,
    'power':       2.0,
    'pressure':    2.0,
    'voltage':     1.5,
    'output_pct':  1.5,
    'flow':        1.0,
    'motor':       1.0,
    'other':       0.5,
}
```

**Health level thresholds:**
```python
HEALTH_LEVELS = [
    (80, 'Good',     'green',  'Monthly inspection'),
    (60, 'Caution',  'yellow', '2-week inspection'),
    (40, 'Warning',  'orange', '1-week inspection'),
    (0,  'Critical', 'red',    'Immediate shutdown'),
]
```

### `app.py` — Primary Plotly Dash UI with Draggable Grid

**This is the main entry point.** Built on `dash-draggable` (react-grid-layout wrapper) providing:
- **Drag** panels by their header bar to reposition
- **Resize** panels by dragging the bottom-right corner handle
- **Hide** panels via the ✕ button in each panel header
- **Restore** hidden panels via the sidebar checklist
- **Reset** all positions/visibility via the "↺ 레이아웃 초기화" button

**Key constants:**
```python
ALL_PANELS = {pid: title, ...}   # 6 panel definitions
DEFAULT_LAYOUT = [{i, x, y, w, h, minH, minW}, ...]  # default grid positions
```

**State management (two `dcc.Store` components):**
- `store-equip-json-dict`: equipment DataFrames as JSON, updated on file upload
- `layout-store`: panel positions/sizes, updated on drag/resize (via `main-grid.layout` input)

**Callback chain:**
```
File upload   → store-equip-json-dict → update_all_panels → fill panel content
Equip select  → update_all_panels
Cat checklist → update_timeseries_by_cat

Panel ✕ btn   → panel-visibility-toggle.value → update_grid_structure → main-grid.children
Sidebar toggle → panel-visibility-toggle.value → update_grid_structure
Drag/resize   → main-grid.layout → layout-store (save_layout)
Reset button  → layout-store + panel-visibility-toggle.value (reset to defaults)
```

**Note on content refresh after panel re-add:** When a hidden panel is restored, it appears with empty content until the user re-selects equipment or changes the rolling window. This is by design to avoid race conditions between grid structure and content callbacks.

---

## Input Data Format

### CSV / TXT Files
```
[115:0];[115:1];[115:2];...       ← Row 1: PLC index IDs
#01_A_RHK-A 온도;#01_B 전류;...   ← Row 2: Sensor descriptions
14.09.2025 00:16:15.030000;123.4;456.7;...  ← Data rows
```

- Encoding: **cp949** (EUC-KR Korean)
- Delimiter: **semicolon (`;`)**
- Timestamp format: `DD.MM.YYYY HH:MM:SS.ffffff`
- First column is always the timestamp

### Excel (XLSX)
Same logical structure; first two rows are header rows, openpyxl handles encoding automatically.

### PLC Overflow Cleanup
Values `>= 60000` are treated as sensor error codes and replaced with `NaN`.

---

## Code Conventions

### Naming
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `Z_THRESHOLD`, `CATEGORY_WEIGHTS`)
- **Functions**: `snake_case` (e.g., `compute_health_score`, `detect_anomalies`)
- **Variables**: Mix of English (`sensor_score`, `anomaly_df`) and Korean (`건강도`, `이상감지`) — prefer English for new code
- **Module-level dictionaries**: Used for configuration (no separate config files)

### Error Handling
- UI callbacks wrapped in `try-except`, errors displayed in the UI
- Data parsing uses `pd.to_numeric(..., errors='coerce')` (silent NaN for bad values)
- No custom exception classes — standard Python exceptions used

### Korean Language
The UI, reports, and documentation heavily use Korean. Comments in source files may be in Korean or English. Do not alter Korean-language strings in UI text, report generators, or documentation files without explicit instruction.

---

## Adding New Equipment Types

Edit `EQUIPMENT_PATTERNS` in `preprocess.py`:
```python
EQUIPMENT_PATTERNS = [
    r'RHK-[AB]',          # Existing: Resistance heater
    r'PTK-히터',           # Existing: Pottery kiln heater
    r'YOUR-NEW-PATTERN',   # New pattern added here
]
```

Patterns are evaluated as Python regex against equipment description column values.

---

## Adding New Sensor Categories

Edit `SENSOR_CATEGORY_RULES` in `preprocess.py` and `CATEGORY_WEIGHTS` in `analysis.py`:
```python
# preprocess.py
SENSOR_CATEGORY_RULES = [
    ...
    (r'진동|vibration', 'vibration'),  # New category
]

# analysis.py
CATEGORY_WEIGHTS = {
    ...
    'vibration': 2.0,  # Assign appropriate weight
}
```

---

## Tuning Anomaly Detection

All thresholds are in `analysis.py`:
```python
Z_THRESHOLD = 3.0      # Raise to reduce false positives (less sensitive)
IQR_MULTIPLIER = 1.5   # Raise to reduce false positives (less sensitive)
```

Lower values = more anomalies detected = lower health scores (more conservative).

---

## Testing

**There is no automated test suite.** Manual testing steps:

1. Start the application: `python app.py`
2. Upload `Sample 데이터/소성로 히터 csv파일.txt`
3. Verify:
   - Equipment dropdown populates with recognized equipment IDs
   - Health score gauge shows a value between 0-100
   - Anomaly shading appears as red regions in time series
   - Priority table lists all equipment sorted by health score
4. Test Excel upload with `Sample 데이터/본소성 히터 csv 파일.xlsx`
5. Verify both files produce consistent results for overlapping data

**Future:** Add `pytest` with unit tests for `detect_anomalies()`, `compute_health_score()`, and `load_raw()` using the sample data files as fixtures.

---

## Known Issues & Planned Improvements

| Issue | Status | Fix |
|-------|--------|-----|
| Panel content empty after re-add | By design | Re-select equipment to refresh |
| No persistence between sessions | Architecture | Stateless by design; future: add SQLite for result archival |
| No automated tests | Gap | Add pytest suite with sample data fixtures |
| No requirements.txt | Gap | Add requirements file with pinned versions |

---

## Development Workflow

```bash
# 1. Set up environment
python -m venv .venv
source .venv/bin/activate        # Linux/Mac
# .venv\Scripts\activate         # Windows

pip install dash dash-bootstrap-components dash-draggable pandas numpy plotly scikit-learn openpyxl

# 2. Run the app in development
cd "설비 AI 관련"
python app.py

# 3. Make changes, test manually with sample data

# 4. Commit
git add -A
git commit -m "descriptive message in English or Korean"
git push -u origin <branch-name>
```

---

## Important Notes for AI Assistants

1. **Korean file/directory names**: The main project directory is named `설비 AI 관련` (Korean). Always quote paths in shell commands: `cd "설비 AI 관련"`.

2. **No requirements.txt**: Dependencies are documented only in this file. Don't assume pip-installable packages beyond those listed above.

3. **Single UI implementation**: `app.py` (Plotly Dash) is the only UI. It calls `preprocess.py` and `analysis.py` — changes to those modules affect the UI.

4. **In-memory only**: No database, no persistent storage. All analysis runs fresh on each file upload. Session data is lost on page refresh.

5. **Korean strings**: Do not auto-translate or modify Korean-language UI strings, variable names, or report templates without explicit user instruction.

6. **No test runner**: There is no `pytest`, `unittest`, or other test framework. Do not assume `make test` or `npm test` work. Manual testing via the running app is the only verification method.

7. **Sample data encoding**: The `.txt` sample file uses cp949 (Korean EUC) encoding. Opening it in a text editor or with `open(..., encoding='utf-8')` will produce garbled text. Always specify `encoding='cp949'`.
