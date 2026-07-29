import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle, Info, Lock, ShieldCheck } from 'lucide-react'
import { api } from '../lib/api'
import type { PostureControl, PostureSummary, SecurityControl } from '../lib/types'
import { Button, Card, Input, Modal } from './ui'
import { useToast } from './Toast'

/**
 * Security posture — now a control surface, not a report.
 *
 * Each row still says what being off actually exposes; the difference is you can
 * change it here instead of editing a container's environment. The portal is
 * authoritative, so a saved value beats the environment — which is why turning a
 * protection off asks first and always lands in the audit log.
 *
 * A control that couldn't work yet (no KMS, no cosign binary, no backup bucket)
 * is shown locked with the reason, rather than offering a switch that would fail.
 */
export function SecurityControls({ posture, summary, onChanged }: {
  posture: PostureControl[]
  summary: PostureSummary
  onChanged: () => void | Promise<void>
}) {
  const toast = useToast()
  const [controls, setControls] = useState<SecurityControl[]>([])
  const [busy, setBusy] = useState('')
  const [confirming, setConfirming] = useState<{ control: SecurityControl; next: boolean } | null>(null)

  async function loadControls() {
    try {
      setControls((await api.listControls()).controls)
    } catch {
      setControls([])  // read-only fallback: the posture list below still renders
    }
  }
  useEffect(() => { loadControls() }, [])

  const byKey = new Map(controls.map((c) => [c.key, c]))

  async function save(control: SecurityControl, next: boolean | number, confirm = false) {
    setBusy(control.key)
    try {
      const r = await api.setControl(control.key, next, confirm)
      toast.push(
        r.rerender
          ? `${control.label} saved — ${r.rerender.rendered} town stacks re-rendered`
          : `${control.label} saved`,
      )
      setConfirming(null)
      await Promise.all([loadControls(), onChanged()])
    } catch (e) {
      const message = (e as Error).message
      // The backend asks for confirmation by refusing once; surface that as a
      // dialog rather than an error the operator can't act on.
      if (/confirm to proceed/i.test(message)) {
        setConfirming({ control, next: Boolean(next) })
      } else {
        toast.push(message, 'error')
      }
    } finally {
      setBusy('')
    }
  }

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
        Hardening controls for this control plane. Changes take effect immediately and
        are recorded in the audit log. Each one that's off says what that exposes.
      </p>

      <div className="space-y-2">
        {posture.map((c) => {
          const on = c.enabled
          const warn = c.severity === 'warning'
          const control = byKey.get(c.key)
          const locked = control && !control.value && !control.can_enable
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
                  {control?.source === 'portal' && (
                    <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-sky-500/15 text-sky-300">
                      set here
                    </span>
                  )}
                  {control?.effect === 'rerender' && (
                    <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-white/10 text-white/50">
                      re-renders towns
                    </span>
                  )}
                </div>
                <p className={`text-xs mt-0.5 ${on ? 'text-white/45' : 'text-white/70'}`}>{c.detail}</p>
                {locked && (
                  <p className="text-xs mt-1 text-amber-200/80 flex gap-1.5">
                    <Lock className="w-3.5 h-3.5 shrink-0 mt-px" />{control!.blocked_because}
                  </p>
                )}
              </div>

              {control?.type === 'bool' ? (
                <Toggle
                  checked={Boolean(control.value)}
                  disabled={busy === c.key || Boolean(locked)}
                  label={c.label}
                  onChange={(next) => save(control, next)}
                />
              ) : control?.type === 'int' ? (
                <NumberControl control={control} busy={busy === c.key}
                               onSave={(v) => save(control, v)} />
              ) : (
                <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-white/10 text-white/50 shrink-0">
                  {on ? 'Enabled' : 'Off'}
                </span>
              )}
            </div>
          )
        })}
      </div>

      {confirming && (
        <Modal
          open
          title={`${confirming.next ? 'Turn on' : 'Turn off'} ${confirming.control.label.toLowerCase()}?`}
          onClose={() => setConfirming(null)}
        >
          <p className="text-sm text-white/70 mb-2">
            {confirming.next
              ? 'This changes how the fleet is deployed for every town.'
              : 'This removes a protection across the whole fleet.'}
          </p>
          <p className="text-sm text-white/50 mb-5">
            The change is recorded in the audit log against your account, and takes
            effect right away.
          </p>
          <div className="flex gap-2 justify-end">
            <Button variant="secondary" onClick={() => setConfirming(null)}>Cancel</Button>
            <Button
              isLoading={busy === confirming.control.key}
              onClick={() => save(confirming.control, confirming.next, true)}
            >
              Yes, {confirming.next ? 'turn it on' : 'turn it off'}
            </Button>
          </div>
        </Modal>
      )}
    </Card>
  )
}

function Toggle({ checked, disabled, label, onChange }: {
  checked: boolean
  disabled?: boolean
  label: string
  onChange: (next: boolean) => void
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`shrink-0 mt-0.5 w-10 h-6 rounded-full border transition-colors relative
        disabled:opacity-40 disabled:cursor-not-allowed
        ${checked ? 'bg-emerald-500/80 border-emerald-400/60' : 'bg-white/10 border-white/20'}`}
    >
      <span
        className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all
          ${checked ? 'left-[1.125rem]' : 'left-0.5'}`}
      />
    </button>
  )
}

function NumberControl({ control, busy, onSave }: {
  control: SecurityControl
  busy: boolean
  onSave: (value: number) => void
}) {
  const [value, setValue] = useState(String(control.value))
  useEffect(() => { setValue(String(control.value)) }, [control.value])
  const dirty = value !== String(control.value)
  return (
    <div className="flex items-center gap-2 shrink-0">
      <Input
        aria-label={control.label}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="!w-24"
      />
      {dirty && (
        <Button size="sm" isLoading={busy} onClick={() => onSave(Number(value))}>
          Save
        </Button>
      )}
    </div>
  )
}
