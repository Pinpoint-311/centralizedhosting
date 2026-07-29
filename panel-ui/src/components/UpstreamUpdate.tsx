import { useState } from 'react'
import {
  AlertTriangle, ArrowRight, CheckCircle2, Database, DownloadCloud,
  ExternalLink, ShieldCheck, ShieldAlert, X,
} from 'lucide-react'
import { api } from '../lib/api'
import type { UpstreamCandidate, UpstreamStatus } from '../lib/types'
import { Badge, Button, Card, Input, Modal, Textarea, timeAgo } from './ui'
import { useToast } from './Toast'

/**
 * Review gate for an upstream app build.
 *
 * The panel finds builds on its own but never deploys one. This card is where a
 * human looks at what changed — the digest, whether it is signed, whether it
 * carries a schema change — and decides. Approving publishes a Release; it still
 * takes a separate rollout, and then a promotion, to reach every town.
 */
export function UpstreamUpdate({ status, onChanged }: {
  status: UpstreamStatus
  onChanged: () => void | Promise<void>
}) {
  const toast = useToast()
  const [checking, setChecking] = useState(false)
  const [reviewing, setReviewing] = useState<UpstreamCandidate | null>(null)
  const candidate = status.pending

  async function check() {
    setChecking(true)
    try {
      const r = await api.checkUpstream()
      toast.push(r.new
        ? `Found ${r.candidate.version} — review it before it goes anywhere`
        : 'No new build on this channel')
      await onChanged()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setChecking(false)
    }
  }

  return (
    <Card className="!p-4 mb-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <DownloadCloud className="w-4 h-4 text-white/50" />
            <h3 className="font-semibold text-white">App updates</h3>
            <Badge>{status.channel}</Badge>
            {status.fleet_drift && (
              <Badge variant="warning">fleet on {status.fleet_versions.length} versions</Badge>
            )}
          </div>
          <p className="text-sm text-white/50 mt-1">
            {candidate
              ? 'A new build is waiting for your review. Nothing has been deployed.'
              : status.fleet_versions.length
                ? `Fleet running ${status.fleet_versions.join(', ')}.`
                : 'No towns are running a released version yet.'}
          </p>
        </div>
        <Button size="sm" variant="secondary" onClick={check} isLoading={checking}
                leftIcon={<DownloadCloud className="w-4 h-4" />}>
          Check for updates
        </Button>
      </div>

      {candidate && (
        <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.03] p-4">
          <div className="flex items-center gap-2 flex-wrap mb-3">
            <span className="font-semibold text-white">v{candidate.version}</span>
            {candidate.signature_verified ? (
              <Badge variant="success"><ShieldCheck className="w-3 h-3 mr-1 inline" />signed</Badge>
            ) : (
              <Badge variant={status.signature_enforced ? 'danger' : 'default'}>
                <ShieldAlert className="w-3 h-3 mr-1 inline" />
                {status.signature_enforced ? 'unverified' : 'signing not enforced'}
              </Badge>
            )}
            {candidate.schema_change && (
              <Badge variant="warning"><Database className="w-3 h-3 mr-1 inline" />schema change</Badge>
            )}
            <span className="text-xs text-white/40">found {timeAgo(candidate.discovered_at)}</span>
          </div>

          <dl className="grid sm:grid-cols-2 gap-x-6 gap-y-1 text-xs mb-3">
            <Row label="Backend digest" value={candidate.backend_digest} mono />
            <Row label="Frontend digest" value={candidate.frontend_digest} mono />
            <Row label="Schema revision" value={candidate.db_revision || '— not stamped'} mono />
            <Row label="Runs against" value={candidate.min_db_revision || '— not stamped'} mono />
          </dl>

          {candidate.schema_change && (
            <p className="text-xs text-amber-200/80 mb-3 flex gap-2">
              <Database className="w-4 h-4 shrink-0 mt-px" />
              <span>
                This build migrates the database.{' '}
                {status.backup_before_migrate
                  ? 'Each town is backed up immediately before its schema changes.'
                  : 'No pre-migration backup will be taken — BACKUPS_ENABLED is off, so there is no restore point if a migration goes wrong.'}
              </span>
            </p>
          )}

          {candidate.blockers.length > 0 && (
            <ul className="text-xs text-red-300/90 mb-3 space-y-1">
              {candidate.blockers.map((b) => (
                <li key={b} className="flex gap-2">
                  <AlertTriangle className="w-4 h-4 shrink-0 mt-px" />{b}
                </li>
              ))}
            </ul>
          )}

          <div className="flex gap-2 flex-wrap items-center">
            <Button size="sm" onClick={() => setReviewing(candidate)}
                    leftIcon={<CheckCircle2 className="w-4 h-4" />}>
              Review and approve
            </Button>
            {candidate.compare_url && (
              <a href={candidate.compare_url} target="_blank" rel="noreferrer noopener"
                 className="text-sm text-white/60 hover:text-white inline-flex items-center gap-1">
                What changed <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>
        </div>
      )}

      {reviewing && (
        <ReviewModal
          candidate={reviewing}
          onClose={() => setReviewing(null)}
          onDone={async () => { setReviewing(null); await onChanged() }}
        />
      )}
    </Card>
  )
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-2 min-w-0">
      <dt className="text-white/40 shrink-0">{label}</dt>
      <dd className={`text-white/70 truncate ${mono ? 'font-mono' : ''}`} title={value}>{value}</dd>
    </div>
  )
}

function ReviewModal({ candidate, onClose, onDone }: {
  candidate: UpstreamCandidate
  onClose: () => void
  onDone: () => void | Promise<void>
}) {
  const toast = useToast()
  const [note, setNote] = useState('')
  const [dbRevision, setDbRevision] = useState(candidate.db_revision || '')
  const [minDbRevision, setMinDbRevision] = useState(candidate.min_db_revision || '')
  const [busy, setBusy] = useState('')

  async function act(kind: 'approve' | 'reject') {
    setBusy(kind)
    try {
      if (kind === 'approve') {
        await api.approveCandidate(candidate.id, {
          note: note || null,
          db_revision: dbRevision || null,
          min_db_revision: minDbRevision || null,
        })
        toast.push(`v${candidate.version} published — start a rollout when you're ready`)
      } else {
        await api.rejectCandidate(candidate.id, { note: note || null })
        toast.push(`v${candidate.version} declined; it won't be offered again`)
      }
      await onDone()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }

  return (
    <Modal open title={`Review v${candidate.version}`} onClose={onClose}>
      <p className="text-sm text-white/60 mb-4">
        Approving publishes this build as a release. It does not deploy: you still
        start a canary rollout, and promote it, before every town runs it.
      </p>

      {!candidate.stamp_complete && (
        <div className="mb-4 rounded-lg border border-amber-400/30 bg-amber-400/5 p-3">
          <p className="text-xs text-amber-200/90 mb-3">
            This build carries no migration stamp, so the panel cannot work out its
            schema compatibility on its own. Enter the revision its migrations
            produce and the oldest revision it can run against — without these the
            canary's migration gate is disabled.
          </p>
          <div className="grid sm:grid-cols-2 gap-3">
            <Input label="Schema revision (db_revision)" value={dbRevision}
                   onChange={(e) => setDbRevision(e.target.value)} placeholder="d4e5f6a7b8c9" />
            <Input label="Oldest supported (min_db_revision)" value={minDbRevision}
                   onChange={(e) => setMinDbRevision(e.target.value)} placeholder="c3d4e5f6a7b8" />
          </div>
        </div>
      )}

      <Textarea label="Note (recorded in the audit log)" value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="What you checked before approving" />

      <div className="flex gap-2 justify-end mt-5">
        <Button variant="secondary" onClick={() => act('reject')} isLoading={busy === 'reject'}
                leftIcon={<X className="w-4 h-4" />}>
          Decline
        </Button>
        <Button onClick={() => act('approve')} isLoading={busy === 'approve'}
                leftIcon={<ArrowRight className="w-4 h-4" />}>
          Approve and publish
        </Button>
      </div>
    </Modal>
  )
}
