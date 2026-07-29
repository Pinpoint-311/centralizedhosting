import { useEffect, useState } from 'react'
import { Info, ShieldCheck, RotateCw, SlidersHorizontal, Archive, CheckCircle, AlertTriangle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import type { SystemConfig, RetentionPolicy, RetentionState, PostureControl, PostureSummary } from '../../lib/types'
import { Button, Card, Select, Spinner } from '../../components/ui'
import { getBaseDomain } from '../../lib/config'
import { useToast } from '../../components/Toast'
import { useSession } from '../../lib/session'
import { Announcements } from '../Settings'

function fmt(v: unknown): string {
  if (typeof v === 'boolean') return v ? 'on' : 'off'
  if (v === null || v === undefined || v === '') return '—'
  return String(v)
}

/**
 * Security posture — the hardening controls, each with what it means when it's
 * OFF. This replaced a flat key/value dump of the same values: in that form
 * `cosign_verify: off` (a real finding) looked identical to `base_domain`
 * (just a fact), so the card couldn't tell an operator anything was wrong.
 */
function SecurityPosture({ posture, summary }: { posture: PostureControl[]; summary: PostureSummary }) {
  const clean = summary.warnings === 0
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-1">
        <h3 className="font-semibold text-white flex items-center gap-2">
          <ShieldCheck className="w-5 h-5" /> Security posture
        </h3>
        <span
          className={`text-xs px-2.5 py-1 rounded-full border ${clean
            ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
            : 'bg-amber-500/15 text-amber-300 border-amber-500/30'}`}
        >
          {summary.enabled}/{summary.total} enabled
          {clean ? '' : ` · ${summary.warnings} gap${summary.warnings === 1 ? '' : 's'}`}
        </span>
      </div>
      <p className="text-sm text-white/50 mb-4">
        Hardening controls for this control plane, set by environment variables on the host. Each
        one that's off says what that actually exposes.
      </p>
      <div className="space-y-2">
        {posture.map((c) => {
          const on = c.enabled
          const warn = c.severity === 'warning'
          return (
            <div
              key={c.key}
              className={`flex items-start gap-3 p-3 rounded-xl border ${on
                ? 'bg-white/[0.03] border-white/10'
                : warn
                  ? 'bg-amber-500/[0.07] border-amber-500/25'
                  : 'bg-white/[0.03] border-white/10'}`}
            >
              {on ? (
                <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
              ) : warn ? (
                <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              ) : (
                <Info className="w-4 h-4 text-white/40 shrink-0 mt-0.5" />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-white">{c.label}</span>
                  <span
                    className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded ${on
                      ? 'bg-emerald-500/15 text-emerald-300'
                      : warn
                        ? 'bg-amber-500/15 text-amber-300'
                        : 'bg-white/10 text-white/50'}`}
                  >
                    {on ? 'Enabled' : 'Off'}
                  </span>
                </div>
                <p className={`text-xs mt-0.5 ${on ? 'text-white/45' : 'text-white/70'}`}>{c.detail}</p>
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

/**
 * Records-retention policy — the app's admin retention settings, ported. The
 * state table and the effective-days maths are the app's; here the policy is
 * the hosting organization's default, pushed down to every town it hosts.
 */
function RetentionPolicySection() {
  const toast = useToast()
  const { can } = useSession()
  const [states, setStates] = useState<RetentionState[] | null>(null)
  const [policy, setPolicy] = useState<RetentionPolicy | null>(null)
  const [saving, setSaving] = useState(false)

  async function load() {
    try {
      const [s, p] = await Promise.all([api.retentionStates(), api.retentionPolicy()])
      setStates(s)
      setPolicy(p)
    } catch (e) {
      toast.push((e as Error).message, 'error')
    }
  }
  useEffect(() => { load() }, [])

  async function save(body: { state_code?: string; override_days?: number; mode?: string }) {
    setSaving(true)
    try {
      await api.updateRetentionPolicy(body)
      await load()
      toast.push('Retention policy updated')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }

  if (!policy || !states) return <Card><Spinner /></Card>

  const years = (policy.effective_days / 365).toFixed(1)
  return (
    <Card>
      <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
        <Archive className="w-5 h-5" /> Records retention
      </h3>
      <p className="text-sm text-white/50 mb-4">
        Your jurisdiction's records-retention rule. This is the default pushed to every municipality
        you host — a town under managed policy can't shorten it.
      </p>

      <div className="grid sm:grid-cols-3 gap-4 mb-4">
        <div className="p-4 rounded-xl bg-white/[0.03] border border-white/10">
          <div className="text-2xl font-bold text-white">{years} yrs</div>
          <div className="text-xs text-white/40 mt-0.5">Effective retention</div>
        </div>
        <div className="p-4 rounded-xl bg-white/[0.03] border border-white/10">
          <div className="text-2xl font-bold text-white capitalize">{policy.mode}</div>
          <div className="text-xs text-white/40 mt-0.5">At expiry</div>
        </div>
        <div className="p-4 rounded-xl bg-white/[0.03] border border-white/10">
          <div className="text-2xl font-bold text-white">{policy.stats.towns_covered}</div>
          <div className="text-xs text-white/40 mt-0.5">Municipalities covered</div>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 gap-4">
        <Select
          label="Jurisdiction"
          value={policy.state_code}
          disabled={!can('admin') || saving}
          onChange={(e) => save({ state_code: e.target.value })}
          options={states.map((s) => ({ value: s.code, label: `${s.name} — ${s.retention_years} yrs` }))}
        />
        <Select
          label="At expiry"
          value={policy.mode}
          disabled={!can('admin') || saving}
          onChange={(e) => save({ mode: e.target.value })}
          options={[
            { value: 'anonymize', label: 'Anonymize (keep the record, strip personal data)' },
            { value: 'delete', label: 'Delete the record entirely' },
          ]}
        />
      </div>

      <p className="text-xs text-white/40 mt-3">
        {policy.policy.name}: {policy.policy.retention_years} years under {policy.policy.public_records_law}
        {' '}(source: {policy.policy.source}).
        {policy.override_days ? ` Overridden to ${policy.override_days} days.` : ''}
      </p>
    </Card>
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
      const skipped = r.skipped ? `, skipped ${r.skipped} undecryptable` : ''
      toast.push(`Re-encrypted ${r.reencrypted} secret(s)${skipped} (KMS: ${r.kms_backend})`)
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

      {!cfg ? (
        <Card><Spinner /></Card>
      ) : (
        <>
          <SecurityPosture posture={cfg.posture} summary={cfg.summary} />

          <Card>
            <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
              <SlidersHorizontal className="w-5 h-5" /> Deployment
            </h3>
            <p className="text-sm text-white/50 mb-4">
              How this control plane is deployed. Set by environment variables on the host and shown
              read-only — change them in your deployment, not the browser.
            </p>
            <div className="grid sm:grid-cols-2 gap-x-8 gap-y-1.5">
              {Object.entries(cfg.deployment).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between gap-3 text-sm py-1 border-b border-white/5">
                  <span className="text-white/60">{k.replace(/_/g, ' ')}</span>
                  <span className="text-white font-mono text-xs text-right break-all">{fmt(v)}</span>
                </div>
              ))}
            </div>
            <div className="flex items-start gap-2 mt-4 p-3 rounded-lg bg-blue-500/10 border border-blue-500/20">
              <Info className="w-4 h-4 text-blue-300 shrink-0 mt-0.5" />
              <p className="text-xs text-blue-100/70">
                Towns live at <code>&lt;slug&gt;.{BASE_DOMAIN}</code> via wildcard TLS. Encryption
                backend and background-loop intervals live on{' '}
                <Link to="/setup/health" className="underline hover:text-blue-100">System Health</Link>.
              </p>
            </div>
          </Card>
        </>
      )}

      <RetentionPolicySection />

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
