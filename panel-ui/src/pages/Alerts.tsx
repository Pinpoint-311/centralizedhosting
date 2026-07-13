import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { BellRing, RefreshCw, Check, AlertTriangle, WifiOff, GitBranch } from 'lucide-react'
import { api } from '../lib/api'
import type { Alert } from '../lib/types'
import { Badge, Button, Card, EmptyState, Spinner, timeAgo } from '../components/ui'
import { PageHeader } from '../components/Shell'
import { useToast } from '../components/Toast'
import { useSession } from '../lib/session'

const KIND_ICON: Record<string, React.ReactNode> = {
  down: <WifiOff className="w-4 h-4" />,
  drift: <GitBranch className="w-4 h-4" />,
}

export function Alerts() {
  const toast = useToast()
  const { can } = useSession()
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [openOnly, setOpenOnly] = useState(true)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')

  async function load() {
    setAlerts(await api.alerts(openOnly))
  }
  useEffect(() => {
    setLoading(true)
    load().catch((e) => toast.push((e as Error).message, 'error')).finally(() => setLoading(false))
  }, [openOnly])

  async function evaluate() {
    setBusy('eval')
    try {
      const r = await api.evaluateAlerts()
      toast.push(r.new_alerts ? `${r.new_alerts} new alert(s)` : 'No new alerts')
      await load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }
  async function ack(id: string) {
    setBusy(id)
    try {
      await api.ackAlert(id)
      await load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }

  return (
    <div>
      <PageHeader
        title="Alerts"
        subtitle="Fleet monitoring — towns down, version drift, and more."
        actions={
          can('operator') && (
            <Button variant="secondary" onClick={evaluate} isLoading={busy === 'eval'} leftIcon={<RefreshCw className="w-4 h-4" />}>
              Evaluate now
            </Button>
          )
        }
      />
      <div className="flex gap-2 mb-4">
        {[{ v: true, l: 'Open' }, { v: false, l: 'All' }].map((o) => (
          <button
            key={o.l}
            onClick={() => setOpenOnly(o.v)}
            className={`px-3 py-1.5 text-sm rounded-lg ${openOnly === o.v ? 'bg-white/15 text-white' : 'text-white/50 hover:text-white'}`}
          >
            {o.l}
          </button>
        ))}
      </div>

      {loading ? (
        <Spinner />
      ) : alerts.length === 0 ? (
        <Card><EmptyState icon={<BellRing className="w-7 h-7" />} title={openOnly ? 'No open alerts' : 'No alerts'} hint="All quiet across the fleet." /></Card>
      ) : (
        <div className="space-y-2">
          {alerts.map((a) => (
            <Card key={a.id} className="!p-4">
              <div className="flex items-center gap-3">
                <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${a.severity === 'critical' ? 'bg-red-500/20 text-red-300' : 'bg-amber-500/20 text-amber-300'}`}>
                  {KIND_ICON[a.kind] || <AlertTriangle className="w-4 h-4" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-white">{a.message}</div>
                  <div className="text-xs text-white/40 flex items-center gap-2">
                    <Badge variant={a.severity === 'critical' ? 'danger' : 'warning'}>{a.kind}</Badge>
                    {timeAgo(a.created_at)}
                    {a.tenant_slug && (
                      <Link to={`/towns/${a.tenant_id}`} className="text-indigo-300 hover:text-indigo-200">{a.tenant_slug}</Link>
                    )}
                    {a.acknowledged_at && <span className="text-green-300">acked by {a.acknowledged_by}</span>}
                  </div>
                </div>
                {!a.acknowledged_at && can('operator') && (
                  <Button size="sm" variant="secondary" onClick={() => ack(a.id)} isLoading={busy === a.id} leftIcon={<Check className="w-4 h-4" />}>
                    Acknowledge
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
