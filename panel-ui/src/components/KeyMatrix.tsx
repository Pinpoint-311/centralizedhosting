import { Building2, Landmark, Users, Lock } from 'lucide-react'
import type { KeyCatalog } from '../lib/types'

export const OWNER_META: Record<
  string,
  { label: string; short: string; icon: typeof Landmark; hint: string }
> = {
  town: {
    label: 'Town provides',
    short: 'Town',
    icon: Building2,
    hint: 'The town enters this in its own instance — it never touches the panel.',
  },
  state_shared: {
    label: 'State · shared',
    short: 'Shared',
    icon: Users,
    hint: 'One state credential, entered once, plugged into every town set to shared.',
  },
  state_per_town: {
    label: 'State · per-town',
    short: 'Per-town',
    icon: Landmark,
    hint: 'State-owned but a distinct value per town — for billing, quota, and blast-radius isolation.',
  },
}

/**
 * The "who provides which API key" matrix, three ways per service:
 * town-owned, a shared state credential, or a state-owned per-town value.
 * Infrastructure keys are always state-owned (shown locked).
 */
export function KeyMatrix({
  catalog,
  assignments,
  onChange,
  disabled,
}: {
  catalog: KeyCatalog
  assignments: Record<string, string>
  onChange: (serviceId: string, owner: string) => void
  disabled?: boolean
}) {
  const owners = catalog.owners.length ? catalog.owners : ['town', 'state_shared', 'state_per_town']

  return (
    <div className="space-y-3">
      {catalog.assignable.map((svc) => {
        const owner = assignments[svc.id] || svc.default_owner
        return (
          <div
            key={svc.id}
            className="flex flex-col lg:flex-row lg:items-center gap-3 lg:gap-4 p-4 rounded-xl bg-white/[0.03] border border-white/10"
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium text-white">{svc.label}</span>
                <code className="text-[11px] text-white/40 bg-white/5 rounded px-1.5 py-0.5">
                  {svc.keys.join(', ')}
                </code>
              </div>
              <p className="text-sm text-white/50 mt-0.5">{svc.description}</p>
              {owner !== 'town' && <p className="text-xs text-indigo-300/70 mt-1">{svc.state_hint}</p>}
            </div>

            <div className="inline-flex rounded-xl bg-white/5 border border-white/10 p-1 shrink-0">
              {owners.map((o) => {
                const meta = OWNER_META[o]
                if (!meta) return null
                const Icon = meta.icon
                const active = owner === o
                return (
                  <button
                    key={o}
                    type="button"
                    disabled={disabled}
                    title={meta.hint}
                    onClick={() => onChange(svc.id, o)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg transition-all ${
                      active
                        ? o === 'town'
                          ? 'bg-gradient-to-r from-slate-500 to-slate-600 text-white shadow-lg'
                          : 'bg-gradient-to-r from-indigo-500 to-indigo-600 text-white shadow-lg shadow-indigo-500/20'
                        : 'text-white/60 hover:text-white'
                    } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    <Icon className="w-3.5 h-3.5" /> {meta.short}
                  </button>
                )
              })}
            </div>
          </div>
        )
      })}

      {/* Infrastructure keys — always state-owned, shown locked */}
      <div className="p-4 rounded-xl bg-white/[0.02] border border-white/10 border-dashed">
        <div className="flex items-center gap-2 mb-2">
          <Lock className="w-4 h-4 text-white/40" />
          <span className="text-sm font-medium text-white/70">
            Infrastructure — always managed by the state
          </span>
        </div>
        <p className="text-xs text-white/40 mb-3">
          Provisioned automatically and never editable by the town: database credentials,
          encryption keys, backups, and the app secret key.
        </p>
        <div className="flex flex-wrap gap-1.5">
          {catalog.infrastructure.map((k) => (
            <code
              key={k}
              className="text-[11px] text-white/50 bg-white/5 border border-white/10 rounded px-1.5 py-0.5"
            >
              {k}
            </code>
          ))}
          {catalog.infrastructure_prefixes.map((p) => (
            <code
              key={p}
              className="text-[11px] text-white/50 bg-white/5 border border-white/10 rounded px-1.5 py-0.5"
            >
              {p}*
            </code>
          ))}
        </div>
      </div>
    </div>
  )
}
