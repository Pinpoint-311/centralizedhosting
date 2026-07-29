import { useEffect, useState } from 'react'
import { Building2, Landmark, Users, Wallet } from 'lucide-react'
import { api } from '../lib/api'
import type { KeyDefaults } from '../lib/types'
import { Button, Card, Modal, Spinner } from './ui'
import { useToast } from './Toast'

/**
 * Who supplies — and therefore pays for — each external service key.
 *
 * This is the fleet-wide default a new town inherits. Existing towns keep
 * whatever they already have: re-pointing forty towns' Maps billing is an event,
 * not a settings change, so it lives behind its own action. The drift count on
 * each row says how many towns currently differ, so a default that no longer
 * reflects reality is visible instead of quietly wrong.
 */
const OWNER_META: Record<string, { label: string; blurb: string; icon: typeof Users }> = {
  town: {
    label: 'Town pays',
    blurb: 'Each town brings its own key and is billed directly.',
    icon: Building2,
  },
  state_shared: {
    label: 'You pay — one shared key',
    blurb: 'One credential from your pool serves every town.',
    icon: Landmark,
  },
  state_per_town: {
    label: 'You pay — key per town',
    blurb: 'You supply a separate key per town, so spend and quotas stay attributable.',
    icon: Wallet,
  },
}

export function KeyPayerDefaults() {
  const toast = useToast()
  const [data, setData] = useState<KeyDefaults | null>(null)
  const [busy, setBusy] = useState('')
  const [applying, setApplying] = useState(false)

  async function load() {
    try {
      setData(await api.keyDefaults())
    } catch (e) {
      toast.push((e as Error).message, 'error')
    }
  }
  useEffect(() => { load() }, [])

  async function choose(serviceId: string, owner: string) {
    if (!data || data.defaults[serviceId] === owner) return
    setBusy(serviceId)
    const next = { ...data.defaults, [serviceId]: owner }
    try {
      await api.setKeyDefaults(next)
      toast.push('Default saved — it applies to towns you add from now on')
      await load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }

  async function applyToAll() {
    setApplying(false)
    try {
      const r = await api.applyKeyDefaults()
      toast.push(r.count
        ? `${r.count} town${r.count === 1 ? '' : 's'} moved to the default`
        : 'Every town already matches the default')
      await load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    }
  }

  if (!data) return <Card><Spinner /></Card>

  const drifting = Object.values(data.drift).reduce((a, b) => Math.max(a, b), 0)

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-1">
        <h3 className="font-semibold text-white flex items-center gap-2">
          <Wallet className="w-5 h-5" /> Who pays for each service
        </h3>
        {drifting > 0 && (
          <Button size="sm" variant="secondary" onClick={() => setApplying(true)}>
            Apply default to all towns
          </Button>
        )}
      </div>
      <p className="text-sm text-white/50 mb-4">
        The default a newly added town inherits. Changing it here does not move towns
        you already host — use “Apply to all” when you mean to re-point their billing.
      </p>

      <div className="space-y-3">
        {data.services.map((service) => {
          const current = data.defaults[service.id]
          const drift = data.drift[service.id] || 0
          return (
            <div key={service.id} className="p-3 rounded-xl border border-white/10 bg-white/[0.03]">
              <div className="flex items-center gap-2 flex-wrap mb-2">
                <span className="text-sm font-medium text-white">{service.label}</span>
                {drift > 0 && (
                  <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300">
                    {drift} of {data.town_count} differ
                  </span>
                )}
              </div>
              <p className="text-xs text-white/45 mb-2.5">{service.description}</p>

              <div
                role="radiogroup"
                aria-label={`Who pays for ${service.label}`}
                className="grid sm:grid-cols-3 gap-2"
              >
                {data.owners.map((owner) => {
                  const meta = OWNER_META[owner]
                  if (!meta) return null
                  const active = current === owner
                  const Icon = meta.icon
                  return (
                    <button
                      key={owner}
                      type="button"
                      role="radio"
                      aria-checked={active}
                      disabled={busy === service.id}
                      onClick={() => choose(service.id, owner)}
                      className={`text-left p-2.5 rounded-lg border transition-colors disabled:opacity-50
                        ${active
                          ? 'bg-sky-500/15 border-sky-400/50'
                          : 'bg-white/[0.02] border-white/10 hover:border-white/25'}`}
                    >
                      <span className="flex items-center gap-1.5 text-xs font-medium text-white">
                        <Icon className="w-3.5 h-3.5 shrink-0" />{meta.label}
                      </span>
                      <span className="block text-[11px] text-white/45 mt-1">{meta.blurb}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>

      {applying && (
        <Modal open title="Apply the default to every town?" onClose={() => setApplying(false)}>
          <p className="text-sm text-white/70 mb-2">
            This overwrites each town's own choice with the defaults above.
          </p>
          <p className="text-sm text-white/50 mb-5">
            Where a town moves from paying for its own key to using yours (or the other
            way round), that changes who is billed. Every town that changes is named in
            the audit log.
          </p>
          <div className="flex gap-2 justify-end">
            <Button variant="secondary" onClick={() => setApplying(false)}>Cancel</Button>
            <Button onClick={applyToAll}>Apply to all towns</Button>
          </div>
        </Modal>
      )}
    </Card>
  )
}
