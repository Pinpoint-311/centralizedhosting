import { useEffect, useState } from 'react'
import { Activity, CheckCircle, XCircle, RefreshCw, Database, KeyRound, ScrollText } from 'lucide-react'
import { api } from '../../lib/api'
import type { SystemHealth as Health } from '../../lib/types'
import { Badge, Button, Card, Spinner } from '../../components/ui'
import { useToast } from '../../components/Toast'

const CHECK_ICON: Record<string, typeof Database> = {
  database: Database,
  secret_encryption: KeyRound,
  audit_chain: ScrollText,
}

export function SystemHealth() {
  const toast = useToast()
  const [data, setData] = useState<Health | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  async function load(spin = false) {
    if (spin) setRefreshing(true)
    try {
      setData(await api.systemHealth())
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
