import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { UserCircle, Users as UsersIcon, ShieldCheck } from 'lucide-react'
import { api } from '../../lib/api'
import type { Operators } from '../../lib/types'
import { Badge, Card, Spinner, timeAgo } from '../../components/ui'
import { useToast } from '../../components/Toast'

export function Users() {
  const toast = useToast()
  const [data, setData] = useState<Operators | null>(null)

  useEffect(() => {
    api.operators().then(setData).catch((e) => toast.push((e as Error).message, 'error'))
  }, [])
  if (!data) return <Spinner />

  const roleEntries = Object.entries(data.role_map)

  return (
    <div className="space-y-4">
      <Card>
        <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
          <ShieldCheck className="w-5 h-5" /> How access works
        </h3>
        <p className="text-sm text-white/50">
          The panel has <b>no user database</b> — operators authenticate through your identity
          provider and their role comes from their IdP group. Manage sign-in and the
          group&nbsp;&rarr;&nbsp;role mapping in{' '}
          <Link to="/setup/integration" className="text-indigo-300 hover:text-indigo-200">Setup &amp; Integration &rarr; Single sign-on</Link>.
          You are signed in as <b className="text-white">{data.you.actor}</b>{' '}
          <Badge variant="info">{data.you.role}</Badge>.
        </p>
      </Card>

      <Card>
        <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
          <UsersIcon className="w-5 h-5" /> Roles
        </h3>
        <p className="text-sm text-white/50 mb-4">
          Everyone who signs in without a mapped group gets{' '}
          <Badge>{data.default_role}</Badge> (DEFAULT_OPERATOR_ROLE). SSO is{' '}
          {data.sso_enabled ? <Badge variant="success">enabled</Badge> : <Badge variant="warning">not enabled</Badge>}.
        </p>
        {roleEntries.length === 0 ? (
          <p className="text-sm text-white/40">
            No group&nbsp;&rarr;&nbsp;role mappings yet. Add them under Setup &amp; Integration so IdP
            groups grant viewer / operator / approver / admin.
          </p>
        ) : (
          <div className="space-y-1.5">
            {roleEntries.map(([group, role]) => (
              <div key={group} className="flex items-center justify-between py-1.5 border-b border-white/5">
                <code className="text-sm text-white/80">{group}</code>
                <Badge variant="info">{role}</Badge>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
          <UserCircle className="w-5 h-5" /> Operators seen
        </h3>
        <p className="text-sm text-white/50 mb-4">
          Everyone who has acted on this control plane, from the audit trail — the real record of who
          did what.
        </p>
        {data.operators.length === 0 ? (
          <p className="text-sm text-white/40">No operator activity yet.</p>
        ) : (
          <div className="divide-y divide-white/5">
            {data.operators.map((o) => (
              <div key={o.actor} className="flex items-center gap-3 py-2.5">
                <div className="w-8 h-8 rounded-full bg-primary-500/15 text-primary-300 flex items-center justify-center shrink-0">
                  <UserCircle className="w-4 h-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-white truncate">{o.actor}</div>
                  <div className="text-xs text-white/40">{o.actions} action(s)</div>
                </div>
                <div className="text-xs text-white/40 shrink-0">
                  {o.last_action_at ? timeAgo(o.last_action_at) : '—'}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
