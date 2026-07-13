import { useEffect, useState } from 'react'
import { Building2, KeyRound, Info, Check, Users } from 'lucide-react'
import { api } from '../lib/api'
import type { KeyCatalog, SecretOut } from '../lib/types'
import { Badge, Button, Card, Spinner } from '../components/ui'
import { OWNER_META } from '../components/KeyMatrix'
import { PageHeader } from '../components/Shell'
import { getBaseDomain } from '../lib/config'
import { useToast } from '../components/Toast'

export function Settings() {
  const BASE_DOMAIN = getBaseDomain()
  const toast = useToast()
  const [catalog, setCatalog] = useState<KeyCatalog | null>(null)
  const [creds, setCreds] = useState<SecretOut[]>([])

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
          <>
            <SharedCredentials catalog={catalog} creds={creds} onChange={loadCreds} />

            <Card>
              <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
                <KeyRound className="w-5 h-5" /> Default key responsibility
              </h3>
              <p className="text-sm text-white/50 mb-4">
                The starting point for each new municipality's matrix. Flip any of these per town
                when you add or edit it.
              </p>
              <div className="space-y-2">
                {catalog.assignable.map((s) => {
                  const meta = OWNER_META[s.default_owner]
                  const Icon = meta?.icon || Building2
                  return (
                    <div key={s.id} className="flex items-center justify-between py-2 border-b border-white/5">
                      <div>
                        <div className="text-white font-medium">{s.label}</div>
                        <code className="text-[11px] text-white/40">{s.keys.join(', ')}</code>
                      </div>
                      <span
                        className={`inline-flex items-center gap-1.5 text-sm ${
                          s.default_owner === 'town' ? 'text-white/60' : 'text-indigo-200'
                        }`}
                      >
                        <Icon className="w-4 h-4" /> {meta?.label || s.default_owner}
                      </span>
                    </div>
                  )
                })}
              </div>
            </Card>
          </>
        )}
      </div>
    </div>
  )
}

/**
 * Enter each shared state credential ONCE. Every town whose matrix sets that
 * service to "State · shared" plugs into this value at provision time.
 */
function SharedCredentials({
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
      toast.push(`${key} stored in the shared pool (encrypted)`)
      onChange()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setSavingKey('')
    }
  }

  const rows = catalog.assignable.flatMap((s) =>
    s.keys.map((k) => ({ key: k, label: s.label })),
  )

  return (
    <Card>
      <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
        <Users className="w-5 h-5" /> Shared state credentials
      </h3>
      <p className="text-sm text-white/50 mb-4">
        Enter a credential once here and every town set to <b>State · shared</b> for that service
        plugs into it — no per-town re-entry. Stored encrypted at rest; write-only.
      </p>
      <div className="space-y-3">
        {rows.map(({ key, label }) => (
          <div key={key} className="flex flex-col sm:flex-row sm:items-center gap-2">
            <div className="sm:w-64 shrink-0">
              <div className="text-sm text-white font-medium">{label}</div>
              <code className="text-[11px] text-white/40">{key}</code>
            </div>
            <div className="flex-1 flex gap-2">
              <input
                type="password"
                className="glass-input"
                placeholder={configured.has(key) ? '•••••••• (set — enter to replace)' : 'Enter shared value'}
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
