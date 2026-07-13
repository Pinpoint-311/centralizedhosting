import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Building2,
  Rocket,
  ScrollText,
  Settings,
  LogOut,
  Menu,
  X,
} from 'lucide-react'
import { clearToken } from '../lib/api'
import { Logo } from './Logo'

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/towns', label: 'Municipalities', icon: Building2 },
  { to: '/releases', label: 'Releases', icon: Rocket },
  { to: '/audit', label: 'Audit Log', icon: ScrollText },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Shell({ children, onLogout }: { children: React.ReactNode; onLogout: () => void }) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()

  function logout() {
    clearToken()
    onLogout()
    navigate('/')
  }

  const sidebar = (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-5 py-6">
        <Logo size={40} />
        <div>
          <div className="font-bold text-white leading-tight">Pinpoint 311</div>
          <div className="text-xs text-white/50">Hosting Control Plane</div>
        </div>
      </div>

      <nav className="flex-1 px-3 space-y-1">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={() => setOpen(false)}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-xl transition-colors text-sm ${
                isActive
                  ? 'bg-white/10 text-white font-medium'
                  : 'text-white/60 hover:bg-white/5 hover:text-white'
              }`
            }
          >
            <item.icon className="w-5 h-5" />
            {item.label}
          </NavLink>
        ))}
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
      <aside className="hidden lg:flex w-64 shrink-0 flex-col border-r border-white/10 bg-[rgba(30,27,75,0.6)] backdrop-blur-xl sticky top-0 h-screen">
        {sidebar}
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="lg:hidden fixed inset-0 z-40 flex">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <div className="relative w-64 bg-[rgba(30,27,75,0.97)] backdrop-blur-xl border-r border-white/10">
            {sidebar}
          </div>
        </div>
      )}

      <div className="flex-1 min-w-0">
        <header className="lg:hidden flex items-center justify-between px-4 py-3 border-b border-white/10 sticky top-0 z-30 bg-[rgba(30,27,75,0.8)] backdrop-blur-xl">
          <div className="flex items-center gap-2">
            <Logo size={32} />
            <span className="font-bold text-white">Pinpoint 311</span>
          </div>
          <button onClick={() => setOpen((o) => !o)} className="p-2 text-white/70">
            {open ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </header>

        <main className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">{children}</main>
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
