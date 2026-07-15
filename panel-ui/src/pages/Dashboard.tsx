import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Building2,
  Activity,
  GitBranch,
  AlertTriangle,
  RefreshCw,
  ArrowRight,
  Wifi,
  WifiOff,
} from 'lucide-react'
import { api } from '../lib/api'
import type { FleetSummary } from '../lib/types'
import { Button, Card, Spinner, StatusBadge, timeAgo } from '../components/ui'
import { PageHeader } from '../components/Shell'
import { useToast } from '../components/Toast'

// A single premium KPI strip — calm, government-serious, one surface instead of
// four floating tiles and two low-signal charts.
function Kpi({
  icon,
  label,
  value,
  accent,
  hint,
}: {
  icon: React.ReactNode
  label: string
  value: React.ReactNode
  accent: string
  hint?: string
}) {
  return (
    <div className="flex items-center gap-4 px-5 py-5">
      <div
        className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
        style={{ background: `${accent}1f`, color: accent }}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-[11px] font-medium uppercase tracking-wider text-white/45">{label}</div>
        <div className="text-2xl font-bold text-white leading-tight mt-0.5">{value}</div>
        {hint && <div className="text-xs text-white/40 mt-0.5">{hint}</div>}
      </div>
    </div>
  )
}

export function Dashboard() {
  const [data, setData] = useState<FleetSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const toast = useToast()

  async function load() {
    try {
      setData(await api.fleetSummary())
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const timer = setInterval(() => api.fleetSummary().then(setData).catch(() => {}), 30000)
    return () => clearInterval(timer)
  }, [])

  async function refresh() {
    setRefreshing(true)
    try {
      const r = await api.fleetRefresh()
      toast.push(`Polled ${r.polled} town(s) — ${r.reachable} reachable`)
      await load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setRefreshing(false)
    }
  }

  if (loading) return <Spinner />
  if (!data) return null

  const active = data.status_counts.active || 0

  return (
    <div>
      <PageHeader
        title="Program Overview"
        subtitle="Every municipality you host, at a glance — metadata only."
        actions={
          <Button
            variant="secondary"
            onClick={refresh}
            isLoading={refreshing}
            leftIcon={<RefreshCw className="w-4 h-4" />}
          >
            Poll telemetry
          </Button>
        }
      />

      {/* One premium surface with the four numbers that matter. */}
      <div className="premium-card mb-6">
        <div className="grid grid-cols-2 lg:grid-cols-4 divide-y divide-x divide-white/10 lg:divide-y-0 [&>*]:min-w-0">
          <Kpi
            icon={<Building2 className="w-5 h-5" />}
            label="Municipalities"
            value={data.tenants_total}
            accent="#818cf8"
            hint="hosted on this control plane"
          />
          <Kpi
            icon={<Activity className="w-5 h-5" />}
            label="Active"
            value={active}
            accent="#22c55e"
            hint={`${data.tenants_total - active} not active`}
          />
          <Kpi
            icon={<AlertTriangle className="w-5 h-5" />}
            label="Version drift"
            value={data.drifted}
            accent={data.drifted ? '#f59e0b' : '#22c55e'}
            hint={data.drifted ? 'behind latest release' : 'all up to date'}
          />
          <Kpi
            icon={<GitBranch className="w-5 h-5" />}
            label="Latest release"
            value={<span className="text-xl">{data.latest_release || '—'}</span>}
            accent="#38bdf8"
            hint="published version"
          />
        </div>
      </div>

      <Card className="!p-0 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <h3 className="font-semibold text-white">Municipalities</h3>
          <Link to="/towns" className="text-sm text-indigo-300 hover:text-indigo-200 flex items-center gap-1">
            Manage all <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
        {data.towns.length === 0 ? (
          <div className="px-6 py-10 text-center text-white/50">
            No municipalities yet.{' '}
            <Link to="/towns" className="text-indigo-300 hover:text-indigo-200">
              Add your first town →
            </Link>
          </div>
        ) : (
          <div className="divide-y divide-white/5">
            {data.towns.map((t, i) => (
              <motion.div
                key={t.id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i * 0.025, 0.3) }}
              >
                <Link
                  to={`/towns/${t.id}`}
                  className="flex items-center gap-4 px-6 py-4 hover:bg-white/[0.03] transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-white truncate">{t.name}</div>
                    <div className="text-sm text-white/40 truncate">{t.host}</div>
                  </div>
                  <div className="hidden sm:block text-sm text-white/50 w-28">
                    {t.running_version || <span className="text-white/30">unknown</span>}
                    {t.drift && <span className="text-amber-300 ml-1" title="version drift">•</span>}
                  </div>
                  <div className="hidden md:flex items-center gap-1.5 text-xs text-white/40 w-24">
                    {t.reachable === null ? (
                      <span>—</span>
                    ) : t.reachable ? (
                      <>
                        <Wifi className="w-3.5 h-3.5 text-green-400" /> {timeAgo(t.last_seen)}
                      </>
                    ) : (
                      <>
                        <WifiOff className="w-3.5 h-3.5 text-red-400" /> down
                      </>
                    )}
                  </div>
                  <StatusBadge status={t.status} />
                  <ArrowRight className="w-4 h-4 text-white/30" />
                </Link>
              </motion.div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
