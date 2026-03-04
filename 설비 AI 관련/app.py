"""
app.py - 설비 이상예지 모니터링 대시보드 (Plotly Dash)

실행:
    python app.py
    → 브라우저에서 http://127.0.0.1:8050 열기

지원 파일 형식:
    - CSV / TXT (세미콜론 구분, cp949 인코딩)
    - Excel (.xlsx)
"""

import io
import base64

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from dash import dcc, html, callback, Input, Output, State, no_update

from preprocess import (
    load_raw, clean_numeric, extract_equipment,
    get_sensor_display_name, get_categories_by_equipment,
)
from analysis import (
    compute_rolling_stats, detect_anomalies, compute_health_score,
    get_top_risk_sensors, generate_korean_report, summarize_all_equipment,
    score_to_level,
)

# ─────────────────────────────────────────────
# 앱 초기화
# ─────────────────────────────────────────────
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    title='설비 이상예지 모니터링',
    suppress_callback_exceptions=True,
)


# ─────────────────────────────────────────────
# 헬퍼: 패널 카드 래퍼
# ─────────────────────────────────────────────
def panel_card(panel_id: str, title: str, children):
    return html.Div(
        id=panel_id,
        children=[
            html.H5(title),
            html.Div(children, style={'overflowY': 'auto'}),
        ],
        className='panel-card',
        style={'minHeight': '200px'},
    )


# ─────────────────────────────────────────────
# 사이드바
# ─────────────────────────────────────────────
def make_sidebar():
    return html.Div([
        html.H4('⚙️ 설정'),

        html.P('📂 데이터 파일', style={'color': '#888', 'fontSize': '0.85em', 'marginBottom': '6px'}),
        dcc.Upload(
            id='upload-data',
            children=html.Div([
                html.Div('📁', style={'fontSize': '1.5em', 'marginBottom': '4px'}),
                html.Div('파일을 끌어놓거나'),
                html.Div('클릭하여 선택', style={'color': '#00B4D8', 'fontWeight': 'bold'}),
                html.Div('CSV / TXT / XLSX', style={'fontSize': '0.75em', 'color': '#666', 'marginTop': '4px'}),
            ]),
            className='upload-box',
            multiple=False,
        ),
        html.Div(id='upload-status', style={'marginTop': '6px', 'fontSize': '0.8em', 'color': '#aaa'}),

        html.Div(className='divider'),

        html.P('🏭 설비 선택', style={'color': '#888', 'fontSize': '0.85em', 'marginBottom': '6px'}),
        dcc.Dropdown(
            id='equip-dropdown',
            options=[],
            placeholder='파일을 먼저 업로드하세요',
            style={'backgroundColor': '#2a2a4a', 'color': '#fff', 'border': '1px solid #444'},
            className='mb-2',
        ),

        html.Div(className='divider'),

        html.P('⏱ 이동 평균 기간', style={'color': '#888', 'fontSize': '0.85em', 'marginBottom': '6px'}),
        dcc.RadioItems(
            id='window-radio',
            options=[{'label': f' {w}분', 'value': w} for w in [10, 30, 60]],
            value=10,
            inline=True,
            style={'color': '#ccc', 'fontSize': '0.9em'},
        ),

        html.Div(className='divider'),

        html.P('🎛️ 패널 표시', style={'color': '#888', 'fontSize': '0.85em', 'marginBottom': '6px'}),
        dbc.Checklist(
            id='panel-visibility',
            options=[
                {'label': ' ❓ 건강도/이상감지 설명', 'value': 'panel-explain'},
                {'label': ' 📊 건강도 게이지',        'value': 'panel-gauge'},
                {'label': ' ⚠️ 위험센서 TOP5',        'value': 'panel-risks'},
                {'label': ' 📈 시계열 차트',           'value': 'panel-timeseries'},
                {'label': ' 📋 분석 리포트',           'value': 'panel-report'},
                {'label': ' 🗂️ 우선순위 표',           'value': 'panel-priority'},
            ],
            value=['panel-explain', 'panel-gauge', 'panel-risks',
                   'panel-timeseries', 'panel-report', 'panel-priority'],
            switch=True,
            style={'color': '#ccc', 'fontSize': '0.88em'},
        ),
    ], className='sidebar')


# ─────────────────────────────────────────────
# 앱 레이아웃
# ─────────────────────────────────────────────
app.layout = html.Div([
    dcc.Store(id='store-equip-json-dict'),

    dbc.Container([
        dbc.Row([
            dbc.Col(make_sidebar(), width=2),

            dbc.Col([
                html.Div([
                    html.Div('🏭 설비 이상예지 모니터링 대시보드', className='main-title'),
                    html.Hr(style={'borderColor': '#2a2a4a', 'margin': '8px 0 16px 0'}),
                ]),

                html.Div(id='main-grid', children=[

                    # ── 행 1: 건강도/이상감지 설명 (전폭) ──────────
                    dbc.Row([dbc.Col(
                        panel_card('panel-explain', '❓ 건강도와 이상감지란?', html.Div([
                            dbc.Row([
                                dbc.Col([
                                    html.P('🏥 건강도 점수', style={'color': '#00B4D8', 'fontWeight': 'bold', 'marginBottom': '4px'}),
                                    html.P('설비의 센서들이 얼마나 정상 범위 안에서 측정되는지를 0~100점으로 나타낸 점수입니다.',
                                           style={'fontSize': '0.85em', 'color': '#ccc'}),
                                    dbc.Table([html.Tbody([
                                        html.Tr([html.Td('🟢 80~100점'), html.Td('양호 — 정상 운전, 월 1회 정기 점검')]),
                                        html.Tr([html.Td('🟡 60~79점'), html.Td('주의 — 일부 이상, 2주 내 점검')]),
                                        html.Tr([html.Td('🟠 40~59점'), html.Td('경고 — 다수 이상, 1주 내 점검')]),
                                        html.Tr([html.Td('🔴 39점 이하'), html.Td('위험 — 즉시 가동 중단 및 긴급 정비')]),
                                    ])], bordered=False, size='sm', color='dark', style={'fontSize': '0.83em'}),
                                ], width=6),
                                dbc.Col([
                                    html.P('🔍 이상 감지란?', style={'color': '#00B4D8', 'fontWeight': 'bold', 'marginBottom': '4px'}),
                                    html.P('각 센서에는 "정상 범위"가 있습니다. 예를 들어 온도 센서 정상 범위가 800~1200℃라면:',
                                           style={'fontSize': '0.85em', 'color': '#ccc'}),
                                    html.Ul([
                                        html.Li('1,000℃ → ✅ 정상', style={'fontSize': '0.83em', 'color': '#aaa'}),
                                        html.Li('1,500℃ → ❌ 이상 (범위 초과)', style={'fontSize': '0.83em', 'color': '#E74C3C'}),
                                        html.Li('500℃   → ❌ 이상 (범위 미달)', style={'fontSize': '0.83em', 'color': '#E74C3C'}),
                                    ]),
                                    html.P('이상 감지 건수 = 정상 범위를 벗어난 측정값의 총 횟수',
                                           style={'fontSize': '0.82em', 'color': '#888', 'marginTop': '6px'}),
                                ], width=6),
                            ]),
                        ])),
                        width=12
                    )], className='mb-3'),

                    # ── 행 2: 게이지 (좌 5) + 위험센서 (우 7) ───────
                    dbc.Row([
                        dbc.Col(
                            panel_card('panel-gauge', '📊 설비 건강도', html.Div([
                                dcc.Graph(id='gauge-chart', config={'displayModeBar': False},
                                          style={'height': '220px'}),
                                html.Div(id='health-status-msg', style={'marginTop': '6px', 'fontSize': '0.88em'}),
                            ])),
                            width=5,
                        ),
                        dbc.Col(
                            panel_card('panel-risks', '⚠️ 주의가 필요한 센서 TOP 5', html.Div([
                                html.P(id='risks-caption', style={'color': '#888', 'fontSize': '0.8em', 'marginBottom': '8px'}),
                                html.Div(id='risks-cards'),
                            ])),
                            width=7,
                        ),
                    ], className='mb-3'),

                    # ── 행 3: 시계열 차트 (전폭) ─────────────────────
                    dbc.Row([dbc.Col(
                        panel_card('panel-timeseries', '📈 센서 시계열 분석', html.Div([
                            html.Div(id='category-selector-container'),
                            html.P(id='ts-caption', style={'color': '#888', 'fontSize': '0.8em', 'margin': '4px 0 6px 0'}),
                            dcc.Graph(id='timeseries-chart', config={'displayModeBar': True},
                                      style={'height': '380px'}),
                        ])),
                        width=12
                    )], className='mb-3'),

                    # ── 행 4: 한국어 분석 리포트 (전폭) ──────────────
                    dbc.Row([dbc.Col(
                        panel_card('panel-report', '📋 한국어 분석 리포트', html.Div([
                            html.Pre(id='report-text',
                                     style={'fontSize': '0.82em', 'color': '#ccc',
                                            'whiteSpace': 'pre-wrap', 'overflowY': 'auto',
                                            'maxHeight': '200px', 'backgroundColor': '#111',
                                            'padding': '10px', 'borderRadius': '6px'}),
                        ])),
                        width=12
                    )], className='mb-3'),

                    # ── 행 5: 전체 설비 우선순위 (전폭) ──────────────
                    dbc.Row([dbc.Col(
                        panel_card('panel-priority', '🗂️ 전체 설비 — 어떤 설비부터 점검할까?', html.Div([
                            html.Div(id='priority-status-msg', style={'marginBottom': '8px'}),
                            html.Div(id='priority-table-container'),
                            html.Hr(style={'borderColor': '#333'}),
                            html.P('📊 점수 계산 방법', style={'color': '#00B4D8', 'fontSize': '0.85em', 'marginBottom': '4px'}),
                            html.Ul([
                                html.Li('각 센서의 정상 범위를 벗어난 비율만큼 점수 감점 (100점 만점 시작)', style={'fontSize': '0.8em', 'color': '#aaa'}),
                                html.Li('온도 센서 ×3배 · 전류 ×2.5배 · 전력/압력 ×2배 비중으로 계산', style={'fontSize': '0.8em', 'color': '#aaa'}),
                                html.Li('이상감지율(%) = 전체 측정 중 정상 범위를 벗어난 값의 비율', style={'fontSize': '0.8em', 'color': '#aaa'}),
                            ]),
                        ])),
                        width=12
                    )], className='mb-3'),

                ]),  # main-grid end

            ], width=10, className='main-area'),
        ]),
    ], fluid=True),
], style={'minHeight': '100vh'})


# ─────────────────────────────────────────────
# 콜백 1: 파일 업로드 → 설비 데이터 저장
# ─────────────────────────────────────────────
@callback(
    Output('store-equip-json-dict', 'data'),
    Output('upload-status', 'children'),
    Output('equip-dropdown', 'options'),
    Output('equip-dropdown', 'value'),
    Input('upload-data', 'contents'),
    State('upload-data', 'filename'),
    prevent_initial_call=True,
)
def process_upload(contents, filename):
    if contents is None:
        return no_update, no_update, [], None

    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        file_ext = filename.rsplit('.', 1)[-1].lower()

        source = io.BytesIO(decoded)
        _, _, df_raw = load_raw(source, file_ext)
        df_clean = clean_numeric(df_raw)
        equip_dict = extract_equipment(df_clean)

        if not equip_dict:
            return None, html.Span('⚠️ 분석 가능한 설비 없음', style={'color': '#E74C3C'}), [], None

        equip_json_dict = {k: v.to_json(date_format='iso') for k, v in equip_dict.items()}
        options = [{'label': name, 'value': name} for name in equip_json_dict.keys()]
        first = options[0]['value']
        status = html.Span(f'✅ {filename}', style={'color': '#2ECC71'})
        return equip_json_dict, status, options, first

    except Exception as e:
        return None, html.Span(f'❌ 오류: {str(e)[:80]}', style={'color': '#E74C3C'}), [], None


# ─────────────────────────────────────────────
# 콜백 2: 설비/윈도우/스토어 변경 → 모든 패널 업데이트
# ─────────────────────────────────────────────
@callback(
    Output('gauge-chart', 'figure'),
    Output('health-status-msg', 'children'),
    Output('risks-caption', 'children'),
    Output('risks-cards', 'children'),
    Output('category-selector-container', 'children'),
    Output('ts-caption', 'children'),
    Output('timeseries-chart', 'figure'),
    Output('report-text', 'children'),
    Output('priority-status-msg', 'children'),
    Output('priority-table-container', 'children'),
    Input('equip-dropdown', 'value'),
    Input('window-radio', 'value'),
    Input('store-equip-json-dict', 'data'),
    prevent_initial_call=True,
)
def update_all_panels(selected, window, equip_json_dict):
    empty_fig = go.Figure()
    empty_fig.update_layout(
        paper_bgcolor='#1e2130', plot_bgcolor='#1e2130',
        font_color='#888', height=220,
        annotations=[dict(text='파일을 업로드하고 설비를 선택하세요',
                           xref='paper', yref='paper', x=0.5, y=0.5,
                           showarrow=False, font=dict(size=14, color='#888'))],
    )

    if not selected or not equip_json_dict or selected not in equip_json_dict:
        return (empty_fig, '', '', [], '', '', empty_fig, '', '', [])

    try:
        equip_json = equip_json_dict[selected]
        df = pd.read_json(equip_json)
        df.index = pd.to_datetime(df.index)

        anomaly_df = detect_anomalies(df)
        health     = compute_health_score(df, anomaly_df)
        rolling    = compute_rolling_stats(df)
        top_risks  = get_top_risk_sensors(health, n=5, df=df)

        rolling_df = rolling[window]['mean']
        score = health['score'] or 0.0
        level, desc = score_to_level(score)

        # 게이지
        gauge_fig = _make_gauge(score, selected)

        # 건강도 상태 메시지
        level_colors = {'양호': '#2ECC71', '주의': '#F1C40F', '경고': '#E67E22', '위험': '#E74C3C'}
        bar_color = level_colors.get(level, '#888')
        anomaly_pct = health['anomaly_rate'] * 100
        health_msg = html.Div([
            html.Span(f'■ {level}', style={'color': bar_color, 'fontWeight': 'bold', 'fontSize': '1.0em'}),
            html.Span(f' — {desc}', style={'color': '#ccc', 'fontSize': '0.9em'}),
            html.Br(),
            html.Span(
                f'센서 {len(df.columns)}개 중 전체 측정값의 {anomaly_pct:.1f}%가 정상 범위를 벗어났습니다.',
                style={'color': '#aaa', 'fontSize': '0.83em'},
            ),
        ])

        # 위험 센서 카드
        risks_caption = f'📌 {selected} 설비에서 정상 범위를 가장 많이 벗어난 센서 순서입니다.'
        risks_cards = _make_risk_cards(top_risks, len(df))

        # 시계열
        categories = get_categories_by_equipment(df)
        cat_options = list(categories.keys())
        default_cats = cat_options[:min(2, len(cat_options))]
        cat_selector = dcc.Checklist(
            id='cat-checklist',
            options=[{'label': f' {c}', 'value': c} for c in cat_options],
            value=default_cats,
            inline=True,
            style={'fontSize': '0.85em', 'color': '#ccc', 'marginBottom': '4px'},
        )
        selected_cols = []
        for cat in default_cats:
            selected_cols.extend(categories.get(cat, []))
        selected_cols = selected_cols[:10]
        ts_caption = (
            f'빨간 음영 = 이상 시간대  |  굵은 선 = {window}분 이동 평균  |  흐린 선 = 원시값'
        )
        ts_fig = _make_timeseries(df, anomaly_df, selected_cols, rolling_df, window)

        # 리포트
        report_text = generate_korean_report(selected, health, df)

        # 우선순위
        priority_msg, priority_table = _make_priority(equip_json_dict)

        return (
            gauge_fig, health_msg,
            risks_caption, risks_cards,
            cat_selector, ts_caption, ts_fig,
            report_text,
            priority_msg, priority_table,
        )

    except Exception as e:
        err = html.Span(f'❌ 분석 오류: {str(e)[:100]}', style={'color': '#E74C3C'})
        return (empty_fig, err, '', [], '', '', empty_fig, str(e), '', [])


# ─────────────────────────────────────────────
# 콜백 3: 카테고리 변경 → 시계열 업데이트
# ─────────────────────────────────────────────
@callback(
    Output('timeseries-chart', 'figure', allow_duplicate=True),
    Input('cat-checklist', 'value'),
    State('equip-dropdown', 'value'),
    State('window-radio', 'value'),
    State('store-equip-json-dict', 'data'),
    prevent_initial_call=True,
)
def update_timeseries_by_cat(selected_cats, selected, window, equip_json_dict):
    if not selected_cats or not selected or not equip_json_dict:
        return no_update

    try:
        df = pd.read_json(equip_json_dict[selected])
        df.index = pd.to_datetime(df.index)
        anomaly_df = detect_anomalies(df)
        rolling_df = compute_rolling_stats(df)[window]['mean']
        categories = get_categories_by_equipment(df)
        selected_cols = []
        for cat in selected_cats:
            selected_cols.extend(categories.get(cat, []))
        return _make_timeseries(df, anomaly_df, selected_cols[:10], rolling_df, window)
    except Exception:
        return no_update


# ─────────────────────────────────────────────
# 콜백 4: 패널 표시/숨김
# ─────────────────────────────────────────────
@callback(
    Output('panel-explain',    'style'),
    Output('panel-gauge',      'style'),
    Output('panel-risks',      'style'),
    Output('panel-timeseries', 'style'),
    Output('panel-report',     'style'),
    Output('panel-priority',   'style'),
    Input('panel-visibility', 'value'),
    prevent_initial_call=False,
)
def toggle_panels(visible_panels):
    visible_panels = visible_panels or []
    all_panels = ['panel-explain', 'panel-gauge', 'panel-risks',
                  'panel-timeseries', 'panel-report', 'panel-priority']
    show = {'minHeight': '200px'}
    hide = {'minHeight': '200px', 'display': 'none'}
    return tuple(show if p in visible_panels else hide for p in all_panels)


# ─────────────────────────────────────────────
# 내부 헬퍼 함수
# ─────────────────────────────────────────────
def _make_gauge(score: float, equip_name: str) -> go.Figure:
    if score is None:
        score = 0.0
    if score >= 80:
        bar_color = '#2ECC71'
    elif score >= 60:
        bar_color = '#F1C40F'
    elif score >= 40:
        bar_color = '#E67E22'
    else:
        bar_color = '#E74C3C'

    fig = go.Figure(go.Indicator(
        mode='gauge+number',
        value=score,
        title={'text': f'{equip_name}<br><span style="font-size:0.8em">설비 건강도</span>',
               'font': {'size': 13, 'color': '#ccc'}},
        gauge={
            'axis': {'range': [0, 100], 'tickfont': {'size': 10, 'color': '#888'},
                     'tickvals': [0, 20, 40, 60, 80, 100], 'tickcolor': '#555'},
            'bar': {'color': bar_color, 'thickness': 0.3},
            'bgcolor': 'rgba(0,0,0,0)',
            'steps': [
                {'range': [0,  40], 'color': 'rgba(231,76,60,0.2)'},
                {'range': [40, 60], 'color': 'rgba(230,126,34,0.2)'},
                {'range': [60, 80], 'color': 'rgba(241,196,15,0.15)'},
                {'range': [80, 100], 'color': 'rgba(46,204,113,0.15)'},
            ],
        },
        number={'suffix': '점', 'font': {'size': 28, 'color': bar_color}},
    ))
    fig.update_layout(
        height=220,
        margin=dict(l=20, r=20, t=50, b=10),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font_color='#ccc',
    )
    return fig


def _make_risk_cards(top_risks: list, total_rows: int) -> list:
    if not top_risks:
        return [html.P('이상이 탐지된 센서가 없습니다.', style={'color': '#aaa'})]

    cards = []
    for i, risk in enumerate(top_risks, 1):
        score = risk['score']
        if score < 40:
            css_class, emoji = 'danger', '🔴'
        elif score < 60:
            css_class, emoji = 'alert', '🟠'
        elif score < 80:
            css_class, emoji = 'warn', '🟡'
        else:
            css_class, emoji = 'good', '🟢'

        total = risk.get('total_rows', total_rows)
        anom_pct = (risk['anomaly_count'] / total * 100) if total > 0 else 0

        range_info = []
        if 'normal_min' in risk:
            range_info = [
                html.Span(f"정상범위: {risk['normal_min']} ~ {risk['normal_max']}", className='risk-range'),
                html.Span(f"평균: {risk.get('avg_value','-')}  최대: {risk.get('actual_max','-')}", className='risk-range'),
            ]

        score_color = '#E74C3C' if score < 60 else '#F1C40F' if score < 80 else '#2ECC71'
        cards.append(html.Div([
            html.Div([
                html.Span(f'{emoji} {i}위. ', style={'fontWeight': 'bold'}),
                html.Span(risk['display'], style={'fontWeight': 'bold', 'color': '#fff'}),
                html.Span(f"  [{risk['category']}]", style={'fontSize': '0.78em', 'color': '#888'}),
            ], style={'marginBottom': '4px'}),
            html.Div([
                html.Span('건강도: '),
                html.Span(f"{score:.1f}점", style={'color': score_color, 'fontWeight': 'bold'}),
                html.Span('  |  이상 감지: '),
                html.Span(f"{risk['anomaly_count']}건 / {total}건 ({anom_pct:.1f}%)", style={'fontWeight': 'bold'}),
            ], style={'fontSize': '0.83em', 'color': '#ccc', 'marginBottom': '4px'}),
            html.Div(range_info, style={'fontSize': '0.8em'}),
        ], className=f'risk-card {css_class}'))
    return cards


def _make_timeseries(df, anomaly_df, selected_cols, rolling_df, window) -> go.Figure:
    fig = go.Figure()
    if not selected_cols:
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font_color='#888', height=380,
            annotations=[dict(text='센서 카테고리를 선택하세요',
                               xref='paper', yref='paper', x=0.5, y=0.5,
                               showarrow=False, font=dict(size=14, color='#888'))],
        )
        return fig

    colors = px.colors.qualitative.Plotly
    combined_anomaly = anomaly_df[selected_cols].any(axis=1)
    in_anom, start_t = False, None
    for ts, val in combined_anomaly.items():
        if val and not in_anom:
            start_t = ts; in_anom = True
        elif not val and in_anom:
            fig.add_vrect(x0=start_t, x1=ts, fillcolor='rgba(231,76,60,0.15)', layer='below', line_width=0)
            in_anom = False
    if in_anom and start_t is not None:
        fig.add_vrect(x0=start_t, x1=combined_anomaly.index[-1],
                      fillcolor='rgba(231,76,60,0.15)', layer='below', line_width=0)

    for i, col in enumerate(selected_cols):
        short = get_sensor_display_name(col)
        c = colors[i % len(colors)]
        fig.add_trace(go.Scatter(
            x=df.index, y=df[col], name=short,
            line=dict(color=c, width=1), opacity=0.35,
            legendgroup=col, showlegend=True, hoverinfo='skip',
        ))
        if col in rolling_df.columns:
            fig.add_trace(go.Scatter(
                x=rolling_df.index, y=rolling_df[col],
                name=f'{short} ({window}분 평균)',
                line=dict(color=c, width=2.5),
                legendgroup=col, showlegend=True,
                hovertemplate=f'<b>{short}</b><br>값: %{{y:.2f}}<extra></extra>',
            ))

    fig.update_layout(
        xaxis_title='시간', yaxis_title='센서값',
        hovermode='x unified', height=380,
        legend=dict(orientation='h', yanchor='top', y=-0.18, xanchor='left', x=0, font=dict(size=10)),
        margin=dict(l=50, r=20, t=20, b=100),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(30,33,48,0.8)',
        font_color='#ccc',
        xaxis=dict(gridcolor='#2a2a4a'), yaxis=dict(gridcolor='#2a2a4a'),
    )
    return fig


def _make_priority(equip_json_dict: dict):
    all_equip = {}
    for k, v in equip_json_dict.items():
        df = pd.read_json(v)
        df.index = pd.to_datetime(df.index)
        all_equip[k] = df

    priority_df = summarize_all_equipment(all_equip)
    if priority_df.empty:
        return html.P('분석 가능한 설비 데이터가 없습니다.', style={'color': '#aaa'}), []

    priority_df = priority_df.copy()
    priority_df.insert(0, '점검순서', range(1, len(priority_df) + 1))
    priority_df['건강도'] = priority_df['건강도'].round(1)
    priority_df['이상감지율(%)'] = priority_df['이상감지율(%)'].round(1)

    all_good = (priority_df['건강도'] >= 80).all()
    if all_good:
        status_msg = dbc.Alert('✅ 현재 모든 설비가 양호 상태입니다.', color='success',
                                className='p-2', style={'fontSize': '0.85em'})
    else:
        critical_cnt = int((priority_df['건강도'] < 60).sum())
        warn_cnt = int(((priority_df['건강도'] >= 60) & (priority_df['건강도'] < 80)).sum())
        parts = []
        if critical_cnt: parts.append(f'🔴 즉시 점검 필요: {critical_cnt}개 설비')
        if warn_cnt:     parts.append(f'🟡 주의 관찰: {warn_cnt}개 설비')
        status_msg = dbc.Alert(' | '.join(parts), color='warning',
                                className='p-2', style={'fontSize': '0.85em'})

    rows = []
    for _, row in priority_df.iterrows():
        score = row['건강도']
        if score >= 80:
            bg, fg = 'rgba(46,204,113,0.15)', '#2ECC71'
        elif score >= 60:
            bg, fg = 'rgba(241,196,15,0.12)', '#F1C40F'
        elif score >= 40:
            bg, fg = 'rgba(230,126,34,0.15)', '#E67E22'
        else:
            bg, fg = 'rgba(231,76,60,0.15)', '#E74C3C'

        rows.append(html.Tr([
            html.Td(str(int(row['점검순서'])), style={'textAlign': 'center', 'width': '60px', 'color': '#888'}),
            html.Td(row['설비명'], style={'fontWeight': 'bold', 'color': '#fff'}),
            html.Td(f"{score:.1f}점", style={'fontWeight': 'bold', 'color': fg,
                                               'backgroundColor': bg, 'textAlign': 'center'}),
            html.Td(row['상태'], style={'color': fg, 'textAlign': 'center'}),
            html.Td(row['주요위험센서'], style={'fontSize': '0.82em', 'color': '#ccc'}),
            html.Td(row.get('위험센서 상세', ''), style={'fontSize': '0.78em', 'color': '#888'}),
            html.Td(f"{row['이상감지율(%)']:.1f}%", style={'textAlign': 'center', 'color': '#aaa'}),
            html.Td(row['권고사항'], style={'fontSize': '0.8em', 'color': '#aaa'}),
        ]))

    table = dbc.Table(
        [
            html.Thead(html.Tr([
                html.Th('점검순서'), html.Th('설비명'), html.Th('건강도'),
                html.Th('상태'), html.Th('주요위험센서'), html.Th('위험센서 상세'),
                html.Th('이상감지율(%)'), html.Th('권고사항'),
            ], style={'fontSize': '0.82em', 'color': '#888'})),
            html.Tbody(rows),
        ],
        bordered=False, hover=True, responsive=True, color='dark',
        size='sm', style={'fontSize': '0.83em'},
    )
    return status_msg, table


# ─────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────
if __name__ == '__main__':
    app.run(debug=True, port=8050)
