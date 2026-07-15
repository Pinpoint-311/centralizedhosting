import { useState } from 'react'
import { MotionConfig } from 'framer-motion'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { getToken } from './lib/api'
import { SessionProvider } from './lib/session'
import { ToastProvider } from './components/Toast'
import { TokenGate } from './components/TokenGate'
import { Shell, HubShell, type HubTab } from './components/Shell'
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

const MUNI_TABS: HubTab[] = [
  { to: '/towns', label: 'Directory', subtitle: 'Every municipality you host.' },
  { to: '/map', label: 'State Map', subtitle: 'Onboarded municipalities and their boundaries — public geography from OpenStreetMap, never resident data.' },
  { to: '/requests', label: 'Requests', subtitle: 'Municipalities that have asked to be onboarded.' },
]
const INSIGHTS_TABS: HubTab[] = [
  { to: '/analytics', label: '311 Analytics', subtitle: 'Resident-request trends, aggregated by region — never by individual municipality.' },
  { to: '/cost', label: 'Cost & Chargeback', subtitle: 'What each municipality costs to host, split state-borne vs town-borne.' },
]
const OPS_TABS: HubTab[] = [
  { to: '/sla', label: 'Uptime & SLA', subtitle: 'Availability and incidents across the fleet.' },
  { to: '/alerts', label: 'Alerts', subtitle: 'Open monitoring alerts across hosted municipalities.' },
  { to: '/releases', label: 'Releases', subtitle: 'Published versions and fleet rollout.' },
]
const GOV_TABS: HubTab[] = [
  { to: '/compliance', label: 'Compliance', subtitle: 'Security and policy posture across the fleet — infrastructure metadata, not resident data.' },
  { to: '/audit', label: 'Audit Log', subtitle: 'Tamper-evident record of every state action.' },
]

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
                <Route path="/towns/:id" element={<TownDetail />} />

                <Route element={<HubShell title="Municipalities" tabs={MUNI_TABS} />}>
                  <Route path="/towns" element={<Towns />} />
                  <Route path="/map" element={<StateMap />} />
                  <Route path="/requests" element={<Requests />} />
                </Route>

                <Route element={<HubShell title="Insights" tabs={INSIGHTS_TABS} />}>
                  <Route path="/analytics" element={<Analytics />} />
                  <Route path="/cost" element={<Cost />} />
                </Route>

                <Route element={<HubShell title="Operations" tabs={OPS_TABS} />}>
                  <Route path="/sla" element={<Sla />} />
                  <Route path="/alerts" element={<Alerts />} />
                  <Route path="/releases" element={<Releases />} />
                </Route>

                <Route element={<HubShell title="Governance" tabs={GOV_TABS} />}>
                  <Route path="/compliance" element={<Compliance />} />
                  <Route path="/audit" element={<Audit />} />
                </Route>

                <Route path="/settings" element={<Settings />} />
              </Routes>
            </Shell>
          </BrowserRouter>
        </SessionProvider>
      </ToastProvider>
    </MotionConfig>
  )
}
