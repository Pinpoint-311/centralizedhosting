import { useEffect, useState } from 'react'
import { BarChart3, ShieldCheck, Info } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../lib/api'
import type { Analytics as AnalyticsData } from '../lib/types'
import { getRegionLabel, getRegionLabelPlural } from '../lib/config'
import { Card, Spinner, EmptyState } from '../components/ui'
import { useToast } from '../components/Toast'

export function Analytics() {
  const toast = useToast()
  const regionLabel = getRegionLabel()
  const regionPlural = getRegionLabelPlural()
  const [data, setData] = useState<AnalyticsData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.analytics().then(setData).catch((e) => toast.push((e as Error).message, 'error')).finally(() => setLoading(false))
  }, [])

  if (loading) return <Spinner />
  if (!data) return null

  const regionKey = regionLabel.toLowerCase()
  const catData = Object.entries(data.by_canonical_category)
    .filter(([code]) => code !== 'other')
    .slice(0, 10)
    .map(([code, count]) => ({ name: code.replace(/_/g, ' '), count }))

  return (
    <div>

      <div className="flex items-start gap-3 mb-6 p-4 rounded-xl bg-indigo-500/10 border border-indigo-500/25">
        <ShieldCheck className="w-5 h-5 text-indigo-300 shrink-0 mt-0.5" />
        <p className="text-sm text-indigo-100/80">
          <b>Privacy wall.</b> These figures are aggregated to the {regionLabel.toLowerCase()} level
          only. No individual municipality's numbers are shown here or anywhere in this panel.{' '}
          {regionPlural} with fewer than {data.min_cell} towns are combined or withheld
          so they can't be traced to one town.
          {data.towns_withheld_for_privacy > 0 && (
            <> {data.towns_withheld_for_privacy} town(s) are currently withheld for this reason.</>
          )}
        </p>
      </div>

      {data.program_total_requests === 0 ? (
        <Card><EmptyState icon={<BarChart3 className="w-7 h-7" />} title="No request data yet" hint="Aggregates populate as towns report telemetry." /></Card>
      ) : (
        <>
          <div className="grid sm:grid-cols-3 gap-4 mb-6">
            <Card className="!p-5">
              <div className="text-sm text-white/50">Program total requests</div>
              <div className="text-3xl font-bold text-white mt-1">{data.program_total_requests.toLocaleString()}</div>
            </Card>
            <Card className="!p-5">
              <div className="text-sm text-white/50">{regionPlural} reported</div>
              <div className="text-3xl font-bold text-white mt-1">{data.regions.length}</div>
            </Card>
            <Card className="!p-5">
              <div className="text-sm text-white/50">Unmapped categories</div>
              <div className="text-3xl font-bold text-white mt-1">{data.unmapped_requests.toLocaleString()}</div>
              <div className="text-xs text-white/40 mt-1">Map local categories to improve breakdowns</div>
            </Card>
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <Card>
              <h3 className="font-semibold text-white mb-4">Top request categories (program-wide)</h3>
              {catData.length === 0 ? (
                <p className="text-white/40 text-sm">No mapped categories yet.</p>
              ) : (
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={catData} layout="vertical" margin={{ left: 40 }}>
                    <XAxis type="number" tick={{ fill: 'rgba(255,255,255,0.6)', fontSize: 12 }} />
                    <YAxis type="category" dataKey="name" width={110} tick={{ fill: 'rgba(255,255,255,0.6)', fontSize: 11 }} />
                    <Tooltip cursor={{ fill: 'rgba(255,255,255,0.05)' }} contentStyle={{ background: '#1e1b4b', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 12 }} />
                    <Bar dataKey="count" fill="#818cf8" radius={[0, 6, 6, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Card>

            <Card className="!p-0 overflow-hidden">
              <div className="px-5 py-4 border-b border-white/10">
                <h3 className="font-semibold text-white">By {regionLabel.toLowerCase()}</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-white/40 border-b border-white/10">
                      <th className="px-5 py-3 font-medium">{regionLabel}</th>
                      <th className="px-4 py-3 font-medium text-right">Towns</th>
                      <th className="px-4 py-3 font-medium text-right">Requests</th>
                      <th className="px-4 py-3 font-medium text-right">Close rate</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {data.regions.map((r, i) => (
                      <tr key={i} className="hover:bg-white/[0.03]">
                        <td className="px-5 py-3 text-white">{String(r[regionKey])}</td>
                        <td className="px-4 py-3 text-right text-white/60">{String(r.towns)}</td>
                        <td className="px-4 py-3 text-right text-white">{Number(r.total_requests).toLocaleString()}</td>
                        <td className="px-4 py-3 text-right text-white/60">{r.close_rate_percent != null ? `${r.close_rate_percent}%` : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
          <p className="text-xs text-white/40 mt-4 flex items-center gap-1.5"><Info className="w-3.5 h-3.5" /> {data.note}</p>
        </>
      )}
    </div>
  )
}
