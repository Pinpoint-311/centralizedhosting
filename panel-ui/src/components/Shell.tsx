import { createContext, useContext, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { NavLink, useLocation, useNavigate, Outlet } from 'react-router-dom'
import {
  LayoutDashboard,
  Building2,
  BarChart3,
  Activity,
  ShieldCheck,
  Settings,
  LogOut,
  Menu,
  X,
} from 'lucide-react'
import { api, clearToken } from '../lib/api'
import { Logo } from './Logo'

// Five hubs + Settings. Each hub owns a set of routes (its tabs); the sidebar
// item is active whenever the current path belongs to the hub.
interface NavItem {
  to: string
  label: string
  icon: typeof LayoutDashboard
  owns: string[]
  exact?: boolean
  badge?: 'alerts'
}

const NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, owns: ['/'], exact: true },
  { to: '/towns', label: 'Municipalities', icon: Building2, owns: ['/towns', '/map', '/requests'] },
  { to: '/analytics', label: 'Insights', icon: BarChart3, owns: ['/analytics', '/cost'] },
  { to: '/sla', label: 'Operations', icon: Activity, owns: ['/sla', '/alerts', '/releases'], badge: 'alerts' },
  { to: '/compliance', label: 'Governance', icon: ShieldCheck, owns: ['/compliance', '/audit'] },
  { to: '/settings', label: 'Settings', icon: Settings, owns: ['/settings'] },
]

function isActive(pathname: string, item: NavItem): boolean {
  if (item.exact) return pathname === item.to
  return item.owns.some((p) => pathname === p || pathname.startsWith(p + '/'))
}

export function Shell({ children, onLogout }: { children: React.ReactNode; onLogout: () => void }) {
  const [open, setOpen] = useState(false)
  const [alertCount, setAlertCount] = useState(0)
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    api.alerts(true).then((a) => setAlertCount(a.length)).catch(() => setAlertCount(0))
  }, [])

  function logout() {
    clearToken()
    onLogout()
    navigate('/')
  }

  const sidebar = (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-5 py-6">
        <Logo size={38} />
        <div>
          <div className="font-semibold text-white leading-tight">Pinpoint 311</div>
          <div className="text-xs text-white/50">Hosting Control Plane</div>
        </div>
      </div>

      <nav aria-label="Primary" className="flex-1 px-3 space-y-1 overflow-y-auto">
        {NAV.map((item) => {
          const active = isActive(location.pathname, item)
          return (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={() => setOpen(false)}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-xl transition-colors text-sm ${
                active
                  ? 'bg-primary-500/20 text-white font-medium'
                  : 'text-white/60 hover:bg-white/5 hover:text-white'
              }`}
            >
              <item.icon className="w-5 h-5 shrink-0" />
              <span className="flex-1">{item.label}</span>
              {item.badge === 'alerts' && alertCount > 0 && (
                <span className="text-[11px] font-semibold bg-red-500/80 text-white rounded-full px-1.5 min-w-[1.25rem] text-center">
                  {alertCount}
                </span>
              )}
            </NavLink>
          )
        })}
      </nav>

      <div className="p-3 border-t border-white/10">
        <button
          onClick={logout}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-white/60 hover:bg-white/5 hover:text-white transition-colors"
        >
          <LogOut className="w-5 h-5" />
          Sign out
        </button>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen flex">
      {/* Desktop sidebar */}
      <aside className="hidden lg:flex w-64 shrink-0 flex-col glass-sidebar sticky top-0 h-screen">
        {sidebar}
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="lg:hidden fixed inset-0 z-40 flex" role="dialog" aria-modal="true" aria-label="Navigation menu">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <div className="relative w-64 glass-sidebar">{sidebar}</div>
        </div>
      )}

      <div className="flex-1 min-w-0">
        <header className="lg:hidden flex items-center justify-between px-4 py-3 border-b border-white/10 sticky top-0 z-30 bg-[rgba(30,27,75,0.85)] backdrop-blur-xl">
          <div className="flex items-center gap-2">
            <Logo size={32} />
            <span className="font-semibold text-white">Pinpoint 311</span>
          </div>
          <button
            onClick={() => setOpen((o) => !o)}
            className="p-2 text-white/70 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
            aria-label={open ? 'Close navigation menu' : 'Open navigation menu'}
            aria-expanded={open}
          >
            {open ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </header>

        <main id="main-content" role="main" className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
          {children}
        </main>
      </div>
    </div>
  )
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string
  subtitle?: string
  actions?: React.ReactNode
}) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
      <div>
        <h1 className="text-2xl font-bold text-white">{title}</h1>
        {subtitle && <p className="text-white/50 mt-1">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

// ---------------------------------------------------------------- Hub layout
export interface HubTab {
  to: string
  label: string
  subtitle?: string
}

// A page's action buttons portal into the hub's tab row (right side) so they
// align with the tabs instead of floating on a separate band.
const HubActionSlot = createContext<HTMLElement | null>(null)

/**
 * A hub groups related pages under one sidebar entry. It owns the page title +
 * subtitle and renders a pill tab bar to switch between its pages; the pages
 * themselves render only their content (and any page-specific action buttons,
 * which appear on the right of the tab row via PageToolbar).
 */
export function HubShell({ title, tabs }: { title: string; tabs: HubTab[] }) {
  const location = useLocation()
  const [slot, setSlot] = useState<HTMLElement | null>(null)
  const active =
    tabs.find((t) => location.pathname === t.to || location.pathname.startsWith(t.to + '/')) || tabs[0]

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">{title}</h1>
        {active?.subtitle && <p className="text-white/50 mt-1">{active.subtitle}</p>}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        {tabs.length > 1 ? (
          <div className="flex flex-wrap gap-1 p-1 rounded-xl bg-white/[0.04] border border-white/10 w-fit">
            {tabs.map((t) => {
              const isActive =
                location.pathname === t.to || location.pathname.startsWith(t.to + '/')
              return (
                <NavLink
                  key={t.to}
                  to={t.to}
                  className={`px-3.5 py-1.5 rounded-lg text-sm transition-colors ${
                    isActive
                      ? 'bg-primary-500/25 text-white font-medium'
                      : 'text-white/55 hover:text-white hover:bg-white/5'
                  }`}
                >
                  {t.label}
                </NavLink>
              )
            })}
          </div>
        ) : (
          <div />
        )}
        {/* Actions from the active page land here, aligned with the tabs. */}
        <div ref={setSlot} className="flex flex-wrap items-center gap-2" />
      </div>

      <HubActionSlot.Provider value={slot}>
        <Outlet />
      </HubActionSlot.Provider>
    </div>
  )
}

/** A hub page's own action buttons — rendered into the tab row's right side so
 * they align with the tabs (the hub owns the title). */
export function PageToolbar({ children }: { children: React.ReactNode }) {
  const slot = useContext(HubActionSlot)
  if (slot) return createPortal(children, slot)
  // Fallback (used outside a hub, or before the slot mounts): inline, right-aligned.
  return <div className="flex flex-wrap items-center justify-end gap-2 mb-6">{children}</div>
}
