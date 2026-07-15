import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, Download } from 'lucide-react'
import { api } from '../lib/api'
import type { SlaSummary } from '../lib/types'
import { Card, Spinner, EmptyState, Select } from '../components/ui'
import { PageToolbar } from '../components/Shell'
import { useToast } from '../components/Toast'

function uptimeColor(pct: number | null) {
  if (pct == null) return '#94a3b8'
  if (pct >= 99.9) return '#22c55e'
  if (pct >= 99) return '#84cc16'
  if (pct >= 95) return '#f59e0b'
  return '#ef4444'
}

export function Sla() {
  const toast = useToast()
  const [days, setDays] = useState(30)
  const [data, setData] = useState<SlaSummary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    api.sla(days).then(setData).catch((e) => toast.push((e as Error).message, 'error')).finally(() => setLoading(false))
  }, [days])

  function exportCsv() {
    if (!data) return
    const rows = [['municipality', 'uptime_percent', 'checks', 'reachable', 'incidents']]
    data.towns.forEach((t) => rows.push([t.name || t.slug || '', String(t.uptime_percent ?? ''), String(t.checks), String(t.reachable), String(t.incidents)]))
    const blob = new Blob([rows.map((r) => r.map((c) => `"${c}"`).join(',')).join('\n')], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `pinpoint311-sla-${days}d.csv`
    a.click()
  }

  return (
    <div>
      <PageToolbar>
        <div className="w-36">
          <Select
            value={String(days)}
            onChange={(e) => setDays(Number(e.target.value))}
            options={[{ value: '7', label: 'Last 7 days' }, { value: '30', label: 'Last 30 days' }, { value: '90', label: 'Last 90 days' }]}
          />
        </div>
        <button onClick={exportCsv} className="inline-flex items-center gap-2 px-4 py-2.5 text-sm rounded-xl bg-white/10 hover:bg-white/20 border border-white/20 text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400">
          <Download className="w-4 h-4" /> Export
        </button>
      </PageToolbar>
      {loading ? (
        <Spinner />
      ) : !data || data.towns.length === 0 ? (
        <Card><EmptyState icon={<Activity className="w-7 h-7" />} title="No uptime data yet" hint="Reachability accrues as telemetry is polled." /></Card>
      ) : (
        <Card className="!p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-white/40 border-b border-white/10">
                  <th className="px-5 py-3 font-medium">Municipality</th>
                  <th className="px-4 py-3 font-medium">Uptime</th>
                  <th className="px-4 py-3 font-medium text-right">Checks</th>
                  <th className="px-4 py-3 font-medium text-right">Incidents</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {data.towns.map((t) => (
                  <tr key={t.id} className="hover:bg-white/[0.03]">
                    <td className="px-5 py-3">
                      <Link to={`/towns/${t.id}`} className="text-white hover:text-indigo-300">{t.name || t.slug}</Link>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="w-28 h-2 rounded-full bg-white/10 overflow-hidden">
                          <div className="h-full rounded-full" style={{ width: `${t.uptime_percent ?? 0}%`, background: uptimeColor(t.uptime_percent) }} />
                        </div>
                        <span className="text-white tabular-nums">{t.uptime_percent != null ? `${t.uptime_percent}%` : '—'}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right text-white/60">{t.checks}</td>
                    <td className="px-4 py-3 text-right text-white/60">{t.incidents}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
