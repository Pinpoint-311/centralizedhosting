import { useState } from 'react'
import { MotionConfig } from 'framer-motion'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { getToken } from './lib/api'
import { ToastProvider } from './components/Toast'
import { TokenGate } from './components/TokenGate'
import { Shell } from './components/Shell'
import { Dashboard } from './pages/Dashboard'
import { Towns } from './pages/Towns'
import { TownDetail } from './pages/TownDetail'
import { StateMap } from './pages/StateMap'
import { Releases } from './pages/Releases'
import { Audit } from './pages/Audit'
import { Settings } from './pages/Settings'

export function App() {
  const [authed, setAuthed] = useState(!!getToken())

  if (!authed) {
    return (
      <MotionConfig reducedMotion="user">
        <ToastProvider>
          <TokenGate onAuthed={() => setAuthed(true)} />
        </ToastProvider>
      </MotionConfig>
    )
  }

  return (
    <MotionConfig reducedMotion="user">
      <ToastProvider>
        <BrowserRouter>
          <a
            href="#main-content"
            className="sr-only focus:not-sr-only focus:absolute focus:z-[200] focus:top-3 focus:left-3 focus:px-4 focus:py-2 focus:rounded-lg focus:bg-indigo-600 focus:text-white"
          >
            Skip to main content
          </a>
          <Shell onLogout={() => setAuthed(false)}>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/towns" element={<Towns />} />
              <Route path="/towns/:id" element={<TownDetail />} />
              <Route path="/map" element={<StateMap />} />
              <Route path="/releases" element={<Releases />} />
              <Route path="/audit" element={<Audit />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </Shell>
        </BrowserRouter>
      </ToastProvider>
    </MotionConfig>
  )
}
