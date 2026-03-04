import React, { useState } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import AlertsPage from './pages/AlertsPage'
import UploadPage from './pages/UploadPage'

const NAV = [
  { to: '/',       label: 'Dashboard' },
  { to: '/alerts', label: 'Alerts' },
  { to: '/upload', label: 'Upload' },
]

export default function App() {
  return (
    <div style={{ display:'flex', flexDirection:'column', minHeight:'100vh' }}>
      {/* 헤더 - Grafana 스타일 */}
      <header style={{
        background:'#111827', borderBottom:'1px solid #1e2535',
        padding:'0 16px', height:48, display:'flex', alignItems:'center', gap:24,
        flexShrink:0,
      }}>
        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
          <span style={{ color:'#f97316', fontSize:18 }}>🔥</span>
          <span style={{ fontWeight:700, color:'#e2e8f0', fontSize:14 }}>소성로 히터 고장예지</span>
        </div>
        <nav style={{ display:'flex', gap:2 }}>
          {NAV.map(({ to, label }) => (
            <NavLink key={to} to={to} end={to === '/'}
              style={({ isActive }) => ({
                padding:'6px 14px', borderRadius:4, fontSize:13, fontWeight:500,
                textDecoration:'none', transition:'all .15s',
                color: isActive ? '#fff' : '#9ca3af',
                background: isActive ? '#1f2937' : 'transparent',
              })}
            >{label}</NavLink>
          ))}
        </nav>
        <div style={{ marginLeft:'auto', display:'flex', alignItems:'center', gap:8 }}>
          <span style={{ fontSize:11, color:'#4b5563' }}>Last 24h</span>
          <div style={{ width:8, height:8, borderRadius:'50%', background:'#36d399' }} />
          <span style={{ fontSize:11, color:'#36d399' }}>LIVE</span>
        </div>
      </header>

      <main style={{ flex:1, padding:'12px', overflowY:'auto' }}>
        <Routes>
          <Route path="/"       element={<Dashboard />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/upload" element={<UploadPage />} />
        </Routes>
      </main>
    </div>
  )
}
