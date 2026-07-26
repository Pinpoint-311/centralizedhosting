import { useEffect, useState } from 'react'
import { Activity, CheckCircle, XCircle, RefreshCw, Database, KeyRound, ScrollText, ShieldAlert, ArrowRight } from 'lucide-react'
import { api } from '../../lib/api'
import type { SystemHealth as Health, ProactiveHealth } from '../../lib/types'
import { Badge, Button, Card, Spinner } from '../../components/ui'
import { useToast } from '../../components/Toast'

function ProactiveCard({ data }: { data: ProactiveHealth }) {
  const issues = data.checks.filter((c) => c.status === 'warning' || c.status === 'critical')
  const ok = data.overall_status === 'ok'
  const critical = data.overall_status === 'critical'
  return (
    <Card className={ok ? '' : critical ? '!border-red-500/40' : '!border-amber-500/40'}>
      <div className="flex items-center gap-3 mb-1">
        <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${ok ? 'bg-green-500/15 text-green-300' : critical ? 'bg-red-500/15 text-red-300' : 'bg-amber-500/15 text-amber-300'}`}>
          {ok ? <CheckCircle className="w-5 h-5" /> : <ShieldAlert className="w-5 h-5" />}
        </div>
        <div>
          <h3 className="font-semibold text-white">{data.summary.label}</h3>
          <p className="text-xs text-white/50">Leading-indicator checks · off-host monitoring is alerted when a check crosses a threshold.</p>
        </div>
      </div>
      {ok ? (
        <p className="text-sm text-green-300/80 mt-2">All early-warning checks passing (disk, memory, database, backups, audit chain).</p>
      ) : (
        <div className="space-y-2 mt-3">
          {issues.map((c) => (
            <div key={c.key} className={`p-3 rounded-lg border ${c.status === 'critical' ? 'bg-red-500/10 border-red-500/20' : 'bg-amber-500/10 border-amber-500/20'}`}>
              <div className="flex items-center gap-2">
                <Badge variant={c.status === 'critical' ? 'danger' : 'warning'}>{c.status}</Badge>
                <span className="text-sm text-white/80"><b>{c.label}:</b> {c.message}</span>
              </div>
              {c.action && (
                <p className="text-xs text-white/50 mt-1 flex items-center gap-1"><ArrowRight className="w-3 h-3" /> {c.action}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

const CHECK_ICON: Record<string, typeof Database> = {
  database: Database,
  secret_encryption: KeyRound,
  audit_chain: ScrollText,
}

export function SystemHealth() {
  const toast = useToast()
  const [data, setData] = useState<Health | null>(null)
  const [proactive, setProactive] = useState<ProactiveHealth | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  async function load(spin = false) {
    if (spin) setRefreshing(true)
    try {
      const [h, p] = await Promise.all([api.systemHealth(), api.systemProactive().catch(() => null)])
      setData(h)
      setProactive(p)
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setRefreshing(false)
    }
  }
  useEffect(() => { load() }, [])
  if (!data) return <Spinner />

  const allOk = Object.values(data.checks).every((c) => c.ok)

  return (
    <div className="space-y-4">
      <div className="mb-2">
        <h1 className="text-xl sm:text-2xl font-bold text-white flex items-center gap-2">
          <Activity className="w-6 h-6" /> System Health
        </h1>
        <p className="text-white/50 text-sm mt-1">Live status of the control plane itself.</p>
      </div>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`w-11 h-11 rounded-2xl flex items-center justify-center ${allOk ? 'bg-green-500/15 text-green-300' : 'bg-red-500/15 text-red-300'}`}>
            <Activity className="w-6 h-6" />
          </div>
          <div>
            <div className="text-lg font-semibold text-white">{allOk ? 'All systems operational' : 'Attention needed'}</div>
            <div className="text-sm text-white/50">Control plane v{data.version}</div>
          </div>
        </div>
        <Button variant="secondary" onClick={() => load(true)} isLoading={refreshing} leftIcon={<RefreshCw className="w-4 h-4" />}>
          Refresh
        </Button>
      </div>

      {proactive && <ProactiveCard data={proactive} />}

      <div className="grid sm:grid-cols-3 gap-4">
        {Object.entries(data.checks).map(([key, c]) => {
          const Icon = CHECK_ICON[key] || Activity
          return (
            <Card key={key} className="!p-5">
              <div className="flex items-center justify-between mb-2">
                <Icon className="w-5 h-5 text-white/40" />
                {c.ok ? <CheckCircle className="w-5 h-5 text-green-400" /> : <XCircle className="w-5 h-5 text-red-400" />}
              </div>
              <div className="text-sm font-medium text-white capitalize">{key.replace(/_/g, ' ')}</div>
              <div className="text-xs text-white/50 mt-0.5">{c.detail}</div>
            </Card>
          )
        })}
      </div>

      <div className="grid sm:grid-cols-2 gap-4">
        <Card>
          <h3 className="font-semibold text-white mb-3">Fleet</h3>
          <div className="flex gap-8">
            <div>
              <div className="text-3xl font-bold text-white">{data.fleet.total}</div>
              <div className="text-xs text-white/40 uppercase tracking-wide">Municipalities</div>
            </div>
            <div>
              <div className="text-3xl font-bold text-green-300">{data.fleet.active}</div>
              <div className="text-xs text-white/40 uppercase tracking-wide">Active</div>
            </div>
          </div>
        </Card>
        <Card>
          <h3 className="font-semibold text-white mb-3">Background loops</h3>
          <div className="space-y-1.5">
            {Object.entries(data.background_loops).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between text-sm py-1 border-b border-white/5">
                <span className="text-white/60">{k.replace(/_seconds$/, '').replace(/_/g, ' ')}</span>
                {v > 0 ? <Badge variant="success">every {v}s</Badge> : <Badge>disabled</Badge>}
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
