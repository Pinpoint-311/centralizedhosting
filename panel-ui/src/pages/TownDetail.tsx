import { useEffect, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Building2,
  Globe,
  KeyRound,
  ListChecks,
  ShieldAlert,
  Rocket,
  Pause,
  Play,
  Power,
  PowerOff,
  Trash2,
  Server,
  Check,
  Copy,
  Save,
} from 'lucide-react'
import { api } from '../lib/api'
import type { KeyCatalog, ProvisionJob, SecretOut, Tenant } from '../lib/types'
import {
  Badge,
  Button,
  Card,
  Input,
  Modal,
  Spinner,
  StatusBadge,
  Textarea,
  timeAgo,
} from '../components/ui'
import { KeyMatrix } from '../components/KeyMatrix'
import { useToast } from '../components/Toast'

import { getBaseDomain } from '../lib/config'
type TabId = 'overview' | 'domain' | 'keys' | 'provisioning' | 'breakglass'

export function TownDetail() {
  const BASE_DOMAIN = getBaseDomain()
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const toast = useToast()
  const [tenant, setTenant] = useState<Tenant | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<TabId>('overview')
  const [busy, setBusy] = useState('')

  async function load() {
    try {
      setTenant(await api.getTenant(id))
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [id])

  async function act(label: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(label)
    try {
      await fn()
      toast.push(ok)
      await load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }

  if (loading) return <Spinner />
  if (!tenant) return null

  const host = tenant.custom_domain || `${tenant.subdomain}.${BASE_DOMAIN}`
  const tabs: { id: TabId; label: string; icon: React.ReactNode }[] = [
    { id: 'overview', label: 'Overview', icon: <Server className="w-4 h-4" /> },
    { id: 'domain', label: 'Domain & contact', icon: <Globe className="w-4 h-4" /> },
    { id: 'keys', label: 'API keys', icon: <KeyRound className="w-4 h-4" /> },
    { id: 'provisioning', label: 'Provisioning', icon: <ListChecks className="w-4 h-4" /> },
    { id: 'breakglass', label: 'Break-glass', icon: <ShieldAlert className="w-4 h-4" /> },
  ]

  return (
    <div>
      <Link to="/towns" className="inline-flex items-center gap-1.5 text-sm text-white/50 hover:text-white mb-4">
        <ArrowLeft className="w-4 h-4" /> All municipalities
      </Link>

      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 mb-6">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-2xl bg-primary-500/20 text-primary-300 flex items-center justify-center">
            <Building2 className="w-7 h-7" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-white">{tenant.name}</h1>
              <StatusBadge status={tenant.status} />
            </div>
            <a href={`https://${host}`} target="_blank" className="text-white/50 hover:text-indigo-300 text-sm flex items-center gap-1.5">
              <Globe className="w-3.5 h-3.5" /> {host}
            </a>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {!['decommissioned', 'offline'].includes(tenant.status) && (
            <Button
              onClick={() =>
                act('provision', () => api.provision(tenant.id), 'Provisioning run complete')
              }
              isLoading={busy === 'provision'}
              leftIcon={<Rocket className="w-4 h-4" />}
            >
              {tenant.status === 'active' ? 'Re-provision' : 'Provision'}
            </Button>
          )}
          {tenant.status === 'active' && (
            <Button variant="secondary" onClick={() => act('suspend', () => api.suspend(tenant.id), 'Suspended (read-only)')} isLoading={busy === 'suspend'} leftIcon={<Pause className="w-4 h-4" />}>
              Suspend
            </Button>
          )}
          {tenant.status === 'suspended' && (
            <Button variant="secondary" onClick={() => act('resume', () => api.resume(tenant.id), 'Resumed')} isLoading={busy === 'resume'} leftIcon={<Play className="w-4 h-4" />}>
              Resume
            </Button>
          )}
          {['active', 'suspended'].includes(tenant.status) && (
            <Button
              variant="secondary"
              onClick={() => act('offline', () => api.takeOffline(tenant.id), 'Taken offline — all data retained')}
              isLoading={busy === 'offline'}
              leftIcon={<PowerOff className="w-4 h-4" />}
              title="Stop the instance but keep all data, PII, and configuration. Reversible."
            >
              Take offline
            </Button>
          )}
          {tenant.status === 'offline' && (
            <Button
              onClick={() => act('online', () => api.bringOnline(tenant.id), 'Back online')}
              isLoading={busy === 'online'}
              leftIcon={<Power className="w-4 h-4" />}
            >
              Bring online
            </Button>
          )}
        </div>
      </div>

      {tenant.status === 'offline' && (
        <div className="mb-6 flex items-start gap-3 p-4 rounded-xl bg-slate-500/10 border border-slate-400/30">
          <PowerOff className="w-5 h-5 text-slate-300 shrink-0 mt-0.5" />
          <p className="text-sm text-white/70">
            This instance is <b>offline</b>. It's not reachable and consumes no compute, but its
            database, PII, uploads, encryption key, and configuration are fully retained. Use{' '}
            <b>Bring online</b> to restore it exactly as it was.
          </p>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 mb-6 overflow-x-auto border-b border-white/10">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 px-4 py-3 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors ${
              tab === t.id
                ? 'border-indigo-400 text-white'
                : 'border-transparent text-white/50 hover:text-white'
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && <Overview tenant={tenant} />}
      {tab === 'domain' && <DomainContact tenant={tenant} onSaved={load} />}
      {tab === 'keys' && <KeysTab tenant={tenant} onChanged={load} />}
      {tab === 'provisioning' && <Provisioning tenant={tenant} />}
      {tab === 'breakglass' && <BreakGlass tenant={tenant} />}

      {tenant.status !== 'decommissioned' && (
        <DangerZone tenant={tenant} onDone={() => navigate('/towns')} />
      )}
    </div>
  )
}

// ------------------------------------------------------------------ Overview
function Field({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div>
      <div className="text-xs text-white/40 uppercase tracking-wide mb-1">{label}</div>
      <div className={`text-white ${mono ? 'font-mono text-sm break-all' : ''}`}>{value || <span className="text-white/30">—</span>}</div>
    </div>
  )
}

function Overview({ tenant }: { tenant: Tenant }) {
  return (
    <div className="grid md:grid-cols-2 gap-4">
      <Card>
        <h3 className="font-semibold text-white mb-4">Deployment</h3>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Running version" value={tenant.running_version} />
          <Field label="Target version" value={tenant.target_version} />
          <Field label="Region" value={tenant.region} />
          <Field label="Plan" value={tenant.plan} />
          <Field label="Backend port" value={tenant.backend_port} mono />
          <Field label="Frontend port" value={tenant.frontend_port} mono />
        </div>
      </Card>
      <Card>
        <h3 className="font-semibold text-white mb-4">Provisioned resources</h3>
        <div className="space-y-3">
          <Field label="Database" value={tenant.db_name} mono />
          <Field label="Storage bucket" value={tenant.storage_bucket} mono />
          <Field label="KMS wrapping key" value={tenant.kms_key_ref} mono />
        </div>
        <p className="text-xs text-white/40 mt-4">
          Crypto-shred on decommission destroys the KMS key, making all resident PII
          unrecoverable.
        </p>
      </Card>
    </div>
  )
}

// -------------------------------------------------------------- Domain & contact
function DomainContact({ tenant, onSaved }: { tenant: Tenant; onSaved: () => void }) {
  const BASE_DOMAIN = getBaseDomain()
  const toast = useToast()
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({
    custom_domain: tenant.custom_domain || '',
    contact_name: tenant.contact_name || '',
    contact_title: tenant.contact_title || '',
    contact_email: tenant.contact_email || '',
    contact_phone: tenant.contact_phone || '',
    address: tenant.address || '',
    notes: tenant.notes || '',
    latitude: tenant.latitude != null ? String(tenant.latitude) : '',
    longitude: tenant.longitude != null ? String(tenant.longitude) : '',
  })
  function set(k: keyof typeof form, v: string) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  async function save() {
    setSaving(true)
    try {
      await api.updateTenant(tenant.id, {
        custom_domain: form.custom_domain.trim() ? form.custom_domain.trim().toLowerCase() : null,
        contact_name: form.contact_name || null,
        contact_title: form.contact_title || null,
        contact_email: form.contact_email || null,
        contact_phone: form.contact_phone || null,
        address: form.address || null,
        notes: form.notes || null,
        latitude: form.latitude.trim() ? Number(form.latitude) : null,
        longitude: form.longitude.trim() ? Number(form.longitude) : null,
      })
      toast.push('Saved')
      onSaved()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <h3 className="font-semibold text-white mb-1">Domain</h3>
        <p className="text-sm text-white/50 mb-4">
          Default subdomain: <code className="text-white/70">{tenant.subdomain}.{BASE_DOMAIN}</code> (immutable).
          Add a custom domain to override it.
        </p>
        <Input
          label="Custom domain (optional)"
          placeholder="311.springfield.gov"
          value={form.custom_domain}
          onChange={(e) => set('custom_domain', e.target.value)}
          helperText="Leave blank to serve on the state subdomain. Custom domains need a CNAME to the managed host; TLS is issued on demand."
        />
      </Card>

      <Card>
        <h3 className="font-semibold text-white mb-4">Municipality contact</h3>
        <div className="grid sm:grid-cols-2 gap-4">
          <Input label="Primary contact" value={form.contact_name} onChange={(e) => set('contact_name', e.target.value)} />
          <Input label="Title" value={form.contact_title} onChange={(e) => set('contact_title', e.target.value)} />
          <Input label="Email" type="email" value={form.contact_email} onChange={(e) => set('contact_email', e.target.value)} />
          <Input label="Phone" value={form.contact_phone} onChange={(e) => set('contact_phone', e.target.value)} />
        </div>
        <div className="mt-4 space-y-4">
          <Input label="Mailing address" value={form.address} onChange={(e) => set('address', e.target.value)} />
          <Textarea label="Notes (internal)" value={form.notes} onChange={(e) => set('notes', e.target.value)} />
        </div>
      </Card>

      <Card>
        <h3 className="font-semibold text-white mb-1">Location (for the State Map)</h3>
        <p className="text-sm text-white/50 mb-4">
          Optional latitude / longitude in decimal degrees to place this municipality on the state
          map. Metadata only.
        </p>
        <div className="grid sm:grid-cols-2 gap-4">
          <Input
            label="Latitude"
            inputMode="decimal"
            placeholder="39.7817"
            value={form.latitude}
            onChange={(e) => set('latitude', e.target.value)}
          />
          <Input
            label="Longitude"
            inputMode="decimal"
            placeholder="-89.6501"
            value={form.longitude}
            onChange={(e) => set('longitude', e.target.value)}
          />
        </div>
      </Card>

      <div className="flex justify-end">
        <Button onClick={save} isLoading={saving} leftIcon={<Save className="w-4 h-4" />}>
          Save changes
        </Button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Keys tab
function KeysTab({ tenant, onChanged }: { tenant: Tenant; onChanged: () => void }) {
  const toast = useToast()
  const [catalog, setCatalog] = useState<KeyCatalog | null>(null)
  const [assignments, setAssignments] = useState<Record<string, string>>(tenant.key_assignments || {})
  const [secrets, setSecrets] = useState<SecretOut[]>([])
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  async function loadAll() {
    const [cat, asg, secs] = await Promise.all([
      api.keyCatalog(),
      api.getAssignments(tenant.id),
      api.listSecrets(tenant.id),
    ])
    setCatalog(cat)
    setAssignments(asg.assignments)
    setSecrets(secs)
  }
  useEffect(() => {
    loadAll().catch((e) => toast.push((e as Error).message, 'error'))
  }, [tenant.id])

  async function saveAssignments() {
    setSaving(true)
    try {
      const r = await api.setAssignments(tenant.id, assignments)
      setAssignments(r.assignments)
      setDirty(false)
      toast.push('Key responsibilities saved')
      onChanged()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }

  if (!catalog) return <Spinner />

  const perTownServices = catalog.assignable.filter((s) => assignments[s.id] === 'state_per_town')
  const sharedServices = catalog.assignable.filter((s) => assignments[s.id] === 'state_shared')

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center justify-between mb-1">
          <h3 className="font-semibold text-white">Key responsibility matrix</h3>
          {dirty && (
            <Button size="sm" onClick={saveAssignments} isLoading={saving} leftIcon={<Save className="w-4 h-4" />}>
              Save
            </Button>
          )}
        </div>
        <p className="text-sm text-white/50 mb-4">
          Set once. <b>Town</b> keys are entered by the town in its own instance.{' '}
          <b>State · shared</b> keys use one credential you enter once under{' '}
          <Link to="/settings" className="text-indigo-300 hover:text-indigo-200">
            State credentials
          </Link>
          . <b>State · per-town</b> keys take a distinct value per town, entered below.
        </p>
        <KeyMatrix
          catalog={catalog}
          assignments={assignments}
          onChange={(sid, owner) => {
            setAssignments((a) => ({ ...a, [sid]: owner }))
            setDirty(true)
          }}
        />
      </Card>

      {perTownServices.length > 0 && (
        <BrokeredSecrets
          tenantId={tenant.id}
          services={perTownServices}
          secrets={secrets}
          onChange={() => api.listSecrets(tenant.id).then(setSecrets)}
        />
      )}

      {sharedServices.length > 0 && (
        <Card>
          <h3 className="font-semibold text-white mb-1">Shared state credentials in use</h3>
          <p className="text-sm text-white/50 mb-3">
            These services plug into the shared state pool. Set their values once under{' '}
            <Link to="/settings" className="text-indigo-300 hover:text-indigo-200">
              Settings → State credentials
            </Link>
            .
          </p>
          <div className="flex flex-wrap gap-1.5">
            {sharedServices.map((s) => (
              <Badge key={s.id} variant="info">
                {s.label}
              </Badge>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

function BrokeredSecrets({
  tenantId,
  services,
  secrets,
  onChange,
}: {
  tenantId: string
  services: KeyCatalog['assignable']
  secrets: SecretOut[]
  onChange: () => void
}) {
  const toast = useToast()
  const [values, setValues] = useState<Record<string, string>>({})
  const [savingKey, setSavingKey] = useState('')
  const configured = new Set(secrets.map((s) => s.key_name))

  async function save(key: string) {
    if (!values[key]) return
    setSavingKey(key)
    try {
      await api.putSecret(tenantId, key, values[key])
      setValues((v) => ({ ...v, [key]: '' }))
      toast.push(`${key} stored (encrypted)`)
      onChange()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setSavingKey('')
    }
  }

  const allKeys = services.flatMap((s) => s.keys.map((k) => ({ key: k, label: s.label })))

  return (
    <Card>
      <h3 className="font-semibold text-white mb-1">Per-town state credentials</h3>
      <p className="text-sm text-white/50 mb-4">
        A distinct value for this town, for the services set to <b>State · per-town</b>. Stored
        encrypted at rest; write-only (never displayed back).
      </p>
      <div className="space-y-3">
        {allKeys.map(({ key, label }) => (
          <div key={key} className="flex flex-col sm:flex-row sm:items-center gap-2">
            <div className="sm:w-64 shrink-0">
              <div className="text-sm text-white font-medium">{label}</div>
              <code className="text-[11px] text-white/40">{key}</code>
            </div>
            <div className="flex-1 flex gap-2">
              <input
                type="password"
                className="glass-input"
                placeholder={configured.has(key) ? '•••••••• (configured — enter to replace)' : 'Enter value'}
                value={values[key] || ''}
                onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
              />
              <Button size="sm" onClick={() => save(key)} isLoading={savingKey === key} disabled={!values[key]}>
                Save
              </Button>
            </div>
            {configured.has(key) && (
              <Badge variant="success">
                <Check className="w-3 h-3" /> set
              </Badge>
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}

// -------------------------------------------------------------- Provisioning
function Provisioning({ tenant }: { tenant: Tenant }) {
  const toast = useToast()
  const [jobs, setJobs] = useState<ProvisionJob[]>([])
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    api
      .listJobs(tenant.id)
      .then(setJobs)
      .catch((e) => toast.push((e as Error).message, 'error'))
      .finally(() => setLoading(false))
  }, [tenant.id])

  if (loading) return <Spinner />
  if (jobs.length === 0)
    return (
      <Card>
        <p className="text-white/50 text-center py-6">
          No provisioning runs yet. Use <b>Provision</b> above to create this town's stack.
        </p>
      </Card>
    )

  const stepColor: Record<string, string> = {
    done: 'text-green-300',
    skipped: 'text-white/40',
    failed: 'text-red-300',
    pending: 'text-white/40',
  }

  return (
    <div className="space-y-4">
      {jobs.map((job) => (
        <Card key={job.id}>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="font-medium text-white">Run {job.id.slice(0, 8)}</span>
              <Badge variant={job.status === 'succeeded' ? 'success' : job.status === 'failed' ? 'danger' : 'warning'}>
                {job.status}
              </Badge>
            </div>
            <span className="text-xs text-white/40">{timeAgo(job.created_at)}</span>
          </div>
          {job.onboarding_link && (
            <div className="flex items-center gap-2 mb-3 p-2.5 rounded-lg bg-indigo-500/10 border border-indigo-500/30">
              <span className="text-sm text-indigo-200 truncate flex-1">{job.onboarding_link}</span>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(job.onboarding_link!)
                  toast.push('Onboarding link copied')
                }}
                className="text-indigo-300 hover:text-white"
              >
                <Copy className="w-4 h-4" />
              </button>
            </div>
          )}
          <div className="space-y-1.5">
            {job.steps.map((s) => (
              <div key={s.position} className="flex items-start gap-3 text-sm">
                <span className={`font-mono ${stepColor[s.status] || 'text-white/50'} w-16 shrink-0`}>{s.status}</span>
                <span className="text-white/70 w-52 shrink-0">{s.name}</span>
                <span className="text-white/40 flex-1">{s.detail}</span>
              </div>
            ))}
          </div>
          {job.error && <p className="text-red-300 text-sm mt-3">{job.error}</p>}
        </Card>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- Break-glass
function BreakGlass({ tenant }: { tenant: Tenant }) {
  const toast = useToast()
  const [actor, setActor] = useState('')
  const [reason, setReason] = useState('')
  const [minutes, setMinutes] = useState(30)
  const [issuing, setIssuing] = useState(false)
  const [issued, setIssued] = useState<{ token: string; expires_at: string } | null>(null)

  async function issue() {
    setIssuing(true)
    try {
      const g = await api.issueGrant({ tenant_id: tenant.id, actor, reason, minutes })
      setIssued({ token: g.token!, expires_at: g.expires_at })
      toast.push('Break-glass token issued (shown once)')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setIssuing(false)
    }
  }

  return (
    <Card>
      <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
        <ShieldAlert className="w-5 h-5 text-amber-300" /> Emergency state-ops access
      </h3>
      <p className="text-sm text-white/50 mb-4">
        Issues a time-boxed, audited token that a state operator exchanges at the town for a
        temporary admin session. Every use is logged in the town's own audit trail as
        <code className="text-white/70 mx-1">state_ops</code>. Requires the town to be provisioned.
      </p>
      {issued ? (
        <div className="space-y-3">
          <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30">
            <div className="text-xs text-amber-200/70 mb-1">One-time token — copy it now, expires {timeAgo(issued.expires_at).replace('ago', 'from issue')}</div>
            <div className="flex items-center gap-2">
              <code className="text-xs text-amber-100 break-all flex-1">{issued.token}</code>
              <button onClick={() => { navigator.clipboard.writeText(issued.token); toast.push('Copied') }} className="text-amber-300 hover:text-white shrink-0">
                <Copy className="w-4 h-4" />
              </button>
            </div>
          </div>
          <Button variant="secondary" onClick={() => setIssued(null)}>Issue another</Button>
        </div>
      ) : (
        <div className="space-y-4 max-w-lg">
          <Input label="Operator (who is accessing)" placeholder="ops@state.gov" value={actor} onChange={(e) => setActor(e.target.value)} />
          <Textarea label="Reason (audited)" placeholder="Investigating stuck migration for ticket #123" value={reason} onChange={(e) => setReason(e.target.value)} />
          <Input label="Duration (minutes)" type="number" min={1} max={60} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} helperText="Clamped to the panel maximum (60 min)." />
          <Button onClick={issue} isLoading={issuing} disabled={!actor || reason.length < 10} leftIcon={<KeyRound className="w-4 h-4" />}>
            Issue break-glass token
          </Button>
        </div>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------- Danger zone
function DangerZone({ tenant, onDone }: { tenant: Tenant; onDone: () => void }) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)

  async function decommission() {
    setBusy(true)
    try {
      await api.decommission(tenant.id, confirm)
      toast.push(`${tenant.name} decommissioned — KMS key destroyed`)
      onDone()
    } catch (e) {
      toast.push((e as Error).message, 'error')
      setBusy(false)
    }
  }

  return (
    <>
      <div className="mt-8 rounded-2xl border border-red-500/30 bg-red-500/5 p-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h3 className="font-semibold text-red-200">Decommission municipality</h3>
            <p className="text-sm text-white/50 mt-1">
              Tears down the stack, deletes brokered secrets, and crypto-shreds the KMS key —
              all resident PII becomes unrecoverable. Irreversible.
            </p>
          </div>
          <Button variant="danger" onClick={() => setOpen(true)} leftIcon={<Trash2 className="w-4 h-4" />}>
            Decommission
          </Button>
        </div>
      </div>

      <Modal open={open} onClose={() => setOpen(false)} title="Decommission — irreversible">
        <p className="text-white/70 text-sm mb-4">
          This destroys the town's KMS wrapping key. Type the slug{' '}
          <code className="text-white bg-white/10 rounded px-1.5 py-0.5">{tenant.slug}</code> to confirm.
        </p>
        <Input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder={tenant.slug} autoFocus />
        <div className="flex justify-end gap-2 mt-6">
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={decommission} isLoading={busy} disabled={confirm !== tenant.slug} leftIcon={<Trash2 className="w-4 h-4" />}>
            Permanently decommission
          </Button>
        </div>
      </Modal>
    </>
  )
}
