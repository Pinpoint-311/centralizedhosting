import { useEffect, useState } from 'react'
import { Cloud, Cpu, Languages, Fingerprint, CheckCircle, XCircle } from 'lucide-react'
import { api } from '../../lib/api'
import type { ProviderCatalog, ProviderInfo, CloudProfileState } from '../../lib/types'
import { Badge, Button, Card, Input, Select, Spinner } from '../../components/ui'
import { useToast } from '../../components/Toast'
import { useSession } from '../../lib/session'

const CAPS: { key: string; label: string; icon: typeof Cpu; blurb: string }[] = [
  { key: 'ai', label: 'AI analysis', icon: Cpu, blurb: 'Request triage, priority scoring, and summaries for every town.' },
  { key: 'translation', label: 'Translation', icon: Languages, blurb: 'Multi-language resident intake and staff replies.' },
  { key: 'identity', label: 'Staff identity (SSO)', icon: Fingerprint, blurb: 'The identity provider towns federate their staff logins to.' },
]

function CapabilityCard({ cap, label, icon: Icon, blurb }: { cap: string; label: string; icon: typeof Cpu; blurb: string }) {
  const toast = useToast()
  const { can } = useSession()
  const [cat, setCat] = useState<ProviderCatalog | null>(null)
  const [sel, setSel] = useState('')
  const [model, setModel] = useState('')
  const [creds, setCreds] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState('')
  const [status, setStatus] = useState<{ ok: boolean; message: string } | null>(null)

  async function load() {
    const c = await api.providerCatalog(cap)
    setCat(c)
    setSel(c.selected)
    setModel(c.model || '')
  }
  useEffect(() => { load().catch((e) => toast.push((e as Error).message, 'error')) }, [])
  if (!cat) return <Card><Spinner /></Card>

  const provider = cat.providers.find((p) => p.provider === sel) as ProviderInfo | undefined

  async function save() {
    setBusy('save')
    try {
      const c = await api.saveProvider(cap, { provider: sel, model: model || undefined, credentials: creds })
      setCat(c); setCreds({})
      const s = await api.testProvider(cap); setStatus(s)
      toast.push(`${label} saved`)
    } catch (e) { toast.push((e as Error).message, 'error') } finally { setBusy('') }
  }
  async function test() {
    setBusy('test')
    try { setStatus(await api.testProvider(cap)) } catch (e) { toast.push((e as Error).message, 'error') } finally { setBusy('') }
  }

  return (
    <Card>
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 rounded-xl bg-primary-500/15 text-primary-300 flex items-center justify-center"><Icon className="w-5 h-5" /></div>
          <div>
            <h3 className="font-semibold text-white">{label}</h3>
            <p className="text-xs text-white/50">{blurb}</p>
          </div>
        </div>
        {status && (
          <span className={`text-xs flex items-center gap-1 ${status.ok ? 'text-green-300' : 'text-amber-300'}`}>
            {status.ok ? <CheckCircle className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}{status.message}
          </span>
        )}
      </div>

      <div className="grid sm:grid-cols-3 gap-2 mb-4">
        {cat.providers.map((p) => (
          <button
            key={p.provider}
            onClick={() => { setSel(p.provider); setStatus(null); setModel(p.default_model || '') }}
            className={`text-left p-3 rounded-xl border transition-colors ${sel === p.provider ? 'border-primary-400/50 bg-primary-500/10' : 'border-white/10 hover:bg-white/5'}`}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-white">{p.name}</span>
              {cat.selected === p.provider && <Badge variant="success">In use</Badge>}
            </div>
            {p.boundary && <div className="text-[11px] text-white/40 mt-0.5">{p.boundary}</div>}
          </button>
        ))}
      </div>

      {provider && (
        <div className="space-y-3">
          {provider.description && <p className="text-xs text-white/50">{provider.description}</p>}
          {provider.models && provider.models.length > 0 && (
            <Select
              label="Model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              options={provider.models.map((m) => ({ value: m.id, label: m.label }))}
            />
          )}
          <div className="grid sm:grid-cols-2 gap-3">
            {provider.credential_fields.map((f) => {
              const isSet = cat.configured[f.key]
              const val = f.secret ? (creds[f.key] ?? '') : (creds[f.key] ?? cat.values[f.key] ?? '')
              return (
                <Input
                  key={f.key}
                  label={f.label}
                  type={f.secret ? 'password' : 'text'}
                  value={val}
                  placeholder={f.secret && isSet ? '•••••••• (set — enter to replace)' : ''}
                  onChange={(e) => setCreds({ ...creds, [f.key]: e.target.value })}
                  helperText={provider.field_help?.[f.key]}
                />
              )
            })}
          </div>
          <div className="flex gap-2">
            <Button onClick={save} isLoading={busy === 'save'} disabled={!can('admin')}>Save &amp; test</Button>
            <Button variant="secondary" onClick={test} isLoading={busy === 'test'}>Test connection</Button>
          </div>
        </div>
      )}
    </Card>
  )
}

function CloudEnvironment({ onApplied }: { onApplied: () => void }) {
  const toast = useToast()
  const { can } = useSession()
  const [state, setState] = useState<CloudProfileState | null>(null)
  const [busy, setBusy] = useState('')

  useEffect(() => { api.cloudProfile().then(setState).catch((e) => toast.push((e as Error).message, 'error')) }, [])
  if (!state) return <Card><Spinner /></Card>

  async function apply(id: string) {
    setBusy(id)
    try {
      setState(await api.applyCloudProfile(id, true))
      toast.push('Cloud environment applied to AI + translation + identity')
      onApplied()
    } catch (e) { toast.push((e as Error).message, 'error') } finally { setBusy('') }
  }

  return (
    <Card>
      <h3 className="font-semibold text-white mb-1 flex items-center gap-2"><Cloud className="w-5 h-5" /> Cloud environment</h3>
      <p className="text-sm text-white/50 mb-4">
        Pick one compliance boundary and the AI, translation, and identity defaults are set together.
        You can still override any single capability below.
      </p>
      <div className="grid sm:grid-cols-3 gap-3">
        {state.profiles.map((p) => (
          <div key={p.id} className={`p-4 rounded-xl border ${state.current === p.id ? 'border-primary-400/50 bg-primary-500/10' : 'border-white/10'}`}>
            <div className="flex items-center justify-between mb-1">
              <span className="font-medium text-white text-sm">{p.label}</span>
              {state.current === p.id && <Badge variant="success">Active</Badge>}
            </div>
            <p className="text-[11px] text-white/40 mb-3">{p.boundary}</p>
            <Button size="sm" variant={state.current === p.id ? 'ghost' : 'secondary'} className="w-full"
              onClick={() => apply(p.id)} isLoading={busy === p.id} disabled={!can('admin') || state.current === p.id}>
              {state.current === p.id ? 'In use' : 'Use this'}
            </Button>
          </div>
        ))}
      </div>
    </Card>
  )
}

export function ServiceProviders() {
  const [nonce, setNonce] = useState(0)
  return (
    <div className="space-y-4">
      <CloudEnvironment onApplied={() => setNonce((n) => n + 1)} />
      {CAPS.map((c) => <CapabilityCard key={`${c.key}-${nonce}`} cap={c.key} label={c.label} icon={c.icon} blurb={c.blurb} />)}
    </div>
  )
}
