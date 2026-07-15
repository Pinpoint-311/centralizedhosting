import { useState } from 'react'
import { Building2, Landmark, Users, Lock, ChevronDown } from 'lucide-react'
import type { KeyCatalog } from '../lib/types'

// Kept for other consumers (labels/icons per backend owner mode).
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
    label: 'State provides',
    short: 'State',
    icon: Users,
    hint: 'One state credential, entered once, used by every town.',
  },
  state_per_town: {
    label: 'State provides',
    short: 'State',
    icon: Landmark,
    hint: 'State-owned but a distinct value per town — for billing, quota, and blast-radius isolation.',
  },
}

/**
 * "Who provides each API key?" — a simple two-way choice per service: the
 * State provides it, or the Town does. When the State provides it, an advanced
 * toggle chooses one shared credential (default) vs. a distinct value per town.
 *
 * The backend still stores three modes; this widget maps them:
 *   town → town · State + shared → state_shared · State + per-town → state_per_town
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
  const [showKeys, setShowKeys] = useState(false)

  return (
    <div className="space-y-3">
      {catalog.assignable.map((svc) => {
        const owner = assignments[svc.id] || svc.default_owner
        const isState = owner !== 'town'
        const perTown = owner === 'state_per_town'

        return (
          <div
            key={svc.id}
            className="p-4 rounded-xl bg-white/[0.03] border border-white/10"
          >
            <div className="flex flex-col sm:flex-row sm:items-start gap-3 sm:gap-4">
              <div className="flex-1 min-w-0">
                <div className="font-medium text-white">{svc.label}</div>
                <p className="text-sm text-white/50 mt-0.5">{svc.description}</p>
                {showKeys && (
                  <code className="inline-block text-[11px] text-white/40 bg-white/5 rounded px-1.5 py-0.5 mt-1.5">
                    {svc.keys.join(', ')}
                  </code>
                )}
              </div>

              {/* Binary: State provides / Town provides */}
              <div className="inline-flex rounded-xl bg-white/5 border border-white/10 p-1 shrink-0 self-start">
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onChange(svc.id, perTown ? 'state_per_town' : 'state_shared')}
                  className={`flex items-center gap-1.5 px-3.5 py-1.5 text-sm font-medium rounded-lg transition-all ${
                    isState
                      ? 'bg-gradient-to-r from-indigo-500 to-indigo-600 text-white shadow-lg shadow-indigo-500/20'
                      : 'text-white/60 hover:text-white'
                  } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  <Landmark className="w-3.5 h-3.5" /> State
                </button>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onChange(svc.id, 'town')}
                  className={`flex items-center gap-1.5 px-3.5 py-1.5 text-sm font-medium rounded-lg transition-all ${
                    !isState
                      ? 'bg-gradient-to-r from-slate-500 to-slate-600 text-white shadow-lg'
                      : 'text-white/60 hover:text-white'
                  } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  <Building2 className="w-3.5 h-3.5" /> Town
                </button>
              </div>
            </div>

            {/* Context + advanced options, only when the State provides it */}
            {isState ? (
              <div className="mt-3 pt-3 border-t border-white/5">
                <p className="text-xs text-indigo-200/70">{svc.state_hint}</p>
                <label
                  className={`inline-flex items-center gap-2 mt-2 text-sm ${
                    disabled ? 'opacity-50' : 'cursor-pointer'
                  } text-white/70`}
                >
                  <input
                    type="checkbox"
                    disabled={disabled}
                    checked={perTown}
                    onChange={(e) => onChange(svc.id, e.target.checked ? 'state_per_town' : 'state_shared')}
                    className="accent-indigo-500 w-4 h-4"
                  />
                  Give each town its own key
                  <span className="text-white/40">— separate billing &amp; quota per town</span>
                </label>
              </div>
            ) : (
              <p className="text-xs text-white/40 mt-2">
                The town enters this in its own instance — it never touches the panel.
              </p>
            )}
          </div>
        )
      })}

      <div className="flex items-center justify-between pt-1">
        <button
          type="button"
          onClick={() => setShowKeys((s) => !s)}
          className="inline-flex items-center gap-1 text-xs text-white/40 hover:text-white/70"
        >
          <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showKeys ? 'rotate-180' : ''}`} />
          {showKeys ? 'Hide' : 'Show'} technical key names
        </button>
      </div>

      {/* Infrastructure keys — always state-owned, quietly noted */}
      <div className="p-3 rounded-xl bg-white/[0.02] border border-white/10 border-dashed">
        <div className="flex items-center gap-2">
          <Lock className="w-4 h-4 text-white/40 shrink-0" />
          <span className="text-sm text-white/60">
            Database, encryption keys, backups, and the app secret are provisioned
            automatically and always state-managed — nothing to configure.
          </span>
        </div>
        {showKeys && (
          <div className="flex flex-wrap gap-1.5 mt-2 pl-6">
            {catalog.infrastructure.map((k) => (
              <code key={k} className="text-[11px] text-white/40 bg-white/5 border border-white/10 rounded px-1.5 py-0.5">{k}</code>
            ))}
            {catalog.infrastructure_prefixes.map((p) => (
              <code key={p} className="text-[11px] text-white/40 bg-white/5 border border-white/10 rounded px-1.5 py-0.5">{p}*</code>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
