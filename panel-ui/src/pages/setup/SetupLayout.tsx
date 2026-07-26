import React, { useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ChevronDown,
  Palette,
  Terminal,
  Landmark,
  Users as UsersIcon,
  Settings as SettingsIcon,
  BarChart3,
  Home,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { getPlatformName } from '../../lib/config'

// The hosting-provider admin console — ported from the Pinpoint 311 app's
// AdminConsole so the look and behavior are the same: a grouped accordion
// sidebar on the left, max-w-4xl content on the right. Departments and Service
// Categories (municipality-fleet concerns) are intentionally omitted.
interface NavGroup {
  title: string
  icon: LucideIcon
  items: { to: string; label: string; icon: LucideIcon }[]
}

const GROUPS: NavGroup[] = [
  {
    title: 'Branding & Setup',
    icon: Palette,
    items: [
      { to: '/setup/branding', label: 'Branding', icon: Palette },
      { to: '/setup/integration', label: 'Setup & Integration', icon: Terminal },
    ],
  },
  {
    title: 'Organization',
    icon: UsersIcon,
    items: [
      { to: '/setup/organization', label: 'Organization', icon: Landmark },
      { to: '/setup/users', label: 'Users', icon: UsersIcon },
    ],
  },
  {
    title: 'System & Compliance',
    icon: SettingsIcon,
    items: [
      { to: '/setup/system', label: 'System Settings', icon: SettingsIcon },
      { to: '/setup/health', label: 'System Health', icon: BarChart3 },
    ],
  },
]

// ---- Grouped accordion nav (ported verbatim from the app) -------------------

function SidebarGroup({
  title,
  icon: Icon,
  isActive,
  defaultOpen = false,
  children,
}: {
  title: string
  icon: LucideIcon
  isActive: boolean
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen)

  // Auto-open when active
  useEffect(() => {
    if (isActive && !isOpen) setIsOpen(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isActive])

  return (
    <div className="rounded-xl overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-colors ${
          isActive ? 'bg-white/10 text-white' : 'text-white/60 hover:bg-white/5 hover:text-white'
        }`}
      >
        <Icon className="w-5 h-5" />
        <span className="font-medium flex-1 text-left">{title}</span>
        <motion.div animate={{ rotate: isOpen ? 180 : 0 }} transition={{ duration: 0.2 }}>
          <ChevronDown className="w-4 h-4 opacity-50" />
        </motion.div>
      </button>
      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
            className="overflow-hidden"
          >
            <div className="pl-4 py-1 space-y-1">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function SidebarItem({
  icon: Icon,
  label,
  isActive,
  onClick,
}: {
  icon: LucideIcon
  label: string
  isActive: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors text-sm ${
        isActive ? 'bg-primary-500/20 text-white' : 'text-white/50 hover:bg-white/5 hover:text-white'
      }`}
    >
      <Icon className="w-4 h-4" />
      <span className="font-medium">{label}</span>
    </button>
  )
}

export function SetupLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const path = location.pathname
  const itemActive = (to: string) => path === to || path.startsWith(to + '/')
  const groupActive = (g: NavGroup) => g.items.some((i) => itemActive(i.to))

  return (
    <div className="flex flex-col lg:flex-row gap-6 lg:gap-8">
      {/* Admin-console sidebar */}
      <aside className="lg:w-64 shrink-0" aria-label="Admin console navigation">
        <div className="glass-card !p-3 lg:sticky lg:top-8">
          <div className="flex items-center gap-3 px-2 py-2 mb-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-400 to-orange-600 flex items-center justify-center shrink-0">
              <Home className="w-5 h-5 text-white" aria-hidden="true" />
            </div>
            <div data-no-translate>
              <h2 className="font-semibold text-white leading-tight">Admin Console</h2>
              <p className="text-xs text-white/50 truncate">{getPlatformName()}</p>
            </div>
          </div>
          <nav className="space-y-2" aria-label="Admin configuration">
            {GROUPS.map((g) => (
              <SidebarGroup
                key={g.title}
                title={g.title}
                icon={g.icon}
                isActive={groupActive(g)}
                defaultOpen={groupActive(g)}
              >
                {g.items.map((it) => (
                  <SidebarItem
                    key={it.to}
                    icon={it.icon}
                    label={it.label}
                    isActive={itemActive(it.to)}
                    onClick={() => navigate(it.to)}
                  />
                ))}
              </SidebarGroup>
            ))}
          </nav>
        </div>
      </aside>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="max-w-4xl mx-auto">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
