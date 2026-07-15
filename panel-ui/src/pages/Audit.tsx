import { useEffect, useState } from 'react'
import { ScrollText, RefreshCw } from 'lucide-react'
import { api } from '../lib/api'
import type { AuditEntry } from '../lib/types'
import { Badge, Button, Card, EmptyState, Spinner, timeAgo } from '../components/ui'
import { PageToolbar } from '../components/Shell'
import { useToast } from '../components/Toast'

function actionVariant(action: string): 'success' | 'warning' | 'danger' | 'info' | 'default' {
  if (action.includes('failed') || action.includes('rolled_back') || action.includes('decommission')) return 'danger'
  if (action.includes('breakglass') || action.includes('suspend')) return 'warning'
  if (action.includes('succeeded') || action.includes('completed') || action.includes('created')) return 'success'
  return 'info'
}

export function Audit() {
  const toast = useToast()
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)

  async function load() {
    try {
      setEntries(await api.audit('?limit=200'))
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  return (
    <div>
      <PageToolbar>
        <Button variant="secondary" onClick={load} leftIcon={<RefreshCw className="w-4 h-4" />}>
          Refresh
        </Button>
      </PageToolbar>
      {loading ? (
        <Spinner />
      ) : entries.length === 0 ? (
        <Card>
          <EmptyState icon={<ScrollText className="w-7 h-7" />} title="No audit entries yet" />
        </Card>
      ) : (
        <Card className="!p-0 overflow-hidden">
          <div className="divide-y divide-white/5">
            {entries.map((e) => (
              <div key={e.id} className="flex items-start gap-4 px-5 py-3.5">
                <div className="w-32 shrink-0 text-xs text-white/40 pt-0.5">{timeAgo(e.created_at)}</div>
                <div className="shrink-0">
                  <Badge variant={actionVariant(e.action)}>{e.action}</Badge>
                </div>
                <div className="flex-1 min-w-0 text-sm">
                  <span className="text-white/70">{e.actor}</span>
                  {Object.keys(e.detail || {}).length > 0 && (
                    <span className="text-white/40 ml-2 break-all">
                      {Object.entries(e.detail)
                        .filter(([k]) => k !== 'crypto_shred')
                        .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`)
                        .join('  ')}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
