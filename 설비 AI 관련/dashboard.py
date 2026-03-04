"""
dashboard.py - 다중 설비 이상예지 모니터링 대시보드

실행:
    streamlit run dashboard.py

지원 파일 형식:
    - CSV / TXT (세미콜론 구분, cp949 인코딩)
    - Excel (.xlsx)
"""

import os
import json
import datetime
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

from preprocess import (
    load_raw, clean_numeric, extract_equipment,
    categorize_sensors, get_sensor_display_name, get_categories_by_equipment
)
from analysis import (
    compute_rolling_stats, detect_anomalies, compute_health_score,
    get_top_risk_sensors, generate_korean_report, summarize_all_equipment,
    score_to_level, build_ppt_summary
)


# ─────────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────────
st.set_page_config(
    page_title='설비 이상예지 모니터링',
    page_icon='🏭',
    layout='wide',
    initial_sidebar_state='expanded',
)

# ─────────────────────────────────────────────
# 글로벌 CSS 스타일
# ─────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    /* 위험센서 카드 */
    .risk-card {
        background: #1E1E1E;
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 10px;
        border-left: 5px solid #E74C3C;
    }
    .risk-card.good { border-left-color: #2ECC71; }
    .risk-card.warn { border-left-color: #F1C40F; }
    .risk-card.alert { border-left-color: #E67E22; }
    .risk-card.danger { border-left-color: #E74C3C; }
    .risk-title {
        font-size: 1.0em;
        font-weight: bold;
        margin-bottom: 6px;
        color: #FFFFFF;
    }
    .risk-detail {
        font-size: 0.85em;
        color: #CCCCCC;
        line-height: 1.6;
    }
    .risk-range {
        display: inline-block;
        background: #2C3E50;
        border-radius: 4px;
        padding: 2px 8px;
        margin: 2px 0;
        font-size: 0.82em;
        color: #ECF0F1;
    }
    /* 건강도 레벨 배지 */
    .health-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: bold;
        font-size: 0.9em;
    }
    .health-good   { background: #1E8449; color: #FFFFFF; }
    .health-warn   { background: #7D6608; color: #FFFFFF; }
    .health-alert  { background: #784212; color: #FFFFFF; }
    .health-danger { background: #922B21; color: #FFFFFF; }
    /* expander 내부 텍스트 */
    .explain-box {
        font-size: 0.92em;
        line-height: 1.8;
        color: #DDDDDD;
    }
    .explain-box b { color: #FFFFFF; }
    .explain-box .highlight {
        background: #2C3E50;
        padding: 2px 6px;
        border-radius: 4px;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# 캐시: 데이터 로드 및 설비 추출
# ─────────────────────────────────────────────
@st.cache_data(show_spinner='📊 데이터 로드 및 설비 분리 중...')
def cached_load(file_bytes: bytes, file_ext: str) -> dict:
    """
    파일 바이트 + 확장자를 받아 설비별 DataFrame dict 반환
    (st.cache_data는 파일 객체를 직접 받지 못하므로 bytes로 전달)
    """
    import io
    source = io.BytesIO(file_bytes)
    idx_hdr, desc_hdr, df_raw = load_raw(source, file_ext)
    df_clean = clean_numeric(df_raw)
    equip_dict = extract_equipment(df_clean)
    # JSON 직렬화: 각 DataFrame을 ISO-형식 인덱스 문자열로 변환
    return {k: v.to_json(date_format='iso') for k, v in equip_dict.items()}


@st.cache_data(show_spinner='🔍 이상 탐지 분석 중...')
def cached_analysis(equip_json: str) -> dict:
    """
    DataFrame JSON 문자열 → 이상 탐지 + 건강도 점수 반환
    결과도 JSON 직렬화하여 캐시 저장
    """
    df = pd.read_json(equip_json)
    df.index = pd.to_datetime(df.index)

    anomaly_df   = detect_anomalies(df)
    health       = compute_health_score(df, anomaly_df)
    rolling      = compute_rolling_stats(df)

    return {
        'anomaly_json':   anomaly_df.to_json(date_format='iso'),
        'health_score':   health['score'],
        'sensor_scores':  health['sensor_scores'].to_json(),
        'anomaly_cnt':    health['sensor_anomaly_cnt'].to_json(),
        'anomaly_rate':   health['anomaly_rate'],
        'rolling_mean_10': rolling[10]['mean'].to_json(date_format='iso'),
        'rolling_mean_30': rolling[30]['mean'].to_json(date_format='iso'),
        'rolling_mean_60': rolling[60]['mean'].to_json(date_format='iso'),
    }


def restore_health_result(result: dict) -> dict:
    """cached_analysis 결과에서 health_result dict 복원"""
    return {
        'score':              result['health_score'],
        'sensor_scores':      pd.read_json(result['sensor_scores'], typ='series'),
        'sensor_anomaly_cnt': pd.read_json(result['anomaly_cnt'], typ='series').astype(int),
        'anomaly_rate':       result['anomaly_rate'],
    }


# ─────────────────────────────────────────────
# 플롯 함수들
# ─────────────────────────────────────────────
def render_gauge(score: float, equip_name: str) -> go.Figure:
    """건강도 게이지 차트"""
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
        title={'text': f'{equip_name}<br><span style="font-size:0.85em">설비 건강도</span>',
               'font': {'size': 15}},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1,
                     'tickcolor': '#555', 'tickfont': {'size': 11},
                     'tickvals': [0, 20, 40, 60, 80, 100]},
            'bar': {'color': bar_color, 'thickness': 0.3},
            'bgcolor': 'white',
            'steps': [
                {'range': [0,  40], 'color': '#FADBD8'},
                {'range': [40, 60], 'color': '#FDEBD0'},
                {'range': [60, 80], 'color': '#FEF9E7'},
                {'range': [80, 100],'color': '#EAFAF1'},
            ],
        },
        number={'suffix': '점', 'font': {'size': 32, 'color': bar_color}},
    ))

    # 호버 툴팁: 건강도 쉬운 설명
    hover_text = (
        "<b>건강도란?</b><br>"
        "─────────────────<br>"
        "설비가 얼마나 정상적으로 작동하는지<br>"
        "0~100점으로 나타낸 점수입니다.<br><br>"
        "<b>80점 이상</b>: 양호 (정상 운전)<br>"
        "<b>60~79점</b>: 주의 (일부 이상)<br>"
        "<b>40~59점</b>: 경고 (점검 필요)<br>"
        "<b>39점 이하</b>: 위험 (긴급 정비)"
    )

    fig.add_trace(go.Scatter(
        x=[0.5], y=[0.25],
        mode='markers',
        marker=dict(size=110, color='rgba(0,0,0,0)', line=dict(width=0)),
        hovertemplate=hover_text + '<extra></extra>',
        showlegend=False,
        name='',
    ))

    fig.update_layout(
        height=250,
        margin=dict(l=20, r=20, t=60, b=10),
        xaxis=dict(range=[0, 1], visible=False, fixedrange=True),
        yaxis=dict(range=[0, 1], visible=False, fixedrange=True),
    )
    return fig


def render_timeseries(df: pd.DataFrame,
                      anomaly_df: pd.DataFrame,
                      selected_cols: list,
                      rolling_mean_df: pd.DataFrame,
                      window: int) -> go.Figure:
    """시계열 차트 (원시 데이터 + 롤링 평균 + 이상 구간 음영)"""
    if not selected_cols:
        fig = go.Figure()
        fig.update_layout(title='센서를 선택해주세요', height=400)
        return fig

    colors = px.colors.qualitative.Plotly
    fig = go.Figure()

    # 이상 구간 배경 음영
    combined_anomaly = anomaly_df[selected_cols].any(axis=1)
    _add_anomaly_shading(fig, combined_anomaly)

    for i, col in enumerate(selected_cols):
        short = get_sensor_display_name(col)
        c = colors[i % len(colors)]

        # 원시 데이터 (반투명)
        fig.add_trace(go.Scatter(
            x=df.index, y=df[col],
            name=f'{short}',
            line=dict(color=c, width=1),
            opacity=0.35,
            showlegend=True,
            legendgroup=col,
            hoverinfo='skip',
        ))
        # 롤링 평균 (굵게)
        if col in rolling_mean_df.columns:
            fig.add_trace(go.Scatter(
                x=rolling_mean_df.index,
                y=rolling_mean_df[col],
                name=f'{short} ({window}분 평균)',
                line=dict(color=c, width=2.5),
                legendgroup=col,
                showlegend=True,
                hovertemplate=f'<b>{short}</b> ({window}분 평균)<br>값: %{{y:.2f}}<extra></extra>',
            ))

    fig.update_layout(
        xaxis_title='시간',
        yaxis_title='센서값',
        hovermode='x unified',
        height=450,
        legend=dict(
            orientation='h', yanchor='top', y=-0.25,
            xanchor='left', x=0,
            font=dict(size=11),
        ),
        margin=dict(l=50, r=20, t=40, b=140),
    )
    return fig


def _add_anomaly_shading(fig: go.Figure,
                          combined_anomaly: pd.Series) -> None:
    """이상 구간을 빨간 배경 vrect로 추가"""
    in_anom = False
    start_t = None
    for ts, val in combined_anomaly.items():
        if val and not in_anom:
            start_t = ts
            in_anom = True
        elif not val and in_anom:
            fig.add_vrect(
                x0=start_t, x1=ts,
                fillcolor='rgba(231, 76, 60, 0.15)',
                layer='below', line_width=0,
            )
            in_anom = False
    if in_anom and start_t is not None:
        fig.add_vrect(
            x0=start_t, x1=combined_anomaly.index[-1],
            fillcolor='rgba(231, 76, 60, 0.15)',
            layer='below', line_width=0,
        )


def render_top_risks(top_risks: list, total_rows: int) -> None:
    """위험 센서 TOP N — 정상범위와 실제값을 보여주는 카드 형태"""
    if not top_risks:
        st.info('이상이 탐지된 센서가 없습니다. 모든 센서가 정상 범위입니다.')
        return

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

        # 이상 비율 계산
        total = risk.get('total_rows', total_rows)
        anom_pct = (risk['anomaly_count'] / total * 100) if total > 0 else 0

        # 정상범위 정보
        range_html = ''
        if 'normal_min' in risk and 'normal_max' in risk:
            range_html = (
                f'<span class="risk-range">'
                f'정상 범위: {risk["normal_min"]} ~ {risk["normal_max"]}'
                f'</span><br>'
                f'<span class="risk-range">'
                f'평균: {risk.get("avg_value", "-")} | '
                f'최소: {risk.get("actual_min", "-")} | '
                f'최대: {risk.get("actual_max", "-")}'
                f'</span>'
            )

        st.markdown(
            f"""<div class="risk-card {css_class}">
            <div class="risk-title">
                {emoji} {i}위. {risk['display']}
                <span style="font-size:0.8em;color:#999;"> [{risk['category']}]</span>
            </div>
            <div class="risk-detail">
                건강도: <b style="color:{'#E74C3C' if score<60 else '#F1C40F' if score<80 else '#2ECC71'}">{score:.1f}점</b>
                &nbsp;|&nbsp; 이상 감지: <b>{risk['anomaly_count']}건</b> / {total}건
                (<b>{anom_pct:.1f}%</b>가 정상 범위를 벗어남)<br>
                {range_html}
            </div>
            </div>""",
            unsafe_allow_html=True,
        )


def health_color_style(val):
    """DataFrame 스타일용 건강도 색상 함수"""
    if isinstance(val, (int, float)):
        if val >= 95:
            return 'background-color:#A9DFBF;color:#145A32;font-weight:bold'
        elif val >= 90:
            return 'background-color:#ABEBC6;color:#1E8449;font-weight:bold'
        elif val >= 80:
            return 'background-color:#EAFAF1;color:#1E8449;font-weight:bold'
        elif val >= 60:
            return 'background-color:#FEF9E7;color:#7D6608;font-weight:bold'
        elif val >= 40:
            return 'background-color:#FDEBD0;color:#784212;font-weight:bold'
        else:
            return 'background-color:#FADBD8;color:#922B21;font-weight:bold'
    return ''


def render_easy_explanation() -> None:
    """건강도와 이상 감지 기준을 쉽게 설명하는 expander"""
    with st.expander('❓ 건강도와 이상 감지가 뭔가요? (클릭하면 쉬운 설명이 나옵니다)', expanded=False):
        st.markdown("""
<div class="explain-box">

<b>🏥 건강도 점수란?</b><br>
사람이 건강검진에서 종합점수를 받는 것처럼, <b>설비의 센서들을 검사해서 종합 점수를 매긴 것</b>입니다.<br>
<br>
- <b>100점에 가까울수록</b> → 센서 값이 안정적이고, 정상 범위 안에 있습니다<br>
- <b>0점에 가까울수록</b> → 센서 값이 자주 정상 범위를 벗어났습니다<br>
<br>
<table style="width:100%;border-collapse:collapse;margin:8px 0;">
<tr style="border-bottom:1px solid #444;">
  <td style="padding:6px;">🟢 <b>80~100점 (양호)</b></td>
  <td style="padding:6px;">정상 운전 중. 월 1회 정기 점검으로 충분합니다.</td>
</tr>
<tr style="border-bottom:1px solid #444;">
  <td style="padding:6px;">🟡 <b>60~79점 (주의)</b></td>
  <td style="padding:6px;">일부 센서에서 비정상 값이 감지되었습니다. 2주 내 점검을 권고합니다.</td>
</tr>
<tr style="border-bottom:1px solid #444;">
  <td style="padding:6px;">🟠 <b>40~59점 (경고)</b></td>
  <td style="padding:6px;">여러 센서에서 비정상입니다. 1주 내 점검이 필요합니다.</td>
</tr>
<tr>
  <td style="padding:6px;">🔴 <b>39점 이하 (위험)</b></td>
  <td style="padding:6px;">심각한 이상입니다. 즉시 가동 중단 후 긴급 정비가 필요합니다.</td>
</tr>
</table>
<br>

<b>🔍 이상 감지란?</b><br>
각 센서에는 <b>"보통 이 범위 안에서 값이 나온다"</b>라는 정상 범위가 있습니다.<br>
<br>
예를 들어, 어떤 온도 센서의 정상 범위가 <b class="highlight">800℃ ~ 1,200℃</b> 라면:<br>
- 값이 1,000℃ → ✅ 정상<br>
- 값이 <b style="color:#E74C3C">1,500℃</b> → ❌ <b>이상 (정상 범위를 크게 벗어남)</b><br>
- 값이 <b style="color:#E74C3C">500℃</b> → ❌ <b>이상 (정상 범위보다 너무 낮음)</b><br>
<br>
이렇게 정상 범위를 벗어난 횟수를 세는 것이 <b>"이상 감지 건수"</b>이고,<br>
전체 측정 중 몇 %가 벗어났는지가 <b>"이상 감지율"</b>입니다.<br>
<br>
<b>📏 정상 범위는 어떻게 정할까요?</b><br>
데이터 전체의 값을 크기순으로 나열한 뒤,<br>
<b>가운데 50% 범위(25%~75% 구간)</b>를 기준으로 위아래 여유를 준 범위입니다.<br>
즉, <b>대다수의 값이 몰려 있는 구간</b>을 정상으로 봅니다.<br>
이 범위를 크게 벗어나면 "비정상"으로 판단합니다.

</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# 메인 앱
# ─────────────────────────────────────────────
def main():
    st.title('🏭 설비 이상예지 모니터링 대시보드')
    st.markdown('---')

    # ─── 사이드바 ───────────────────────────
    with st.sidebar:
        st.header('⚙️ 설정')

        # 파일 업로드
        st.subheader('📂 데이터 파일')
        uploaded = st.file_uploader(
            '파일 선택 (CSV/TXT/XLSX)',
            type=['txt', 'csv', 'xlsx'],
            help='세미콜론(;) 구분 CSV(.txt/.csv) 또는 Excel(.xlsx) 파일을 선택하세요.',
        )

        if not uploaded:
            st.info(
                '📂 분석할 데이터 파일을 업로드해주세요.\n\n'
                '지원 형식: CSV / TXT (세미콜론 구분) · Excel (.xlsx)'
            )
            st.stop()

        file_bytes = uploaded.read()
        file_ext   = uploaded.name.rsplit('.', 1)[-1].lower()
        st.caption(f'📄 {uploaded.name}')

        # 데이터 로드
        try:
            equip_json_dict = cached_load(file_bytes, file_ext)
        except Exception as e:
            st.error(f'데이터 로드 실패: {e}')
            st.stop()

        if not equip_json_dict:
            st.warning('분석 가능한 설비 데이터가 없습니다.\n(모든 센서가 0값)')
            st.stop()

        st.markdown('---')

        # 설비 선택
        st.subheader('🏭 설비 선택')
        equip_names = list(equip_json_dict.keys())
        selected = st.selectbox(
            '분석할 설비',
            options=equip_names,
            help='활성 센서 데이터가 있는 설비만 표시됩니다.',
        )

        st.markdown('---')

        # 롤링 윈도우
        st.subheader('⏱ 이동 평균 기간')
        window = st.radio(
            '이동 평균',
            options=[10, 30, 60],
            format_func=lambda x: f'{x}분',
            horizontal=True,
            help='센서 값의 짧은 변동을 부드럽게 보여주는 기간입니다. 길수록 부드러운 추세를 볼 수 있습니다.',
        )

        st.markdown('---')

        # 표시 옵션
        st.subheader('📋 표시 옵션')
        show_report   = st.checkbox('한국어 분석 리포트', value=True)
        show_priority = st.checkbox('전체 설비 정비 우선순위', value=True)
        show_ppt      = st.checkbox('PPT 5줄 요약', value=False)

    # ─── 선택 설비 분석 ─────────────────────
    equip_json = equip_json_dict[selected]

    try:
        result = cached_analysis(equip_json)
    except Exception as e:
        st.error(f'분석 오류: {e}')
        st.stop()

    df          = pd.read_json(equip_json)
    df.index    = pd.to_datetime(df.index)
    anomaly_df  = pd.read_json(result['anomaly_json'])
    anomaly_df.index = pd.to_datetime(anomaly_df.index)
    health_result = restore_health_result(result)
    top_risks     = get_top_risk_sensors(health_result, n=5, df=df)

    # 롤링 평균 DataFrame (선택 윈도우)
    rolling_key   = f'rolling_mean_{window}'
    rolling_df    = pd.read_json(result[rolling_key])
    rolling_df.index = pd.to_datetime(rolling_df.index)

    # ─── 쉬운 설명 (건강도/이상감지란?) ──────
    render_easy_explanation()

    # ─── 상단: 건강도 게이지 + 위험 센서 ───
    col_gauge, col_risks = st.columns([1, 1])

    with col_gauge:
        st.plotly_chart(
            render_gauge(health_result['score'], selected),
            use_container_width=True,
        )
        level, desc = score_to_level(health_result['score'] or 0)
        level_colors = {'양호': 'success', '주의': 'warning',
                        '경고': 'warning',  '위험': 'error'}
        msg_fn = getattr(st, level_colors.get(level, 'info'))

        anomaly_pct = health_result['anomaly_rate'] * 100
        total_sensors = len(df.columns)
        msg_fn(
            f"**상태: {level}** — {desc}\n\n"
            f"센서 {total_sensors}개 분석 결과, "
            f"전체 측정값 중 **{anomaly_pct:.1f}%** 가 정상 범위를 벗어났습니다."
        )

    with col_risks:
        st.subheader(f'⚠️ 주의가 필요한 센서 TOP 5')
        st.caption(f'📌 {selected} 설비에서 정상 범위를 가장 많이 벗어난 센서 순서입니다.')
        render_top_risks(top_risks, len(df))

    st.markdown('---')

    # ─── 시계열 차트 ────────────────────────
    st.subheader('📈 센서 시계열 분석')

    categories = get_categories_by_equipment(df)
    cat_options = list(categories.keys())

    default_cats = cat_options[:min(2, len(cat_options))]
    selected_cats = st.multiselect(
        '센서 카테고리 선택',
        options=cat_options,
        default=default_cats,
        help='여러 카테고리를 선택할 수 있습니다. 최대 10개 센서가 표시됩니다.',
    )

    selected_cols = []
    for cat in selected_cats:
        selected_cols.extend(categories.get(cat, []))

    if len(selected_cols) > 10:
        st.caption(f'⚡ {len(selected_cols)}개 센서 중 건강도 하위 10개만 표시합니다.')
        scores = health_result['sensor_scores']
        subset = [c for c in selected_cols if c in scores.index]
        sorted_cols = scores.loc[subset].nsmallest(10).index.tolist()
        others = [c for c in selected_cols if c not in subset]
        selected_cols = sorted_cols + others[:max(0, 10 - len(sorted_cols))]
        selected_cols = selected_cols[:10]

    st.caption(
        f'**빨간 음영 구간** = 센서 값이 정상 범위를 벗어난 시간대  |  '
        f'**굵은 선** = {window}분 이동 평균 (추세)  |  '
        f'**흐린 선** = 실시간 원시 데이터'
    )
    fig_ts = render_timeseries(df, anomaly_df, selected_cols, rolling_df, window)
    st.plotly_chart(fig_ts, use_container_width=True)

    # ─── 한국어 분석 리포트 ─────────────────
    if show_report:
        with st.expander('📋 한국어 분석 리포트 (클릭하여 펼치기)', expanded=False):
            report_text = generate_korean_report(selected, health_result, df)
            st.text(report_text)

    # ─── 전체 설비 우선순위 테이블 ──────────
    if show_priority:
        st.markdown('---')
        st.subheader('🗂️ 전체 설비 — 어떤 설비부터 점검해야 할까?')
        st.caption(
            '아래 표는 건강도가 낮은 설비부터 높은 설비 순서로 정렬되어 있습니다. '
            '**1번이 가장 먼저 점검해야 할 설비**입니다.'
        )

        with st.spinner('전체 설비 분석 중...'):
            all_equip = {k: pd.read_json(v) for k, v in equip_json_dict.items()}
            for k in all_equip:
                all_equip[k].index = pd.to_datetime(all_equip[k].index)
            priority_df = summarize_all_equipment(all_equip)

        if not priority_df.empty:
            # 상태 요약 배너
            all_good = (priority_df['건강도'] >= 80).all()
            if all_good:
                st.success(
                    '✅ 현재 모든 설비가 양호 상태입니다. '
                    '아래 표는 상대적으로 건강도가 낮은 순서로 보여주므로, '
                    '1번 설비를 가장 먼저 점검하시면 됩니다.'
                )
            else:
                critical_cnt = int((priority_df['건강도'] < 60).sum())
                warn_cnt = int(((priority_df['건강도'] >= 60) & (priority_df['건강도'] < 80)).sum())
                msg_parts = []
                if critical_cnt:
                    msg_parts.append(f'🔴 즉시 점검 필요: {critical_cnt}개 설비')
                if warn_cnt:
                    msg_parts.append(f'🟡 주의 관찰: {warn_cnt}개 설비')
                st.warning(' | '.join(msg_parts))

            # 표 구성
            priority_df = priority_df.copy()
            priority_df.insert(0, '점검순서', range(1, len(priority_df) + 1))

            # 건강도 소수점 1자리로 표시
            priority_df['건강도'] = priority_df['건강도'].round(1)
            priority_df['이상감지율(%)'] = priority_df['이상감지율(%)'].round(1)

            # 건강도·이상감지 계산 방법 (쉬운 버전)
            with st.expander('📊 점수는 어떻게 계산되나요?'):
                st.markdown("""
**건강도 점수 (0~100점)**

각 센서의 값이 정상 범위 안에 있으면 100점, 범위를 벗어나면 감점됩니다.

- 센서마다 "정상 범위"가 있고, 이 범위를 벗어난 비율만큼 점수가 깎입니다
- **온도 센서**는 설비에 가장 중요하므로 점수에 **3배** 반영됩니다
- **전류 센서**는 **2.5배**, 전력/압력은 **2배** 반영됩니다
- 최근 1시간 동안 이상이 많으면 추가로 점수가 깎입니다 (최신 상태 중시)

**이상감지율 (%)**

전체 측정값 중에서 정상 범위를 벗어난 값의 비율입니다.
- 예: 1,000번 측정 중 12번 벗어남 → 이상감지율 1.2%

**정상 범위 기준**

데이터에서 가운데 50%에 해당하는 값들의 범위에 여유를 준 구간입니다.
대부분의 값이 이 안에 들어오고, 이 범위를 크게 벗어나면 이상으로 판단합니다.
""")

            styled = priority_df.style.map(
                health_color_style, subset=['건강도']
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)

            # ─── PPT 5줄 요약 ────────────────
            if show_ppt:
                st.markdown('---')
                st.subheader('📊 PPT 핵심 5줄 요약')
                ppt_lines = build_ppt_summary(priority_df)
                for line in ppt_lines:
                    st.markdown(f'> {line}')
        else:
            st.info('분석 가능한 설비 데이터가 없습니다.')

    # ─── 푸터 ───────────────────────────────
    st.markdown('---')
    st.caption(
        f'🕒 마지막 데이터: {df.index[-1].strftime("%Y-%m-%d %H:%M")}  |  '
        f'📊 센서 수: {len(df.columns)}개  |  '
        f'⏱ 분석 기간: {df.index[0].strftime("%H:%M")} ~ {df.index[-1].strftime("%H:%M")}'
    )


if __name__ == '__main__':
    main()
