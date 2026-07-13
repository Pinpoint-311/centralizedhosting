import { useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { getToken } from './lib/api'
import { ToastProvider } from './components/Toast'
import { TokenGate } from './components/TokenGate'
import { Shell } from './components/Shell'
import { Dashboard } from './pages/Dashboard'
import { Towns } from './pages/Towns'
import { TownDetail } from './pages/TownDetail'
import { Releases } from './pages/Releases'
import { Audit } from './pages/Audit'
import { Settings } from './pages/Settings'

export function App() {
  const [authed, setAuthed] = useState(!!getToken())

  if (!authed) {
    return (
      <ToastProvider>
        <TokenGate onAuthed={() => setAuthed(true)} />
      </ToastProvider>
    )
  }

  return (
    <ToastProvider>
      <BrowserRouter>
        <Shell onLogout={() => setAuthed(false)}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/towns" element={<Towns />} />
            <Route path="/towns/:id" element={<TownDetail />} />
            <Route path="/releases" element={<Releases />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </Shell>
      </BrowserRouter>
    </ToastProvider>
  )
}
