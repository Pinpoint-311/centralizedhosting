import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ShieldCheck, Check, X, Scale } from 'lucide-react'
import { api } from '../lib/api'
import type { ComplianceSummary } from '../lib/types'
import { Card, Spinner, EmptyState, Badge } from '../components/ui'
import { useToast } from '../components/Toast'

const CHECK_LABEL: Record<string, string> = {
  encryption: 'Encryption (KMS)',
  version_current: 'Version current',
  retention_set: 'Retention policy',
  mfa_required: 'MFA required',
  accessibility_statement: 'Accessibility statement',
  log_shipping: 'Central logging',
}

function scoreColor(s: number) {
  if (s >= 90) return '#22c55e'
  if (s >= 70) return '#84cc16'
  if (s >= 50) return '#f59e0b'
  return '#ef4444'
}

export function Compliance() {
  const toast = useToast()
  const [data, setData] = useState<ComplianceSummary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.compliance().then(setData).catch((e) => toast.push((e as Error).message, 'error')).finally(() => setLoading(false))
  }, [])

  if (loading) return <Spinner />
  if (!data) return null

  const checkKeys = Object.keys(CHECK_LABEL)

  return (
    <div>
      {data.total === 0 ? (
        <Card><EmptyState icon={<ShieldCheck className="w-7 h-7" />} title="No municipalities yet" /></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
            {checkKeys.map((k) => (
              <Card key={k} className="!p-4">
                <div className="text-2xl font-bold text-white">{data.passing_by_check[k] ?? 0}<span className="text-white/30 text-lg">/{data.total}</span></div>
                <div className="text-xs text-white/50 mt-1">{CHECK_LABEL[k]}</div>
              </Card>
            ))}
          </div>

          <Card className="!p-0 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-white/40 border-b border-white/10">
                    <th className="px-5 py-3 font-medium">Municipality</th>
                    <th className="px-4 py-3 font-medium">Score</th>
                    {checkKeys.map((k) => (
                      <th key={k} className="px-3 py-3 font-medium text-center text-xs">{CHECK_LABEL[k]}</th>
                    ))}
                    <th className="px-4 py-3 font-medium text-center">Legal hold</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {data.towns.map((t) => (
                    <tr key={t.id} className="hover:bg-white/[0.03]">
                      <td className="px-5 py-3">
                        <Link to={`/towns/${t.id}`} className="text-white hover:text-indigo-300">{t.name}</Link>
                        {t.county && <div className="text-xs text-white/40">{t.county}</div>}
                      </td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center gap-2">
                          <span className="w-10 h-1.5 rounded-full bg-white/10 overflow-hidden">
                            <span className="block h-full rounded-full" style={{ width: `${t.score}%`, background: scoreColor(t.score) }} />
                          </span>
                          <span className="text-white tabular-nums text-xs">{t.score}%</span>
                        </span>
                      </td>
                      {checkKeys.map((k) => (
                        <td key={k} className="px-3 py-3 text-center">
                          {t.checks[k] ? <Check className="w-4 h-4 text-green-400 mx-auto" /> : <X className="w-4 h-4 text-white/25 mx-auto" />}
                        </td>
                      ))}
                      <td className="px-4 py-3 text-center">
                        {t.legal_hold ? <Badge variant="warning"><Scale className="w-3 h-3" /> held</Badge> : <span className="text-white/25">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  )
}
