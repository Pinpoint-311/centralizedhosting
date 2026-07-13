import { useEffect, useState } from 'react'
import { Rocket, Plus, GitBranch, ChevronRight, PlayCircle, Undo2, Check } from 'lucide-react'
import { api } from '../lib/api'
import type { Release, Rollout } from '../lib/types'
import { Badge, Button, Card, EmptyState, Input, Modal, Spinner, Textarea, timeAgo } from '../components/ui'
import { PageHeader } from '../components/Shell'
import { useToast } from '../components/Toast'

const ROLLOUT_VARIANT: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'default'> = {
  completed: 'success',
  canary_passed: 'info',
  canary: 'warning',
  promoting: 'warning',
  pending: 'default',
  rolled_back: 'danger',
  failed: 'danger',
}

export function Releases() {
  const toast = useToast()
  const [releases, setReleases] = useState<Release[]>([])
  const [rollouts, setRollouts] = useState<Rollout[]>([])
  const [loading, setLoading] = useState(true)
  const [showPublish, setShowPublish] = useState(false)
  const [busy, setBusy] = useState('')

  async function load() {
    const [r, ro] = await Promise.all([api.listReleases(), api.listRollouts()])
    setReleases(r)
    setRollouts(ro)
  }
  useEffect(() => {
    load()
      .catch((e) => toast.push((e as Error).message, 'error'))
      .finally(() => setLoading(false))
  }, [])

  async function startRollout(releaseId: string) {
    setBusy(releaseId)
    try {
      const r = await api.startRollout({ release_id: releaseId })
      toast.push(`Canary ${r.status.replace('_', ' ')}`)
      await load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }
  async function promote(id: string) {
    setBusy(id)
    try {
      await api.promoteRollout(id)
      toast.push('Rollout promoted to all municipalities')
      await load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }
  async function rollback(id: string) {
    setBusy(id)
    try {
      await api.rollbackRollout(id)
      toast.push('Rolled back')
      await load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }

  if (loading) return <Spinner />

  return (
    <div>
      <PageHeader
        title="Releases"
        subtitle="Publish app versions and roll them out to every municipality with a canary + automatic rollback."
        actions={
          <Button onClick={() => setShowPublish(true)} leftIcon={<Plus className="w-4 h-4" />}>
            Publish release
          </Button>
        }
      />

      <div className="grid lg:grid-cols-2 gap-6">
        <div>
          <h3 className="font-semibold text-white mb-3">Published versions</h3>
          {releases.length === 0 ? (
            <Card>
              <EmptyState icon={<GitBranch className="w-7 h-7" />} title="No releases published" hint="Publish a versioned image to roll it out." />
            </Card>
          ) : (
            <div className="space-y-3">
              {releases.map((r) => (
                <Card key={r.id} className="!p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-white">v{r.version}</span>
                        {r.db_revision && <Badge>db {r.db_revision.slice(0, 8)}</Badge>}
                      </div>
                      <div className="text-xs text-white/40 mt-1">{timeAgo(r.published_at)}{r.notes ? ` · ${r.notes}` : ''}</div>
                    </div>
                    <Button size="sm" variant="secondary" onClick={() => startRollout(r.id)} isLoading={busy === r.id} leftIcon={<Rocket className="w-4 h-4" />}>
                      Roll out
                    </Button>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>

        <div>
          <h3 className="font-semibold text-white mb-3">Rollouts</h3>
          {rollouts.length === 0 ? (
            <Card>
              <EmptyState icon={<Rocket className="w-7 h-7" />} title="No rollouts yet" hint="Start one from a published release." />
            </Card>
          ) : (
            <div className="space-y-3">
              {rollouts.map((ro) => {
                const version = releases.find((r) => r.id === ro.release_id)?.version || ro.release_id.slice(0, 8)
                const healthy = ro.steps.filter((s) => s.status === 'healthy' || s.status === 'unverified').length
                return (
                  <Card key={ro.id} className="!p-4">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-white">v{version}</span>
                        <Badge variant={ROLLOUT_VARIANT[ro.status] || 'default'}>{ro.status.replace('_', ' ')}</Badge>
                      </div>
                      <span className="text-xs text-white/40">{timeAgo(ro.created_at)}</span>
                    </div>
                    <div className="text-sm text-white/50 mb-3">
                      {healthy}/{ro.steps.length} towns upgraded · canary {ro.canary_count}
                    </div>
                    {ro.error && <p className="text-red-300 text-sm mb-3">{ro.error}</p>}
                    <div className="flex gap-2">
                      {ro.status === 'canary_passed' && (
                        <Button size="sm" onClick={() => promote(ro.id)} isLoading={busy === ro.id} leftIcon={<PlayCircle className="w-4 h-4" />}>
                          Promote to all
                        </Button>
                      )}
                      {['canary_passed', 'completed', 'promoting'].includes(ro.status) && (
                        <Button size="sm" variant="secondary" onClick={() => rollback(ro.id)} isLoading={busy === ro.id} leftIcon={<Undo2 className="w-4 h-4" />}>
                          Roll back
                        </Button>
                      )}
                      {ro.status === 'completed' && (
                        <span className="inline-flex items-center gap-1 text-sm text-green-300">
                          <Check className="w-4 h-4" /> All towns on v{version}
                        </span>
                      )}
                    </div>
                  </Card>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {showPublish && (
        <PublishModal
          onClose={() => setShowPublish(false)}
          onDone={() => {
            setShowPublish(false)
            load()
          }}
        />
      )}
    </div>
  )
}

function PublishModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const toast = useToast()
  const [f, setF] = useState({ version: '', db_revision: '', min_db_revision: '', notes: '' })
  const [saving, setSaving] = useState(false)
  function set(k: keyof typeof f, v: string) {
    setF((s) => ({ ...s, [k]: v }))
  }
  async function publish() {
    setSaving(true)
    try {
      await api.publishRelease({
        version: f.version.trim(),
        db_revision: f.db_revision || null,
        min_db_revision: f.min_db_revision || null,
        notes: f.notes || null,
      })
      toast.push(`Release ${f.version} published`)
      onDone()
    } catch (e) {
      toast.push((e as Error).message, 'error')
      setSaving(false)
    }
  }
  return (
    <Modal open onClose={onClose} title="Publish a release">
      <div className="space-y-4">
        <Input label="Version" required placeholder="1.5.0" value={f.version} onChange={(e) => set('version', e.target.value)} autoFocus />
        <div className="grid grid-cols-2 gap-4">
          <Input label="DB revision" placeholder="alembic head" value={f.db_revision} onChange={(e) => set('db_revision', e.target.value)} helperText="What this build's migrations produce." />
          <Input label="Min DB revision" placeholder="oldest compatible" value={f.min_db_revision} onChange={(e) => set('min_db_revision', e.target.value)} helperText="Expand/contract floor." />
        </div>
        <Textarea label="Release notes" value={f.notes} onChange={(e) => set('notes', e.target.value)} />
      </div>
      <div className="flex justify-end gap-2 mt-6">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={publish} isLoading={saving} disabled={!f.version.trim()} leftIcon={<ChevronRight className="w-4 h-4" />}>
          Publish
        </Button>
      </div>
    </Modal>
  )
}
