import { useEffect, useState } from 'react'
import { KeyRound, Check } from 'lucide-react'
import { api } from '../lib/api'
import type { KeyCatalog, SecretOut } from '../lib/types'
import { Badge, Button, Card } from '../components/ui'
import { useToast } from '../components/Toast'

/**
 * One place to set up API keys: enter each credential the Host provides once
 * (services set to "Host" use it), and see at a glance who provides the rest.
 */
export function ApiKeysHub({
  catalog,
  creds,
  onChange,
}: {
  catalog: KeyCatalog
  creds: SecretOut[]
  onChange: () => void
}) {
  const toast = useToast()
  const [values, setValues] = useState<Record<string, string>>({})
  const [savingKey, setSavingKey] = useState('')
  const configured = new Set(creds.map((c) => c.key_name))

  async function save(key: string) {
    if (!values[key]) return
    setSavingKey(key)
    try {
      await api.putStateCredential(key, values[key])
      setValues((v) => ({ ...v, [key]: '' }))
      toast.push(`${key} saved (encrypted)`)
      onChange()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setSavingKey('')
    }
  }

  // Services the Host provides once, program-wide (need a credential here).
  const shared = catalog.assignable.filter((s) => s.default_owner === 'state_shared')
  const perTown = catalog.assignable.filter((s) => s.default_owner === 'state_per_town')
  const towned = catalog.assignable.filter((s) => s.default_owner === 'town')

  return (
    <Card>
      <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
        <KeyRound className="w-5 h-5" /> API keys &amp; credentials
      </h3>
      <p className="text-sm text-white/50 mb-5">
        Enter each credential the <b>Host</b> provides once — every town using it plugs in
        automatically, no per-town re-entry. Stored encrypted at rest; write-only. Towns provide
        their own keys inside their instances.
      </p>

      <div className="space-y-4">
        {shared.map((s) => {
          const allSet = s.keys.every((k) => configured.has(k))
          return (
            <div key={s.id} className="p-4 rounded-xl bg-white/[0.03] border border-white/10">
              <div className="flex items-center justify-between gap-2 mb-3">
                <div className="text-white font-medium">{s.label}</div>
                {allSet ? (
                  <Badge variant="success"><Check className="w-3 h-3" /> set</Badge>
                ) : (
                  <Badge variant="warning">needs a value</Badge>
                )}
              </div>
              <div className="space-y-2">
                {s.keys.map((key) => (
                  <div key={key} className="flex flex-col sm:flex-row sm:items-center gap-2">
                    <code className="text-[11px] text-white/45 sm:w-56 shrink-0">{key}</code>
                    <div className="flex-1 flex gap-2">
                      <input
                        type="password"
                        className="glass-input"
                        placeholder={configured.has(key) ? '•••••••• (set — enter to replace)' : 'Enter value'}
                        value={values[key] || ''}
                        onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
                      />
                      <Button size="sm" onClick={() => save(key)} isLoading={savingKey === key} disabled={!values[key]}>
                        Save
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>

      {(perTown.length > 0 || towned.length > 0) && (
        <div className="mt-5 pt-4 border-t border-white/10 space-y-2 text-sm">
          {perTown.length > 0 && (
            <p className="text-white/50">
              <span className="text-indigo-200">Host, per town:</span>{' '}
              {perTown.map((s) => s.label).join(', ')} — a distinct value is entered on each town's
              <b> API keys</b> tab (metered/billed per town).
            </p>
          )}
          {towned.length > 0 && (
            <p className="text-white/50">
              <span className="text-white/70">Towns provide:</span>{' '}
              {towned.map((s) => s.label).join(', ')} — entered inside each town's own instance.
            </p>
          )}
          <p className="text-white/35 text-xs">Defaults; change who provides any service on a town's API keys tab.</p>
        </div>
      )}
    </Card>
  )
}

// ------------------------------------------------ Announcements / status page
import { Megaphone, Trash2, Plus } from 'lucide-react'
import type { Announcement2 } from '../lib/types'
import { Input, Select } from '../components/ui'

export function Announcements() {
  const toast = useToast()
  const [items, setItems] = useState<Announcement2[]>([])
  const [title, setTitle] = useState('')
  const [severity, setSeverity] = useState('info')
  const [busy, setBusy] = useState(false)

  async function load() {
    setItems(await api.listAnnouncements())
  }
  useEffect(() => {
    load().catch(() => {})
  }, [])

  async function create() {
    if (!title.trim()) return
    setBusy(true)
    try {
      await api.createAnnouncement({ title: title.trim(), severity })
      setTitle('')
      toast.push('Announcement posted to the public status page')
      await load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }
  async function remove(id: string) {
    await api.deleteAnnouncement(id)
    await load()
  }

  return (
    <Card>
      <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
        <Megaphone className="w-5 h-5" /> Status announcements
      </h3>
      <p className="text-sm text-white/50 mb-4">
        Posted to the public status page at <code className="text-white/70">/status</code> — maintenance windows and incidents.
      </p>
      <div className="flex flex-col sm:flex-row gap-2 mb-4">
        <Input aria-label="Announcement text" placeholder="e.g. Planned maintenance Saturday 2–4am ET" value={title} onChange={(e) => setTitle(e.target.value)} />
        <div className="w-44 shrink-0">
          <Select aria-label="Announcement severity" value={severity} onChange={(e) => setSeverity(e.target.value)} options={[
            { value: 'info', label: 'Info' },
            { value: 'maintenance', label: 'Maintenance' },
            { value: 'incident', label: 'Incident' },
          ]} />
        </div>
        <Button onClick={create} isLoading={busy} leftIcon={<Plus className="w-4 h-4" />}>Post</Button>
      </div>
      <div className="space-y-1.5">
        {items.length === 0 && <p className="text-white/40 text-sm">No announcements.</p>}
        {items.map((a) => (
          <div key={a.id} className="flex items-center gap-2 py-1.5 border-b border-white/5">
            <Badge variant={a.severity === 'incident' ? 'danger' : a.severity === 'maintenance' ? 'warning' : 'info'}>{a.severity}</Badge>
            <span className="text-white text-sm flex-1">{a.title}</span>
            <button onClick={() => remove(a.id)} className="text-white/40 hover:text-red-300" aria-label="Delete announcement"><Trash2 className="w-4 h-4" /></button>
          </div>
        ))}
      </div>
    </Card>
  )
}
