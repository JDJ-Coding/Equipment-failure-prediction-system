import React, { useState, useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'

const C = { cyan: '#00b5d8', green: '#36d399', red: '#f87272' }

export default function UploadPage() {
  const [status, setStatus] = useState('idle')
  const [result, setResult] = useState(null)
  const [errorMsg, setErrorMsg] = useState('')
  const navigate = useNavigate()

  const process = async (file) => {
    setStatus('uploading')
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await axios.post('/api/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setResult(res.data)
      setStatus('done')
    } catch (err) {
      setErrorMsg(err.response?.data?.detail || err.message)
      setStatus('error')
    }
  }

  const loadSample = async () => {
    setStatus('uploading')
    try {
      const res = await axios.post('/api/load-sample')
      setResult(res.data)
      setStatus('done')
    } catch (err) {
      setErrorMsg(err.response?.data?.detail || err.message)
      setStatus('error')
    }
  }

  const onDrop = useCallback(f => { if (f[0]) process(f[0]) }, [])
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop, accept: { 'text/*': ['.csv', '.txt'] }, multiple: false,
  })

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: '#e2e8f0' }}>CSV 파일 업로드</h2>

      <div {...getRootProps()} style={{
        border: `2px dashed ${isDragActive ? C.cyan : '#1e2535'}`,
        borderRadius: 8, padding: '60px 24px', textAlign: 'center',
        cursor: 'pointer', transition: 'all .2s',
        background: isDragActive ? '#0d1f2e' : '#131720',
      }}>
        <input {...getInputProps()} />
        <div style={{ fontSize: 40, marginBottom: 12 }}>📁</div>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#e2e8f0', marginBottom: 6 }}>
          {isDragActive ? '여기에 파일을 놓으세요' : 'CSV 파일 드래그 & 드롭'}
        </div>
        <div style={{ fontSize: 12, color: '#4b5563' }}>소성로 히터 데이터 (CP949 인코딩)</div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1, height: 1, background: '#1e2535' }} />
        <span style={{ fontSize: 12, color: '#4b5563' }}>또는</span>
        <div style={{ flex: 1, height: 1, background: '#1e2535' }} />
      </div>

      <button onClick={loadSample} disabled={status === 'uploading'} style={{
        padding: 12, borderRadius: 6, fontSize: 13, fontWeight: 600,
        border: '1px solid #1e2535', background: '#131720',
        color: '#9ca3af', cursor: 'pointer',
      }}>
        🗂️ 서버 샘플 파일 로드
      </button>

      {status === 'uploading' && (
        <div style={{ textAlign: 'center', padding: '32px 0' }}>
          <div style={{
            display: 'inline-block', width: 36, height: 36,
            border: '3px solid #1e2535', borderTop: `3px solid ${C.cyan}`,
            borderRadius: '50%', animation: 'spin .8s linear infinite',
          }} />
          <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
          <div style={{ color: '#6b7280', fontSize: 12, marginTop: 12 }}>분석 파이프라인 실행 중...</div>
        </div>
      )}

      {status === 'error' && (
        <div className="panel" style={{ border: '1px solid #3d1515', background: '#1a0e0e' }}>
          <span style={{ color: C.red }}>❌ {errorMsg}</span>
        </div>
      )}

      {status === 'done' && result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="panel">
            <div className="panel-title">✅ 분석 완료</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginTop: 8 }}>
              {[
                { label: '데이터 행', value: result.meta?.rows?.toLocaleString(), color: C.cyan },
                { label: '활성 컬럼', value: result.meta?.active_columns?.toLocaleString(), color: C.green },
                { label: '탐지 알람', value: result.alert_count, color: C.red },
                { label: '수집 기간', value: '24h', color: '#9ca3af' },
              ].map(k => (
                <div key={k.label} style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '1.8rem', fontWeight: 700, color: k.color, lineHeight: 1 }}>{k.value}</div>
                  <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>{k.label}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-title">데이터 범위</div>
            <div style={{ fontSize: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {[
                ['시작', result.meta?.start],
                ['종료', result.meta?.end],
                ['장비', result.meta?.equipment?.join(', ')],
              ].map(([k, v]) => (
                <div key={k} style={{ display: 'flex', gap: 8 }}>
                  <span style={{ color: '#6b7280', width: 48 }}>{k}</span>
                  <span style={{ color: '#e2e8f0' }}>{v}</span>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => navigate('/')} style={{
              flex: 1, padding: 12, borderRadius: 6, fontSize: 13, fontWeight: 600,
              border: 'none', background: C.cyan, color: '#000', cursor: 'pointer',
            }}>📊 대시보드 보기</button>
            <button onClick={() => navigate('/alerts')} style={{
              flex: 1, padding: 12, borderRadius: 6, fontSize: 13, fontWeight: 600,
              border: 'none', background: C.red, color: '#fff', cursor: 'pointer',
            }}>⚠️ 알람 {result.alert_count}건 확인</button>
          </div>
        </div>
      )}
    </div>
  )
}
