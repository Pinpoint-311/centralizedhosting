import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Inbox, Check, X, Mail } from 'lucide-react'
import { api } from '../lib/api'
import type { TownRequest } from '../lib/types'
import { Badge, Button, Card, EmptyState, Spinner, timeAgo } from '../components/ui'
import { useToast } from '../components/Toast'
import { useSession } from '../lib/session'

export function Requests() {
  const toast = useToast()
  const navigate = useNavigate()
  const { can } = useSession()
  const [requests, setRequests] = useState<TownRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')

  async function load() {
    setRequests(await api.listRequests())
  }
  useEffect(() => {
    load().catch((e) => toast.push((e as Error).message, 'error')).finally(() => setLoading(false))
  }, [])

  async function approve(r: TownRequest) {
    setBusy(r.id)
    try {
      const tenant = await api.approveRequest(r.id)
      toast.push(`${r.name} approved — provision it next`)
      navigate(`/towns/${tenant.id}`)
    } catch (e) {
      toast.push((e as Error).message, 'error')
      setBusy('')
    }
  }
  async function reject(r: TownRequest) {
    setBusy(r.id)
    try {
      await api.rejectRequest(r.id)
      await load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }

  const pending = requests.filter((r) => r.status === 'pending')

  return (
    <div>
      {loading ? (
        <Spinner />
      ) : requests.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Inbox className="w-7 h-7" />}
            title="No requests"
            hint="Enable public intake (PUBLIC_REQUESTS_ENABLED) to accept self-service requests at /request."
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {requests.map((r) => (
            <Card key={r.id} className="!p-4">
              <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-white">{r.name}</span>
                    <Badge variant={r.status === 'pending' ? 'info' : r.status === 'approved' ? 'success' : 'default'}>{r.status}</Badge>
                    {r.ref_code && <code className="text-[11px] text-indigo-200">{r.ref_code}</code>}
                    {r.county && <Badge>{r.county}</Badge>}
                    {r.requested_slug && <code className="text-[11px] text-white/40">{r.requested_slug}</code>}
                  </div>
                  <div className="text-sm text-white/50 flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-0.5">
                    {r.contact_name && <span>{r.contact_name}</span>}
                    {r.contact_email && <a href={`mailto:${r.contact_email}`} className="flex items-center gap-1 hover:text-indigo-300"><Mail className="w-3.5 h-3.5" />{r.contact_email}</a>}
                    {r.contact_phone && <span>{r.contact_phone}</span>}
                    <span>{timeAgo(r.created_at)}</span>
                  </div>
                  {Object.keys(r.details || {}).length > 0 && (
                    <div className="text-xs text-white/50 flex flex-wrap gap-x-3 mt-1.5">
                      {Object.entries(r.details).map(([k, v]) => (
                        <span key={k}><span className="text-white/35">{k.replace(/_/g, ' ')}:</span> {String(v)}</span>
                      ))}
                    </div>
                  )}
                  {r.message && <p className="text-sm text-white/60 mt-2">{r.message}</p>}
                </div>
                {r.status === 'pending' && can('operator') && (
                  <div className="flex gap-2 shrink-0">
                    <Button size="sm" onClick={() => approve(r)} isLoading={busy === r.id} leftIcon={<Check className="w-4 h-4" />}>Approve</Button>
                    <Button size="sm" variant="ghost" onClick={() => reject(r)} isLoading={busy === r.id} leftIcon={<X className="w-4 h-4" />}>Reject</Button>
                  </div>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
      {pending.length === 0 && requests.length > 0 && (
        <p className="text-sm text-white/40 mt-4">No pending requests.</p>
      )}
    </div>
  )
}
