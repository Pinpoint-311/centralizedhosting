import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { DollarSign, Landmark, Building2, Download } from 'lucide-react'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import { api } from '../lib/api'
import type { CostSummary } from '../lib/types'
import { Card, Spinner, EmptyState } from '../components/ui'
import { PageToolbar } from '../components/Shell'
import { useToast } from '../components/Toast'

const money = (n: number) => `$${n.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`

export function Cost() {
  const toast = useToast()
  const [data, setData] = useState<CostSummary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.cost().then(setData).catch((e) => toast.push((e as Error).message, 'error')).finally(() => setLoading(false))
  }, [])

  function exportCsv() {
    if (!data) return
    const rows = [['municipality', 'slug', 'state_borne', 'town_borne', 'total']]
    data.towns.forEach((t) => rows.push([t.name, t.slug, String(t.state_borne), String(t.town_borne), String(t.total)]))
    const blob = new Blob([rows.map((r) => r.map((c) => `"${c}"`).join(',')).join('\n')], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'pinpoint311-chargeback.csv'
    a.click()
  }

  if (loading) return <Spinner />
  if (!data) return null

  const split = [
    { name: 'State-borne', value: data.state_borne, color: '#818cf8' },
    { name: 'Town-borne', value: data.town_borne, color: '#22c55e' },
  ].filter((s) => s.value > 0)

  return (
    <div>
      <PageToolbar>
        <button onClick={exportCsv} className="inline-flex items-center gap-2 px-4 py-2.5 text-sm rounded-xl bg-white/10 hover:bg-white/20 border border-white/20 text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400">
          <Download className="w-4 h-4" /> Export CSV
        </button>
      </PageToolbar>

      {data.fleet_total === 0 ? (
        <Card>
          <EmptyState icon={<DollarSign className="w-7 h-7" />} title="No cost data yet" hint="Poll telemetry on the overview to collect usage." />
        </Card>
      ) : (
        <>
          <div className="grid sm:grid-cols-3 gap-4 mb-6">
            <Card className="!p-5">
              <div className="text-sm text-white/50">Fleet total (period)</div>
              <div className="text-3xl font-bold text-white mt-1">{money(data.fleet_total)}</div>
            </Card>
            <Card className="!p-5">
              <div className="flex items-center gap-2 text-sm text-indigo-200"><Landmark className="w-4 h-4" /> State-borne</div>
              <div className="text-3xl font-bold text-white mt-1">{money(data.state_borne)}</div>
            </Card>
            <Card className="!p-5">
              <div className="flex items-center gap-2 text-sm text-green-200"><Building2 className="w-4 h-4" /> Town-borne</div>
              <div className="text-3xl font-bold text-white mt-1">{money(data.town_borne)}</div>
            </Card>
          </div>

          <div className="grid lg:grid-cols-[20rem_1fr] gap-4">
            <Card>
              <h3 className="font-semibold text-white mb-3">Who pays</h3>
              <ResponsiveContainer width="100%" height={180}>
                <PieChart>
                  <Pie data={split} dataKey="value" nameKey="name" innerRadius={45} outerRadius={72} paddingAngle={2}>
                    {split.map((s) => <Cell key={s.name} fill={s.color} />)}
                  </Pie>
                  <Tooltip formatter={(v: number) => money(v)} contentStyle={{ background: '#1e1b4b', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 12 }} />
                </PieChart>
              </ResponsiveContainer>
              <div className="mt-3 space-y-1.5">
                {Object.entries(data.by_service).map(([svc, v]) => (
                  <div key={svc} className="flex justify-between text-sm">
                    <span className="text-white/60 capitalize">{svc}</span>
                    <span className="text-white">{money(v)}</span>
                  </div>
                ))}
              </div>
            </Card>

            <Card className="!p-0 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-white/40 border-b border-white/10">
                      <th className="px-5 py-3 font-medium">Municipality</th>
                      <th className="px-4 py-3 font-medium text-right">State-borne</th>
                      <th className="px-4 py-3 font-medium text-right">Town-borne</th>
                      <th className="px-5 py-3 font-medium text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {data.towns.map((t) => (
                      <tr key={t.id} className="hover:bg-white/[0.03]">
                        <td className="px-5 py-3">
                          <Link to={`/towns/${t.id}`} className="text-white hover:text-indigo-300">{t.name}</Link>
                        </td>
                        <td className="px-4 py-3 text-right text-indigo-200">{money(t.state_borne)}</td>
                        <td className="px-4 py-3 text-right text-green-200">{money(t.town_borne)}</td>
                        <td className="px-5 py-3 text-right text-white font-medium">{money(t.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
          <p className="text-xs text-white/40 mt-4">{data.note}</p>
        </>
      )}
    </div>
  )
}
