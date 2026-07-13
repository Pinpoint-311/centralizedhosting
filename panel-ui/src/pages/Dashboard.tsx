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
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
} from 'recharts'
import { api } from '../lib/api'
import type { FleetSummary } from '../lib/types'
import { Button, Card, Spinner, StatusBadge, timeAgo } from '../components/ui'
import { PageHeader } from '../components/Shell'
import { useToast } from '../components/Toast'

const STATUS_COLORS: Record<string, string> = {
  active: '#22c55e',
  pending: '#3b82f6',
  provisioning: '#f59e0b',
  suspended: '#f59e0b',
  failed: '#ef4444',
  decommissioned: '#6b7280',
}

function StatTile({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode
  label: string
  value: React.ReactNode
  accent: string
}) {
  return (
    <Card className="!p-5">
      <div className="flex items-center gap-4">
        <div
          className="w-12 h-12 rounded-xl flex items-center justify-center shrink-0"
          style={{ background: `${accent}22`, color: accent }}
        >
          {icon}
        </div>
        <div className="min-w-0">
          <div className="text-2xl font-bold text-white leading-tight">{value}</div>
          <div className="text-sm text-white/50">{label}</div>
        </div>
      </div>
    </Card>
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

  const statusData = Object.entries(data.status_counts).map(([name, value]) => ({ name, value }))
  const versionData = Object.entries(data.version_counts).map(([name, value]) => ({
    name: name === 'unknown' ? 'unknown' : name,
    value,
  }))

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

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatTile
          icon={<Building2 className="w-6 h-6" />}
          label="Municipalities"
          value={data.tenants_total}
          accent="#818cf8"
        />
        <StatTile
          icon={<Activity className="w-6 h-6" />}
          label="Active"
          value={data.status_counts.active || 0}
          accent="#22c55e"
        />
        <StatTile
          icon={<GitBranch className="w-6 h-6" />}
          label="Latest release"
          value={<span className="text-lg">{data.latest_release || '—'}</span>}
          accent="#38bdf8"
        />
        <StatTile
          icon={<AlertTriangle className="w-6 h-6" />}
          label="Version drift"
          value={data.drifted}
          accent={data.drifted ? '#f59e0b' : '#22c55e'}
        />
      </div>

      {data.tenants_total > 0 && (
        <div className="grid lg:grid-cols-2 gap-4 mb-6">
          <Card>
            <h3 className="font-semibold text-white mb-4">Status distribution</h3>
            <div className="flex items-center gap-6">
              <ResponsiveContainer width={160} height={160}>
                <PieChart>
                  <Pie data={statusData} dataKey="value" nameKey="name" innerRadius={45} outerRadius={70} paddingAngle={2}>
                    {statusData.map((s) => (
                      <Cell key={s.name} fill={STATUS_COLORS[s.name] || '#6b7280'} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: '#1e1b4b', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 12 }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-1.5">
                {statusData.map((s) => (
                  <div key={s.name} className="flex items-center gap-2 text-sm">
                    <span className="w-3 h-3 rounded-full" style={{ background: STATUS_COLORS[s.name] || '#6b7280' }} />
                    <span className="text-white/70 capitalize">{s.name}</span>
                    <span className="text-white/40">· {s.value}</span>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          <Card>
            <h3 className="font-semibold text-white mb-4">Running versions</h3>
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={versionData}>
                <XAxis dataKey="name" tick={{ fill: 'rgba(255,255,255,0.6)', fontSize: 12 }} />
                <YAxis allowDecimals={false} tick={{ fill: 'rgba(255,255,255,0.6)', fontSize: 12 }} />
                <Tooltip
                  cursor={{ fill: 'rgba(255,255,255,0.05)' }}
                  contentStyle={{ background: '#1e1b4b', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 12 }}
                />
                <Bar dataKey="value" fill="#818cf8" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </div>
      )}

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
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.03 }}
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
