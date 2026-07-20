import { useEffect, useState } from 'react'
import { KeyRound, Info, Check, ShieldCheck, RotateCw, UserCircle } from 'lucide-react'
import { api } from '../lib/api'
import type { KeyCatalog, SecretOut } from '../lib/types'
import { Badge, Button, Card, Spinner } from '../components/ui'
import { PageHeader } from '../components/Shell'
import { getBaseDomain } from '../lib/config'
import { useToast } from '../components/Toast'
import { useSession } from '../lib/session'

export function Settings() {
  const BASE_DOMAIN = getBaseDomain()
  const toast = useToast()
  const { who, can } = useSession()
  const [catalog, setCatalog] = useState<KeyCatalog | null>(null)
  const [creds, setCreds] = useState<SecretOut[]>([])
  const [auditState, setAuditState] = useState<string>('')
  const [busy, setBusy] = useState('')

  async function verifyAudit() {
    setBusy('verify')
    try {
      const r = await api.auditVerify()
      setAuditState(r.ok ? `Intact — ${r.entries} entries chained` : `BROKEN at #${r.broken_at_seq}: ${r.reason}`)
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }
  async function rotate() {
    setBusy('rotate')
    try {
      const r = await api.reencryptSecrets()
      toast.push(`Re-encrypted ${r.reencrypted} secret(s) with key v${r.key_version}`)
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }

  async function loadCreds() {
    setCreds(await api.listStateCredentials())
  }
  useEffect(() => {
    Promise.all([api.keyCatalog(), api.listStateCredentials()])
      .then(([c, s]) => {
        setCatalog(c)
        setCreds(s)
      })
      .catch((e) => toast.push((e as Error).message, 'error'))
  }, [])

  return (
    <div>
      <PageHeader title="Settings" subtitle="Program-wide configuration and shared credentials." />

      <div className="space-y-4">
        <Announcements />

        {can('admin') && <SsoFederation />}

        <Card>
          <h3 className="font-semibold text-white mb-4 flex items-center gap-2">
            <ShieldCheck className="w-5 h-5" /> Security &amp; compliance
          </h3>
          <div className="grid sm:grid-cols-2 gap-4">
            <div className="flex items-center gap-2">
              <UserCircle className="w-5 h-5 text-white/40" />
              <div>
                <div className="text-xs text-white/40 uppercase tracking-wide">Signed in as</div>
                <div className="text-white">{who?.actor || '—'} <Badge variant="info">{who?.role || 'unknown'}</Badge></div>
              </div>
            </div>
            <div>
              <div className="text-xs text-white/40 uppercase tracking-wide mb-1">Secret key provider</div>
              <div className="text-white">{who?.key_provider || '—'} {who?.require_signed_images && <Badge variant="success">signed images required</Badge>}</div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 mt-4">
            <Button variant="secondary" onClick={verifyAudit} isLoading={busy === 'verify'} leftIcon={<ShieldCheck className="w-4 h-4" />}>
              Verify audit chain
            </Button>
            {can('approver') && (
              <Button variant="secondary" onClick={rotate} isLoading={busy === 'rotate'} leftIcon={<RotateCw className="w-4 h-4" />}>
                Re-encrypt secrets (key rotation)
              </Button>
            )}
          </div>
          {auditState && (
            <p className={`text-sm mt-3 ${auditState.startsWith('Intact') ? 'text-green-300' : 'text-red-300'}`}>{auditState}</p>
          )}
        </Card>

        <Card>
          <h3 className="font-semibold text-white mb-4">Program identity</h3>
          <div className="grid sm:grid-cols-2 gap-4">
            <div>
              <div className="text-xs text-white/40 uppercase tracking-wide mb-1">Base domain</div>
              <div className="text-white font-mono">{BASE_DOMAIN}</div>
              <p className="text-xs text-white/40 mt-1">Towns live at <code>&lt;slug&gt;.{BASE_DOMAIN}</code> via wildcard TLS.</p>
            </div>
            <div>
              <div className="text-xs text-white/40 uppercase tracking-wide mb-1">Deployment mode</div>
              <div className="text-white">Compose per town (MVP)</div>
              <p className="text-xs text-white/40 mt-1">Graduates to Kubernetes/GitOps behind the same API.</p>
            </div>
          </div>
          <div className="flex items-start gap-2 mt-4 p-3 rounded-lg bg-blue-500/10 border border-blue-500/20">
            <Info className="w-4 h-4 text-blue-300 shrink-0 mt-0.5" />
            <p className="text-xs text-blue-100/70">
              Base domain, panel token, and encryption key are set as environment variables on the
              control plane (<code>BASE_DOMAIN</code>, <code>PANEL_API_TOKEN</code>, <code>PANEL_SECRET_KEY</code>) and
              are intentionally not editable from the browser.
            </p>
          </div>
        </Card>

        {!catalog ? (
          <Spinner />
        ) : (
          <ApiKeysHub catalog={catalog} creds={creds} onChange={loadCreds} />
        )}
      </div>
    </div>
  )
}

/**
 * One place to set up API keys: enter each credential the State provides once
 * (services set to "State" use it), and see at a glance who provides the rest.
 */
function ApiKeysHub({
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

  // Services the State provides once, program-wide (need a credential here).
  const shared = catalog.assignable.filter((s) => s.default_owner === 'state_shared')
  const perTown = catalog.assignable.filter((s) => s.default_owner === 'state_per_town')
  const towned = catalog.assignable.filter((s) => s.default_owner === 'town')

  return (
    <Card>
      <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
        <KeyRound className="w-5 h-5" /> API keys &amp; credentials
      </h3>
      <p className="text-sm text-white/50 mb-5">
        Enter each credential the <b>State</b> provides once — every town using it plugs in
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
              <span className="text-indigo-200">State, per town:</span>{' '}
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

function Announcements() {
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
        <Input placeholder="e.g. Planned maintenance Saturday 2–4am ET" value={title} onChange={(e) => setTitle(e.target.value)} />
        <div className="w-44 shrink-0">
          <Select value={severity} onChange={(e) => setSeverity(e.target.value)} options={[
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

// -------------------------------------------------- SSO / identity federation
import { LogIn, Plus as PlusIcon, Trash2 as TrashIcon } from 'lucide-react'
import type { FederationConfig, Role } from '../lib/types'

const PANEL_ROLES: Role[] = ['viewer', 'operator', 'approver', 'admin']

function SsoFederation() {
  const toast = useToast()
  const [cfg, setCfg] = useState<FederationConfig | null>(null)
  const [secret, setSecret] = useState('')
  const [rows, setRows] = useState<{ group: string; role: Role }[]>([])
  const [busy, setBusy] = useState('')

  function hydrate(c: FederationConfig) {
    setCfg(c)
    setRows(Object.entries(c.group_role_map || {}).map(([group, role]) => ({ group, role: role as Role })))
  }
  useEffect(() => {
    api.getFederation().then(hydrate).catch((e) => toast.push((e as Error).message, 'error'))
  }, [])

  if (!cfg) return null
  const set = (k: keyof FederationConfig, v: unknown) => setCfg({ ...cfg, [k]: v } as FederationConfig)

  async function save() {
    setBusy('save')
    try {
      const group_role_map: Record<string, string> = {}
      rows.forEach((r) => { if (r.group.trim()) group_role_map[r.group.trim()] = r.role })
      const body: Record<string, unknown> = {
        enabled: cfg!.enabled,
        provider: cfg!.provider,
        issuer: cfg!.issuer || '',
        client_id: cfg!.client_id || '',
        groups_claim: cfg!.groups_claim || 'groups',
        group_role_map,
        default_role: cfg!.default_role,
      }
      if (secret) body.client_secret = secret
      const out = await api.putFederation(body)
      hydrate(out)
      setSecret('')
      toast.push('SSO federation saved')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }
  async function test() {
    setBusy('test')
    try {
      const r = await api.testFederation()
      toast.push(`Reached IdP: ${r.issuer}`)
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }

  return (
    <Card>
      <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
        <LogIn className="w-5 h-5" /> Single sign-on (SSO)
        {cfg.enabled && cfg.client_secret_set && <Badge variant="success">configured</Badge>}
      </h3>
      <p className="text-sm text-white/50 mb-4">
        Let operators sign in with your identity provider (Okta, Entra/Azure AD, Auth0, Login.gov —
        any OpenID Connect issuer). The client secret is stored encrypted by the panel's secret
        manager and never shown again.
      </p>

      <div className="space-y-4">
        <div className="grid sm:grid-cols-2 gap-4">
          <Input label="Issuer URL" placeholder="https://your-org.okta.com" value={cfg.issuer || ''} onChange={(e) => set('issuer', e.target.value)} helperText="OIDC discovery base (.well-known/openid-configuration)." />
          <Input label="Provider label" placeholder="okta" value={cfg.provider} onChange={(e) => set('provider', e.target.value)} />
          <Input label="Client ID" value={cfg.client_id || ''} onChange={(e) => set('client_id', e.target.value)} />
          <Input
            label="Client secret"
            type="password"
            placeholder={cfg.client_secret_set ? '•••••••• (set — enter to replace)' : 'Enter client secret'}
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
          />
          <Input label="Groups claim" value={cfg.groups_claim} onChange={(e) => set('groups_claim', e.target.value)} helperText="ID-token claim carrying the operator's groups." />
          <Select
            label="Default role (no group match)"
            value={cfg.default_role}
            onChange={(e) => set('default_role', e.target.value)}
            options={PANEL_ROLES.map((r) => ({ value: r, label: r }))}
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium text-white/70">Group → role mapping</label>
            <Button size="sm" variant="ghost" onClick={() => setRows([...rows, { group: '', role: 'viewer' }])} leftIcon={<PlusIcon className="w-4 h-4" />}>Add</Button>
          </div>
          <div className="space-y-2">
            {rows.length === 0 && <p className="text-xs text-white/40">No mappings — everyone who signs in gets the default role above.</p>}
            {rows.map((r, i) => (
              <div key={i} className="flex gap-2 items-center">
                <Input className="flex-1" placeholder="IdP group (e.g. pp311-admins)" value={r.group} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, group: e.target.value } : x))} />
                <div className="w-40">
                  <Select value={r.role} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, role: e.target.value as Role } : x))} options={PANEL_ROLES.map((x) => ({ value: x, label: x }))} />
                </div>
                <button onClick={() => setRows(rows.filter((_, j) => j !== i))} className="text-white/40 hover:text-red-300 shrink-0" aria-label="Remove mapping"><TrashIcon className="w-4 h-4" /></button>
              </div>
            ))}
          </div>
        </div>

        <label className="flex items-center gap-2 text-sm text-white/80 cursor-pointer">
          <input type="checkbox" checked={cfg.enabled} onChange={(e) => set('enabled', e.target.checked)} className="accent-indigo-500 w-4 h-4" />
          Enable SSO sign-in (shows "Sign in with SSO" on the login screen)
        </label>

        <div className="flex flex-wrap gap-2">
          <Button onClick={save} isLoading={busy === 'save'}>Save SSO settings</Button>
          <Button variant="secondary" onClick={test} isLoading={busy === 'test'} disabled={!cfg.issuer}>Test discovery</Button>
        </div>
      </div>
    </Card>
  )
}
