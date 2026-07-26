import { createContext, useContext, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { NavLink, useLocation, useNavigate, Outlet } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
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
  ChevronDown,
  Palette,
  Terminal,
  Landmark,
  Users,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { api, clearToken } from '../lib/api'
import { Logo } from './Logo'
import { getPlatformName, getTagline, getLogoUrl } from '../lib/config'

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
]

// The hosting-provider admin console, surfaced as a dropdown in the main nav.
// Groups mirror the Pinpoint 311 app's admin console (Departments and Service
// Categories omitted — those are municipality-fleet concerns).
interface SetupGroup {
  label: string
  items: { to: string; label: string; icon: LucideIcon }[]
}

const SETUP_GROUPS: SetupGroup[] = [
  {
    label: 'Branding & Setup',
    items: [
      { to: '/setup/branding', label: 'Branding', icon: Palette },
      { to: '/setup/integration', label: 'Setup & Integration', icon: Terminal },
    ],
  },
  {
    label: 'Organization',
    items: [
      { to: '/setup/organization', label: 'Organization', icon: Landmark },
      { to: '/setup/users', label: 'Users', icon: Users },
    ],
  },
  {
    label: 'System & Compliance',
    items: [
      { to: '/setup/system', label: 'System Settings', icon: Settings },
      { to: '/setup/health', label: 'System Health', icon: BarChart3 },
    ],
  },
]

function isActive(pathname: string, item: NavItem): boolean {
  if (item.exact) return pathname === item.to
  return item.owns.some((p) => pathname === p || pathname.startsWith(p + '/'))
}

// Expandable "Setup" entry — the admin console as a dropdown in the main nav.
// Auto-opens when on a /setup route; collapses otherwise.
function SetupNav({ onNavigate }: { onNavigate: () => void }) {
  const location = useLocation()
  const onSetup = location.pathname.startsWith('/setup') || location.pathname === '/settings'
  const [open, setOpen] = useState(onSetup)
  useEffect(() => {
    if (onSetup) setOpen(true)
  }, [onSetup])

  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-colors ${
          onSetup ? 'bg-primary-500/20 text-white font-medium' : 'text-white/60 hover:bg-white/5 hover:text-white'
        }`}
      >
        <Settings className="w-5 h-5 shrink-0" />
        <span className="flex-1 text-left">Setup</span>
        <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
          <ChevronDown className="w-4 h-4 opacity-60" />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
            className="overflow-hidden"
          >
            <div className="pt-1 pb-1 space-y-2.5">
              {SETUP_GROUPS.map((g) => (
                <div key={g.label}>
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-white/30 px-3 mb-1">
                    {g.label}
                  </div>
                  <div className="space-y-0.5">
                    {g.items.map((it) => (
                      <NavLink
                        key={it.to}
                        to={it.to}
                        onClick={onNavigate}
                        className={({ isActive }) =>
                          `flex items-center gap-3 pl-6 pr-3 py-2 rounded-lg text-sm transition-colors ${
                            isActive
                              ? 'bg-primary-500/20 text-white'
                              : 'text-white/50 hover:bg-white/5 hover:text-white'
                          }`
                        }
                      >
                        <it.icon className="w-4 h-4 shrink-0" />
                        <span>{it.label}</span>
                      </NavLink>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
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
    api.logout().catch(() => {}) // clear the SSO session cookie (if any)
    clearToken()
    onLogout()
    navigate('/')
  }

  const sidebar = (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-5 py-6">
        {getLogoUrl() ? (
          <img src={getLogoUrl()} alt="" className="w-[38px] h-[38px] rounded-xl object-cover" />
        ) : (
          <Logo size={38} />
        )}
        <div>
          <div className="font-semibold text-white leading-tight">{getPlatformName()}</div>
          <div className="text-xs text-white/50">{getTagline()}</div>
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
        <SetupNav onNavigate={() => setOpen(false)} />
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
            {getLogoUrl() ? <img src={getLogoUrl()} alt="" className="w-8 h-8 rounded-lg object-cover" /> : <Logo size={32} />}
            <span className="font-semibold text-white">{getPlatformName()}</span>
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
  /** Optional section label — when set, tabs render in labeled groups (the way
   *  an admin console groups its nav), e.g. "Branding & Setup". */
  group?: string
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

  const pill = (t: HubTab) => {
    const isActive = location.pathname === t.to || location.pathname.startsWith(t.to + '/')
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
  }

  const groups = tabs.some((t) => t.group)
    ? [...new Set(tabs.map((t) => t.group))]
    : null

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">{title}</h1>
        {active?.subtitle && <p className="text-white/50 mt-1">{active.subtitle}</p>}
      </div>

      <div className="flex flex-wrap items-start justify-between gap-3 mb-6">
        {groups ? (
          <div className="flex flex-wrap gap-x-6 gap-y-3">
            {groups.map((g) => (
              <div key={g}>
                <div className="text-[10px] font-semibold uppercase tracking-wider text-white/30 mb-1.5 px-1">{g}</div>
                <div className="flex flex-wrap gap-1 p-1 rounded-xl bg-white/[0.04] border border-white/10 w-fit">
                  {tabs.filter((t) => t.group === g).map(pill)}
                </div>
              </div>
            ))}
          </div>
        ) : tabs.length > 1 ? (
          <div className="flex flex-wrap gap-1 p-1 rounded-xl bg-white/[0.04] border border-white/10 w-fit">
            {tabs.map(pill)}
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
