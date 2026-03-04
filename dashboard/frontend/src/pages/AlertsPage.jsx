import React, { useEffect, useState } from 'react'
import axios from 'axios'

const C = { red: '#f87272', yellow: '#fbbd23', green: '#36d399', cyan: '#00b5d8' }

export default function AlertsPage() {
  const [alerts, setAlerts] = useState([])
  const [total, setTotal] = useState(0)
  const [filter, setFilter] = useState('ALL')
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  const load = async (sev) => {
    setLoading(true)
    try {
      const params = sev !== 'ALL' ? { severity: sev, limit: 500 } : { limit: 500 }
      const res = await axios.get('/api/alerts', { params })
      setAlerts(res.data.items || [])
      setTotal(res.data.total || 0)
    } catch {
      setErr('데이터 없음 — Upload 탭에서 파일을 먼저 로드하세요')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(filter) }, [filter])

  const crit = alerts.filter(a => a.severity === 'CRITICAL').length
  const warn = alerts.filter(a => a.severity === 'WARNING').length

  if (loading) return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}>
      <div style={{ width: 36, height: 36, border: `3px solid #1e2535`, borderTop: `3px solid ${C.cyan}`,
        borderRadius: '50%', animation: 'spin .8s linear infinite' }} />
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  )
  if (err) return (
    <div style={{ textAlign: 'center', padding: 60, color: C.red }}>{err}</div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: '#e2e8f0' }}>
          이상 알람 & 고장예지
        </h2>
        <div style={{ display: 'flex', gap: 4 }}>
          {['ALL', 'CRITICAL', 'WARNING'].map(s => {
            const active = filter === s
            const color = s === 'CRITICAL' ? C.red : s === 'WARNING' ? C.yellow : C.cyan
            return (
              <button key={s} onClick={() => setFilter(s)} style={{
                padding: '5px 14px', borderRadius: 4, fontSize: 12, fontWeight: 600,
                border: `1px solid ${active ? color : '#1e2535'}`,
                background: active ? `${color}22` : '#131720',
                color: active ? color : '#6b7280',
                cursor: 'pointer', transition: 'all .15s',
              }}>{s}</button>
            )
          })}
        </div>
      </div>

      {/* KPI */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
        {[
          { label: '전체 알람', value: total, color: '#e2e8f0' },
          { label: 'CRITICAL', value: crit, color: C.red },
          { label: 'WARNING', value: warn, color: C.yellow },
          { label: '탐지 룰 수', value: 7, color: C.cyan },
        ].map(k => (
          <div key={k.label} className="panel" style={{ textAlign: 'center', padding: '16px 12px' }}>
            <div style={{ fontSize: '2.4rem', fontWeight: 700, color: k.color, lineHeight: 1 }}>
              {k.value}
            </div>
            <div style={{ fontSize: 11, color: '#6b7280', marginTop: 6 }}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* 룰 가이드 */}
      <div className="panel">
        <div className="panel-title">탐지 룰 기준</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
          {RULES.map((r, i) => (
            <div key={i} style={{ display: 'flex', gap: 10, padding: '6px 0',
              borderBottom: '1px solid #1e2535' }}>
              <span className={`badge ${r.sev === 'CRITICAL' ? 'badge-red' : 'badge-yellow'}`}>
                {r.sev}
              </span>
              <div>
                <div style={{ fontSize: 12, color: '#e2e8f0', fontWeight: 500 }}>{r.name}</div>
                <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>{r.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 알람 테이블 */}
      <div className="panel">
        <div className="panel-title">
          알람 타임라인 — {alerts.length}건
        </div>
        {alerts.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '32px 0', color: '#4b5563' }}>
            이상 알람 없음
          </div>
        ) : (
          <div style={{ maxHeight: 500, overflowY: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>심각도</th><th>규칙</th><th>컬럼</th>
                  <th style={{ textAlign: 'right' }}>측정값</th>
                  <th style={{ textAlign: 'right' }}>임계값</th>
                  <th>시각</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((a, i) => (
                  <tr key={i}>
                    <td>
                      <span className={`badge ${a.severity === 'CRITICAL' ? 'badge-red' : 'badge-yellow'}`}>
                        {a.severity}
                      </span>
                    </td>
                    <td style={{ color: '#e2e8f0' }}>{a.rule}</td>
                    <td style={{ color: '#9ca3af', maxWidth: 260, overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={a.column}>
                      {a.column?.split('_').slice(-2).join('_')}
                    </td>
                    <td style={{ textAlign: 'right', fontWeight: 600,
                      color: a.severity === 'CRITICAL' ? C.red : C.yellow }}>
                      {a.value}
                    </td>
                    <td style={{ textAlign: 'right', color: '#6b7280' }}>{a.threshold}</td>
                    <td style={{ color: '#6b7280', whiteSpace: 'nowrap', fontSize: 11 }}>
                      {(a.timestamp || '').slice(0, 19).replace('T', ' ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

const RULES = [
  { name: '히터 단선 의심', desc: '전류 < 정상 평균×0.3', sev: 'CRITICAL' },
  { name: 'SCR 출력 초과', desc: '출력 > 95%', sev: 'CRITICAL' },
  { name: '모터/팬 정지 감지', desc: '동작상태 1→0 전환', sev: 'CRITICAL' },
  { name: '절연불량 의심', desc: '전류 > 정상 평균×1.3', sev: 'WARNING' },
  { name: '히터 저항 증가', desc: '저항 > 기준값×1.1 (노화)', sev: 'WARNING' },
  { name: 'SCR 출력 한계 접근', desc: '출력 85~95% — 교체 검토', sev: 'WARNING' },
  { name: '온도 급변 감지', desc: '변화율 > ±10°C/분', sev: 'WARNING' },
]
