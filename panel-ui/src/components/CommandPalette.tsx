import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Search,
  LayoutDashboard,
  Building2,
  Map as MapIcon,
  Rocket,
  ScrollText,
  Settings,
  DollarSign,
  Activity,
  BarChart3,
  ShieldCheck,
  BellRing,
  Inbox,
} from 'lucide-react'
import { api } from '../lib/api'
import type { Tenant } from '../lib/types'

interface Item {
  id: string
  label: string
  hint?: string
  icon: React.ReactNode
  action: () => void
}

/**
 * ⌘K / Ctrl-K command palette: jump to any page or municipality instantly.
 */
export function CommandPalette() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [active, setActive] = useState(0)

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((o) => !o)
      } else if (e.key === 'Escape') {
        setOpen(false)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (open) {
      setQuery('')
      setActive(0)
      api.listTenants().then(setTenants).catch(() => {})
    }
  }, [open])

  const go = (path: string) => {
    navigate(path)
    setOpen(false)
  }

  const pages: Item[] = [
    { id: 'p-overview', label: 'Overview', icon: <LayoutDashboard className="w-4 h-4" />, action: () => go('/') },
    { id: 'p-towns', label: 'Municipalities', icon: <Building2 className="w-4 h-4" />, action: () => go('/towns') },
    { id: 'p-map', label: 'State Map', icon: <MapIcon className="w-4 h-4" />, action: () => go('/map') },
    { id: 'p-analytics', label: '311 Analytics', icon: <BarChart3 className="w-4 h-4" />, action: () => go('/analytics') },
    { id: 'p-cost', label: 'Cost & Chargeback', icon: <DollarSign className="w-4 h-4" />, action: () => go('/cost') },
    { id: 'p-compliance', label: 'Compliance', icon: <ShieldCheck className="w-4 h-4" />, action: () => go('/compliance') },
    { id: 'p-sla', label: 'Uptime & SLA', icon: <Activity className="w-4 h-4" />, action: () => go('/sla') },
    { id: 'p-alerts', label: 'Alerts', icon: <BellRing className="w-4 h-4" />, action: () => go('/alerts') },
    { id: 'p-requests', label: 'Hosting Requests', icon: <Inbox className="w-4 h-4" />, action: () => go('/requests') },
    { id: 'p-releases', label: 'Releases', icon: <Rocket className="w-4 h-4" />, action: () => go('/releases') },
    { id: 'p-audit', label: 'Audit Log', icon: <ScrollText className="w-4 h-4" />, action: () => go('/audit') },
    { id: 'p-settings', label: 'Settings', icon: <Settings className="w-4 h-4" />, action: () => go('/settings') },
  ]

  const items = useMemo(() => {
    const q = query.toLowerCase().trim()
    const townItems: Item[] = tenants.map((t) => ({
      id: `t-${t.id}`,
      label: t.name,
      hint: t.slug,
      icon: <Building2 className="w-4 h-4 text-indigo-300" />,
      action: () => go(`/towns/${t.id}`),
    }))
    const all = [...pages, ...townItems]
    if (!q) return all.slice(0, 8)
    return all.filter((i) => i.label.toLowerCase().includes(q) || i.hint?.toLowerCase().includes(q)).slice(0, 12)
  }, [query, tenants])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[90] flex items-start justify-center pt-[15vh] bg-black/60 backdrop-blur-sm px-4" onClick={() => setOpen(false)}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="glass-card w-full max-w-lg !p-0 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-white/10">
          <Search className="w-5 h-5 text-white/40" />
          <input
            autoFocus
            className="flex-1 bg-transparent outline-none text-white placeholder:text-white/40"
            placeholder="Jump to a page or municipality…"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setActive(0) }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)) }
              else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
              else if (e.key === 'Enter') { e.preventDefault(); items[active]?.action() }
            }}
          />
          <kbd className="text-[10px] text-white/40 border border-white/15 rounded px-1.5 py-0.5">esc</kbd>
        </div>
        <ul className="max-h-80 overflow-y-auto py-2">
          {items.length === 0 && <li className="px-4 py-6 text-center text-white/40 text-sm">No matches</li>}
          {items.map((it, i) => (
            <li key={it.id}>
              <button
                onMouseEnter={() => setActive(i)}
                onClick={it.action}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-left ${i === active ? 'bg-white/10' : ''}`}
              >
                {it.icon}
                <span className="text-white text-sm flex-1">{it.label}</span>
                {it.hint && <code className="text-[11px] text-white/40">{it.hint}</code>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
