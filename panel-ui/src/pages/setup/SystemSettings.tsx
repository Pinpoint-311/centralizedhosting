import { useEffect, useState } from 'react'
import { Info, ShieldCheck, RotateCw, SlidersHorizontal } from 'lucide-react'
import { api } from '../../lib/api'
import type { SystemConfig } from '../../lib/types'
import { Button, Card, Spinner } from '../../components/ui'
import { getBaseDomain } from '../../lib/config'
import { useToast } from '../../components/Toast'
import { useSession } from '../../lib/session'
import { Announcements } from '../Settings'

function fmt(v: unknown): string {
  if (typeof v === 'boolean') return v ? 'on' : 'off'
  if (v === null || v === undefined || v === '') return '—'
  return String(v)
}

function ConfigGroup({ title, values }: { title: string; values: Record<string, unknown> }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-white/40 mb-2">{title}</div>
      <div className="space-y-1.5">
        {Object.entries(values).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-3 text-sm py-1 border-b border-white/5">
            <span className="text-white/60">{k.replace(/_/g, ' ')}</span>
            <span className="text-white font-mono text-xs text-right">{fmt(v)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function SystemSettings() {
  const BASE_DOMAIN = getBaseDomain()
  const toast = useToast()
  const { can } = useSession()
  const [cfg, setCfg] = useState<SystemConfig | null>(null)
  const [busy, setBusy] = useState('')
  const [auditState, setAuditState] = useState('')

  useEffect(() => {
    api.systemConfig().then(setCfg).catch((e) => toast.push((e as Error).message, 'error'))
  }, [])

  async function verifyAudit() {
    setBusy('verify')
    try {
      const r = await api.auditVerify()
      setAuditState(r.ok ? `Intact — ${r.entries} entries chained` : `BROKEN at #${r.broken_at_seq}: ${r.reason}`)
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally { setBusy('') }
  }
  async function rotate() {
    setBusy('rotate')
    try {
      const r = await api.reencryptSecrets()
      toast.push(`Re-encrypted ${r.reencrypted} secret(s) (KMS: ${r.kms_backend})`)
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally { setBusy('') }
  }

  return (
    <div className="space-y-4">
      <div className="mb-2">
        <h1 className="text-xl sm:text-2xl font-bold text-white flex items-center gap-2">
          <SlidersHorizontal className="w-6 h-6" /> System Settings
        </h1>
        <p className="text-white/50 text-sm mt-1">
          The control plane's effective operational configuration and maintenance actions.
        </p>
      </div>

      <Card>
        <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
          <SlidersHorizontal className="w-5 h-5" /> Effective configuration
        </h3>
        <p className="text-sm text-white/50 mb-4">
          The control plane's live operational settings. These are set by environment variables on
          the host and shown read-only — change them in your deployment, not the browser.
        </p>
        {!cfg ? (
          <Spinner />
        ) : (
          <div className="grid md:grid-cols-2 gap-x-8 gap-y-5">
            <ConfigGroup title="Deployment" values={cfg.deployment} />
            <ConfigGroup title="Security" values={cfg.security} />
            <ConfigGroup title="Polling" values={cfg.polling} />
            <ConfigGroup title="Backups" values={cfg.backups} />
            <ConfigGroup title="Intake" values={cfg.intake} />
          </div>
        )}
        <div className="flex items-start gap-2 mt-4 p-3 rounded-lg bg-blue-500/10 border border-blue-500/20">
          <Info className="w-4 h-4 text-blue-300 shrink-0 mt-0.5" />
          <p className="text-xs text-blue-100/70">
            Towns live at <code>&lt;slug&gt;.{BASE_DOMAIN}</code> via wildcard TLS. Base domain,
            panel token, and encryption keys come from the environment and aren't browser-editable.
          </p>
        </div>
      </Card>

      <Card>
        <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
          <ShieldCheck className="w-5 h-5" /> Maintenance
        </h3>
        <p className="text-sm text-white/50 mb-4">
          Verify the tamper-evident audit chain, or re-encrypt all stored secrets after rotating the
          KMS key.
        </p>
        <div className="flex flex-wrap gap-2">
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

      <Announcements />
    </div>
  )
}
