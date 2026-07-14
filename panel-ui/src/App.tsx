import { useState } from 'react'
import { MotionConfig } from 'framer-motion'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { getToken } from './lib/api'
import { SessionProvider } from './lib/session'
import { ToastProvider } from './components/Toast'
import { TokenGate } from './components/TokenGate'
import { Shell } from './components/Shell'
import { CommandPalette } from './components/CommandPalette'
import { Dashboard } from './pages/Dashboard'
import { Towns } from './pages/Towns'
import { TownDetail } from './pages/TownDetail'
import { StateMap } from './pages/StateMap'
import { Cost } from './pages/Cost'
import { Sla } from './pages/Sla'
import { Analytics } from './pages/Analytics'
import { Compliance } from './pages/Compliance'
import { Alerts } from './pages/Alerts'
import { Requests } from './pages/Requests'
import { Releases } from './pages/Releases'
import { Audit } from './pages/Audit'
import { Settings } from './pages/Settings'
import { PublicRequest } from './pages/PublicRequest'

export function App() {
  const [authed, setAuthed] = useState(!!getToken())

  // The public self-service request form is reachable without the panel token.
  const isPublicRequest = window.location.pathname === '/request'
  if (isPublicRequest) {
    return (
      <MotionConfig reducedMotion="user">
        <PublicRequest />
      </MotionConfig>
    )
  }

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
        <SessionProvider>
          <BrowserRouter>
            <a
              href="#main-content"
              className="sr-only focus:not-sr-only focus:absolute focus:z-[200] focus:top-3 focus:left-3 focus:px-4 focus:py-2 focus:rounded-lg focus:bg-indigo-600 focus:text-white"
            >
              Skip to main content
            </a>
            <CommandPalette />
            <Shell onLogout={() => setAuthed(false)}>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/towns" element={<Towns />} />
                <Route path="/towns/:id" element={<TownDetail />} />
                <Route path="/map" element={<StateMap />} />
                <Route path="/cost" element={<Cost />} />
                <Route path="/sla" element={<Sla />} />
                <Route path="/analytics" element={<Analytics />} />
                <Route path="/compliance" element={<Compliance />} />
                <Route path="/alerts" element={<Alerts />} />
                <Route path="/requests" element={<Requests />} />
                <Route path="/releases" element={<Releases />} />
                <Route path="/audit" element={<Audit />} />
                <Route path="/settings" element={<Settings />} />
              </Routes>
            </Shell>
          </BrowserRouter>
        </SessionProvider>
      </ToastProvider>
    </MotionConfig>
  )
}
