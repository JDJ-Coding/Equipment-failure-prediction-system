import React, { useEffect, useState } from 'react'
import axios from 'axios'
import {
  LineChart, Line, AreaChart, Area,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, PieChart, Pie, Cell,
} from 'recharts'

const C = {
  cyan:   '#00b5d8',
  green:  '#36d399',
  yellow: '#fbbd23',
  red:    '#f87272',
  purple: '#a78bfa',
  orange: '#fb923c',
  blue:   '#60a5fa',
  teal:   '#2dd4bf',
  pink:   '#f472b6',
}
const LINE_COLORS = [C.cyan, C.green, C.yellow, C.orange, C.purple, C.teal, C.pink, C.blue]

const TOOLTIP_STYLE = {
  contentStyle: { background: '#1a1f2e', border: '1px solid #2a3347', borderRadius: 6 },
  labelStyle: { color: '#9ca3af', fontSize: 11 },
  itemStyle: { color: '#e2e8f0', fontSize: 11 },
}

async function loadAll(equip = 'RHK-A') {
  const [sumRes, alertRes, tsRes, hmRes] = await Promise.all([
    axios.get('/api/summary'),
    axios.get('/api/alerts', { params: { limit: 200 } }),
    axios.get('/api/timeseries', { params: { equipment: equip, resample: '15min' } }),
    axios.get('/api/heatmap', { params: { equipment: equip, metric: '전류' } }),
  ])
  return {
    summary: sumRes.data,
    alerts: alertRes.data,
    ts: tsRes.data,
    heatmap: hmRes.data,
  }
}

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [equipment, setEquipment] = useState('RHK-A')
  const [equipStatus, setEquipStatus] = useState([])

  // 설비 현황 로드 (한 번만)
  useEffect(() => {
    axios.get('/api/equipment')
      .then(res => setEquipStatus(res.data || []))
      .catch(() => {})
  }, [])

  // 선택 설비 변경 시 데이터 재로드
  useEffect(() => {
    setLoading(true)
    setErr('')
    loadAll(equipment)
      .then(setData)
      .catch(() => setErr('데이터 없음 — Upload 탭에서 파일을 먼저 로드하세요'))
      .finally(() => setLoading(false))
  }, [equipment])

  const selectedEquip = equipStatus.find(e => e.id === equipment)
  const isInactive = selectedEquip?.status === '비가동'

  if (loading) return <LoadingScreen />
  if (err) return <ErrorScreen msg={err} />

  const { summary: s, alerts, ts, heatmap } = data
  const tsChart = buildLineData(ts)
  const seriesKeys = ts ? Object.keys(ts).filter(k => k !== 'timestamps') : []
  const alarmItems = alerts?.items || []
  const critCount = alarmItems.filter(a => a.severity === 'CRITICAL').length
  const warnCount = alarmItems.filter(a => a.severity === 'WARNING').length

  const aging = Object.entries(s.resistance_aging || {})
    .map(([col, v]) => ({ name: shortName(col), value: v }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 8)

  const zoneData = buildZoneData(heatmap)

  return (
    <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'repeat(12, 1fr)' }}>

      {/* ─── 설비 현황 개요 (4개 카드) ─── */}
      {equipStatus.length > 0 && (
        <>
          {equipStatus.map(eq => (
            <EquipCard
              key={eq.id}
              eq={eq}
              selected={equipment === eq.id}
              onClick={() => setEquipment(eq.id)}
            />
          ))}
        </>
      )}

      {/* ─── 선택 표시 바 ─── */}
      <div className="panel" style={{
        gridColumn: 'span 12', padding: '8px 16px',
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <span style={{ fontSize: 11, color: '#8b96a9', textTransform: 'uppercase', letterSpacing: 1 }}>
          분석 대상
        </span>
        <div style={{ display: 'flex', gap: 6 }}>
          {equipStatus.map(eq => {
            const active = equipment === eq.id
            const color = eq.status === '가동중' ? C.cyan : '#4b5563'
            return (
              <button key={eq.id} onClick={() => setEquipment(eq.id)} style={{
                padding: '5px 16px', borderRadius: 4, fontSize: 12, fontWeight: 600,
                border: `1px solid ${active ? color : '#2a3347'}`,
                background: active ? `${color}22` : 'transparent',
                color: active ? color : '#4b5563',
                cursor: eq.status === '가동중' ? 'pointer' : 'not-allowed',
                transition: 'all .15s',
                opacity: eq.status === '가동중' ? 1 : 0.5,
              }}>
                {eq.id}
                <span style={{ marginLeft: 4, fontSize: 10, color: eq.status === '가동중' ? C.green : '#4b5563' }}>
                  {eq.status === '가동중' ? '●' : '○'}
                </span>
              </button>
            )
          })}
        </div>
        <div style={{ marginLeft: 'auto', fontSize: 11, color: '#6b7280' }}>
          {selectedEquip?.label ?? equipment}
        </div>
      </div>

      {/* ─── 비가동 설비 선택 시 ─── */}
      {isInactive ? (
        <div className="panel" style={{ gridColumn: 'span 12', padding: '48px 0', textAlign: 'center' }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>🔴</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0', marginBottom: 8 }}>
            {selectedEquip?.label} — 비가동 중
          </div>
          <div style={{ fontSize: 13, color: '#6b7280' }}>
            활성 센서 {selectedEquip?.active_cols ?? 0}개 / 전체 {selectedEquip?.total_cols ?? 0}개
          </div>
          <div style={{ fontSize: 12, color: '#4b5563', marginTop: 8 }}>
            현재 이 설비에서 수집된 유효 데이터가 없습니다
          </div>
        </div>
      ) : (
        <>
          {/* ─── Row 1: KPI panels ─── */}
          <KpiPanel span={2}
            title="최고 온도"
            value={s.temperature?.max?.toFixed(0)} unit="°C"
            sub={`평균 ${s.temperature?.mean?.toFixed(0)}°C`}
            color={C.orange}
            spark={sparkFromTs(ts, seriesKeys[0])} sparkColor={C.orange}
          />
          <KpiPanel span={2}
            title="최저 활성 온도"
            value={s.temperature?.min?.toFixed(0)} unit="°C"
            sub="측정 최솟값" color={C.cyan}
            spark={sparkFromTs(ts, seriesKeys[1])} sparkColor={C.cyan}
          />
          <KpiPanel span={2}
            title="최대 전류"
            value={s.current?.max?.toFixed(1)} unit="A"
            sub={`평균 ${s.current?.mean?.toFixed(1)}A`}
            color={C.yellow} spark={null}
          />
          <DonutKpi span={2}
            title="SCR 최대 출력"
            value={s.scr_output?.max?.toFixed(1)} unit="%"
            pct={s.scr_output?.max ?? 0}
            color={s.scr_output?.max > 85 ? C.red : C.green}
            sub={`경고 ${s.scr_output?.warning_count ?? 0}존`}
          />
          <DonutKpi span={2}
            title="운전 중 모터"
            value={s.operation?.running} unit={`/ ${s.operation?.total}`}
            pct={((s.operation?.running ?? 0) / (s.operation?.total ?? 1)) * 100}
            color={C.teal}
            sub={`정지 ${s.operation?.stopped ?? 0}개`}
          />
          <AlertSummary span={2}
            critical={critCount} warning={warnCount} total={alerts?.total ?? 0}
          />

          {/* ─── Row 2: 온도 트렌드 + 알람 도넛 ─── */}
          <div className="panel" style={{ gridColumn: 'span 8' }}>
            <div className="panel-title">
              온도 트렌드 — <span style={{ color: C.cyan, fontWeight: 700 }}>{equipment}</span>
              <span style={{ marginLeft: 6, color: '#4b5563' }}>(15분 평균, 아날로그)</span>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={tsChart} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  {seriesKeys.map((k, i) => (
                    <linearGradient key={k} id={`g${i}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={LINE_COLORS[i % 8]} stopOpacity={0.3} />
                      <stop offset="95%" stopColor={LINE_COLORS[i % 8]} stopOpacity={0} />
                    </linearGradient>
                  ))}
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
                <XAxis dataKey="t" tick={{ fill: '#4b5563', fontSize: 10 }}
                  tickFormatter={v => v?.slice(11, 16)} />
                <YAxis tick={{ fill: '#4b5563', fontSize: 10 }} unit="°C" width={48} />
                <Tooltip {...TOOLTIP_STYLE} labelFormatter={v => `시각: ${v?.slice(11, 19)}`} />
                {seriesKeys.map((k, i) => (
                  <Area key={k} type="monotone" dataKey={shortName(k)}
                    stroke={LINE_COLORS[i % 8]} fill={`url(#g${i})`}
                    strokeWidth={1.5} dot={false} />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div className="panel" style={{ gridColumn: 'span 4' }}>
            <div className="panel-title">알람 심각도 분포</div>
            <AlarmDonut critical={critCount} warning={warnCount} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
              {[
                { label: 'CRITICAL', count: critCount, color: C.red },
                { label: 'WARNING', count: warnCount, color: C.yellow },
                { label: '정상', count: Math.max(0, 200 - critCount - warnCount), color: C.green },
              ].map(r => (
                <div key={r.label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: r.color }} />
                  <span style={{ flex: 1, fontSize: 12, color: '#9ca3af' }}>{r.label}</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: r.color }}>{r.count}</span>
                </div>
              ))}
            </div>
          </div>

          {/* ─── Row 3: 저항 노화 바 + 히트맵 + SCR 게이지 ─── */}
          <div className="panel" style={{ gridColumn: 'span 4' }}>
            <div className="panel-title">히터 저항 노화율 (기준 대비 %)</div>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={aging} layout="vertical"
                margin={{ top: 0, right: 32, bottom: 0, left: 90 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" horizontal={false} />
                <XAxis type="number" tick={{ fill: '#4b5563', fontSize: 10 }} unit="%" />
                <YAxis type="category" dataKey="name"
                  tick={{ fill: '#9ca3af', fontSize: 10 }} width={85} />
                <Tooltip
                  {...TOOLTIP_STYLE}
                  formatter={v => [`+${v.toFixed(1)}%`, '노화율']}
                />
                <Bar dataKey="value" radius={[0, 3, 3, 0]}>
                  {aging.map((e, i) => (
                    <Cell key={i} fill={e.value > 20 ? C.red : e.value > 10 ? C.yellow : C.green} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="panel" style={{ gridColumn: 'span 5' }}>
            <div className="panel-title">
              히터 존별 전류 히트맵 — <span style={{ color: C.cyan, fontWeight: 700 }}>{equipment}</span>
            </div>
            <ZoneHeatmap data={zoneData} />
          </div>

          <div className="panel" style={{ gridColumn: 'span 3' }}>
            <div className="panel-title">
              설비 부하 현황 — <span style={{ color: C.cyan, fontWeight: 700 }}>{equipment}</span>
            </div>
            <ScrGauges summary={s} />
          </div>

          {/* ─── Row 4: 알람 타임라인 ─── */}
          <div className="panel" style={{ gridColumn: 'span 12' }}>
            <div className="panel-title" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span>최근 알람 타임라인</span>
              <span style={{ color: C.red, fontWeight: 700, fontSize: 12 }}>CRITICAL {critCount}</span>
              <span style={{ color: C.yellow, fontWeight: 700, fontSize: 12 }}>WARNING {warnCount}</span>
            </div>
            <AlertTable items={alarmItems.slice(0, 15)} />
          </div>
        </>
      )}

    </div>
  )
}

/* ── 설비 현황 카드 ─────────────── */
function EquipCard({ eq, selected, onClick }) {
  const active = eq.status === '가동중'
  const statusColor = active ? C.green : '#4b5563'
  const borderColor = selected ? C.cyan : active ? '#1e3a2e' : '#1e2535'
  const bg = selected ? '#0d1f2e' : '#131720'

  return (
    <div
      onClick={onClick}
      className="panel"
      style={{
        gridColumn: 'span 3',
        cursor: 'pointer',
        border: `1px solid ${borderColor}`,
        background: bg,
        transition: 'all .2s',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: selected ? C.cyan : '#e2e8f0' }}>
          {eq.id}
        </span>
        <span style={{
          fontSize: 10, fontWeight: 600, padding: '2px 8px', borderRadius: 10,
          background: active ? '#0d2e1a' : '#1a1a1a',
          color: statusColor, border: `1px solid ${statusColor}44`,
        }}>
          {eq.status}
        </span>
      </div>
      <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 8 }}>{eq.label}</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 4 }}>
        {[
          { label: '전체', value: eq.total_cols, color: '#6b7280' },
          { label: '활성', value: eq.active_cols, color: active ? C.cyan : '#4b5563' },
          { label: '아날로그', value: eq.analog_cols, color: active ? C.green : '#4b5563' },
        ].map(k => (
          <div key={k.label} style={{ textAlign: 'center', background: '#0d1117', borderRadius: 4, padding: '4px 0' }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: k.color }}>{k.value}</div>
            <div style={{ fontSize: 9, color: '#4b5563', marginTop: 1 }}>{k.label}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── KPI 패널 ─────────────────── */
function KpiPanel({ span, title, value, unit, sub, color, spark, sparkColor }) {
  return (
    <div className="panel" style={{ gridColumn: `span ${span}` }}>
      <div className="panel-title">{title}</div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, marginBottom: 2 }}>
        <span style={{ fontSize: '2.1rem', fontWeight: 700, lineHeight: 1, color }}>
          {value ?? '—'}
        </span>
        <span style={{ fontSize: '0.85rem', color: '#6b7280', marginBottom: 3 }}>{unit}</span>
      </div>
      <div style={{ fontSize: 11, color: '#6b7280' }}>{sub}</div>
      {spark && spark.length > 0 && (
        <ResponsiveContainer width="100%" height={36}>
          <LineChart data={spark}>
            <Line type="monotone" dataKey="v" stroke={sparkColor} strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

/* ── 도넛 KPI ─────────────────── */
function DonutKpi({ span, title, value, unit, pct, color, sub }) {
  const safe = Math.min(Math.max(pct || 0, 0), 100)
  const circum = 2 * Math.PI * 28
  return (
    <div className="panel" style={{ gridColumn: `span ${span}` }}>
      <div className="panel-title">{title}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ position: 'relative', width: 68, height: 68, flexShrink: 0 }}>
          <svg width="68" height="68" style={{ transform: 'rotate(-90deg)' }}>
            <circle cx="34" cy="34" r="28" fill="none" stroke="#1e2535" strokeWidth="8" />
            <circle cx="34" cy="34" r="28" fill="none" stroke={color}
              strokeWidth="8"
              strokeDasharray={`${(safe / 100) * circum} ${circum}`}
              strokeLinecap="round" />
          </svg>
          <div style={{
            position: 'absolute', inset: 0, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            fontSize: 12, fontWeight: 700, color,
          }}>
            {safe.toFixed(0)}%
          </div>
        </div>
        <div>
          <div style={{ fontSize: '1.7rem', fontWeight: 700, color, lineHeight: 1 }}>{value}</div>
          <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>{unit}</div>
          <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>{sub}</div>
        </div>
      </div>
    </div>
  )
}

/* ── 알람 요약 ─────────────────── */
function AlertSummary({ span, critical, warning, total }) {
  return (
    <div className="panel" style={{ gridColumn: `span ${span}` }}>
      <div className="panel-title">이상 알람</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 4 }}>
        <div style={{ background: '#1a0e0e', borderRadius: 4, padding: '8px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, color: C.red, lineHeight: 1 }}>{critical}</div>
          <div style={{ fontSize: 10, color: '#6b7280', marginTop: 2 }}>CRITICAL</div>
        </div>
        <div style={{ background: '#231a07', borderRadius: 4, padding: '8px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, color: C.yellow, lineHeight: 1 }}>{warning}</div>
          <div style={{ fontSize: 10, color: '#6b7280', marginTop: 2 }}>WARNING</div>
        </div>
      </div>
      <div style={{ textAlign: 'center', fontSize: 11, color: '#4b5563', marginTop: 8 }}>
        총 {total}건 탐지
      </div>
    </div>
  )
}

/* ── 알람 도넛 ─────────────────── */
function AlarmDonut({ critical, warning }) {
  const safe = Math.max(0, 200 - critical - warning)
  const pieData = [
    { name: 'CRITICAL', value: critical, color: C.red },
    { name: 'WARNING', value: warning, color: C.yellow },
    { name: '정상', value: safe, color: '#1e2535' },
  ]
  return (
    <ResponsiveContainer width="100%" height={130}>
      <PieChart>
        <Pie data={pieData} cx="50%" cy="50%" innerRadius={36} outerRadius={56}
          dataKey="value" startAngle={90} endAngle={-270} paddingAngle={2}>
          {pieData.map((e, i) => <Cell key={i} fill={e.color} />)}
        </Pie>
        <Tooltip
          contentStyle={{ background: '#1a1f2e', border: '1px solid #2a3347', borderRadius: 6 }}
          itemStyle={{ color: '#e2e8f0', fontSize: 11 }}
        />
      </PieChart>
    </ResponsiveContainer>
  )
}

/* ── 존 히트맵 ─────────────────── */
function ZoneHeatmap({ data }) {
  if (!data || data.length === 0) {
    return <div style={{ color: '#4b5563', fontSize: 12, padding: 12 }}>데이터 없음</div>
  }
  const allVals = data.flatMap(r => r.vals.filter(v => v !== null && v > 0))
  const vmin = allVals.length ? Math.min(...allVals) : 0
  const vmax = allVals.length ? Math.max(...allVals) : 1

  const getColor = v => {
    if (!v || v === 0) return '#0d1117'
    const r = (v - vmin) / (vmax - vmin + 0.001)
    return `rgb(${Math.round(r * 200 + 20)},60,${Math.round((1 - r) * 180 + 20)})`
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: 9 }}>
        <thead>
          <tr>
            <th style={{ color: '#4b5563', padding: '2px 6px', textAlign: 'left', minWidth: 55 }}>Zone</th>
            {(data[0]?.hours || []).map((h, i) => (
              <th key={i} style={{ color: '#4b5563', padding: '1px 1px', fontWeight: 400 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.slice(0, 16).map((row, ri) => (
            <tr key={ri}>
              <td style={{ color: '#9ca3af', padding: '1px 6px', whiteSpace: 'nowrap' }}>{row.zone}</td>
              {row.vals.map((v, vi) => (
                <td key={vi} title={v ? `${v.toFixed(1)}A` : 'N/A'} style={{ padding: 1 }}>
                  <div style={{ width: 16, height: 12, borderRadius: 2, background: getColor(v) }} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 6, fontSize: 10, color: '#4b5563' }}>
        <span>{vmin.toFixed(0)}A</span>
        {[0, 0.25, 0.5, 0.75, 1].map(r => (
          <div key={r} style={{
            width: 14, height: 7, borderRadius: 2,
            background: `rgb(${Math.round(r * 200 + 20)},60,${Math.round((1 - r) * 180 + 20)})`
          }} />
        ))}
        <span>{vmax.toFixed(0)}A</span>
      </div>
    </div>
  )
}

/* ── SCR 게이지 ─────────────────── */
function ScrGauges({ summary: s }) {
  const items = [
    { label: 'SCR 최대 출력', value: s.scr_output?.max ?? 0, warn: 85, crit: 95 },
    { label: 'SCR 평균 출력', value: s.scr_output?.mean ?? 0, warn: 60, crit: 80 },
    { label: '평균 온도 부하', value: ((s.temperature?.mean ?? 0) / 800) * 100, warn: 80, crit: 95,
      display: `${(s.temperature?.mean ?? 0).toFixed(0)}°C` },
    { label: '전류 평균 부하', value: ((s.current?.mean ?? 0) / 130.5) * 100, warn: 75, crit: 90,
      display: `${(s.current?.mean ?? 0).toFixed(1)}A` },
  ]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18, marginTop: 4 }}>
      {items.map((item, i) => {
        const pct = Math.min(item.value, 100)
        const color = pct > item.crit ? C.red : pct > item.warn ? C.yellow : C.green
        return (
          <div key={i}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
              <span style={{ fontSize: 11, color: '#9ca3af' }}>{item.label}</span>
              <span style={{ fontSize: 11, fontWeight: 600, color }}>{item.display ?? `${pct.toFixed(1)}%`}</span>
            </div>
            <div style={{ height: 6, background: '#1e2535', borderRadius: 3 }}>
              <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

/* ── 알람 테이블 ─────────────────── */
function AlertTable({ items }) {
  if (!items || items.length === 0) {
    return (
      <div style={{ color: '#4b5563', textAlign: 'center', padding: '20px 0', fontSize: 12 }}>
        이상 알람 없음 — 정상 운전 중
      </div>
    )
  }
  return (
    <div style={{ overflowX: 'auto', maxHeight: 230, overflowY: 'auto' }}>
      <table className="data-table">
        <thead>
          <tr>
            <th>심각도</th><th>규칙</th><th>대상 컬럼</th>
            <th style={{ textAlign: 'right' }}>측정값</th>
            <th style={{ textAlign: 'right' }}>임계값</th>
            <th>시각</th>
          </tr>
        </thead>
        <tbody>
          {items.map((a, i) => (
            <tr key={i}>
              <td>
                <span className={`badge ${a.severity === 'CRITICAL' ? 'badge-red' : 'badge-yellow'}`}>
                  {a.severity}
                </span>
              </td>
              <td style={{ color: '#e2e8f0' }}>{a.rule}</td>
              <td style={{ color: '#9ca3af', maxWidth: 240, overflow: 'hidden',
                textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={a.column}>
                {shortName(a.column)}
              </td>
              <td style={{ textAlign: 'right', fontWeight: 600,
                color: a.severity === 'CRITICAL' ? C.red : C.yellow }}>{a.value}</td>
              <td style={{ textAlign: 'right', color: '#6b7280' }}>{a.threshold}</td>
              <td style={{ color: '#6b7280', whiteSpace: 'nowrap' }}>
                {(a.timestamp || '').slice(0, 19).replace('T', ' ')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ── 유틸 ─────────────────────── */
function shortName(col = '') {
  const m = col.match(/H(\d+[UBDLMR]*)/i)
  if (m) {
    const p = col.includes('#01_A') || col.includes('RHK#A') ? 'A'
      : col.includes('#01_B') || col.includes('RHK#B') ? 'B' : ''
    return `${p}-${m[0]}`
  }
  const clean = col.replace(/\(D\d+.*?\)|\[.*?\]/g, '').trim()
  const parts = clean.split(/[_\s]+/).filter(Boolean)
  return parts.slice(-3).join('-').slice(0, 20)
}

function buildLineData(ts) {
  if (!ts || !ts.timestamps) return []
  const keys = Object.keys(ts).filter(k => k !== 'timestamps')
  return ts.timestamps.map((t, i) => {
    const pt = { t }
    keys.forEach(k => { pt[shortName(k)] = ts[k]?.[i] ?? null })
    return pt
  })
}

function sparkFromTs(ts, key) {
  if (!ts || !key) return []
  return (ts[key] || []).map(v => ({ v }))
}

function buildZoneData(heatmap) {
  if (!heatmap || !heatmap.data) return []
  const shortHours = (heatmap.hours || []).map(h => h.slice(11, 13) + 'h')
  return heatmap.data.map(row => ({
    zone: row.zone,
    hours: shortHours,
    vals: row.values,
  }))
}

function LoadingScreen() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', height: '60vh', gap: 16 }}>
      <div style={{
        width: 40, height: 40, borderRadius: '50%',
        border: '3px solid #1e2535', borderTop: `3px solid ${C.cyan}`,
        animation: 'spin .8s linear infinite',
      }} />
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      <span style={{ color: '#4b5563', fontSize: 13 }}>데이터 로딩 중...</span>
    </div>
  )
}

function ErrorScreen({ msg }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh' }}>
      <div style={{
        background: '#1a0e0e', border: '1px solid #3d1515',
        borderRadius: 8, padding: '40px 60px', textAlign: 'center',
      }}>
        <div style={{ fontSize: 36, marginBottom: 16 }}>⚠️</div>
        <div style={{ color: C.red, fontSize: 14 }}>{msg}</div>
      </div>
    </div>
  )
}
