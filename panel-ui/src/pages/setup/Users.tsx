import { useEffect, useState } from 'react'
import { Users as UsersIcon, UserPlus, UserCircle, Trash2, KeyRound, ShieldCheck } from 'lucide-react'
import { api } from '../../lib/api'
import type { PanelUser } from '../../lib/types'
import { Badge, Button, Card, Input, Modal, Spinner, timeAgo } from '../../components/ui'
import { useToast } from '../../components/Toast'

const AUTH_BADGE: Record<string, { label: string; variant: 'success' | 'info' | 'warning' }> = {
  sso: { label: 'SSO', variant: 'success' },
  password: { label: 'Password', variant: 'info' },
  invited: { label: 'Invited', variant: 'warning' },
}

export function Users() {
  const toast = useToast()
  const [users, setUsers] = useState<PanelUser[] | null>(null)
  const [me, setMe] = useState<PanelUser | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [pwFor, setPwFor] = useState<PanelUser | null>(null)
  const [form, setForm] = useState({ username: '', email: '', full_name: '' })
  const [pw, setPw] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    try {
      setUsers(await api.listUsers())
    } catch (e) {
      toast.push((e as Error).message, 'error')
    }
  }
  useEffect(() => {
    load()
    api.me().then(setMe).catch(() => {})
  }, [])

  async function create() {
    if (!form.username.trim() || !form.email.trim()) return
    setBusy(true)
    try {
      await api.createUser({ username: form.username.trim(), email: form.email.trim(), full_name: form.full_name.trim() || undefined })
      toast.push('Operator added — they sign in via SSO (matched by email) or a password you set')
      setShowAdd(false)
      setForm({ username: '', email: '', full_name: '' })
      load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  async function toggleActive(u: PanelUser) {
    try {
      await api.updateUser(u.id as number, { is_active: !u.is_active })
      load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    }
  }

  async function remove(u: PanelUser) {
    if (!window.confirm(`Remove ${u.username}? They'll lose access immediately.`)) return
    try {
      await api.deleteUser(u.id as number)
      toast.push(`Removed ${u.username}`)
      load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    }
  }

  async function savePassword() {
    if (!pwFor || pw.length < 10) return
    setBusy(true)
    try {
      await api.setUserPassword(pwFor.id as number, pw)
      toast.push(`Password set for ${pwFor.username}`)
      setPwFor(null)
      setPw('')
      load()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  if (!users) return <Spinner />

  const active = users.filter((u) => u.is_active).length

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white flex items-center gap-2">
            <UsersIcon className="w-6 h-6" /> Users
          </h1>
          <p className="text-white/50 text-sm mt-1">
            Operators with access to this control plane. Everyone here has full access — add or remove
            people to grant or revoke it. They sign in with SSO (matched by email) or a password.
          </p>
        </div>
        <Button className="w-full sm:w-auto" onClick={() => setShowAdd(true)} leftIcon={<UserPlus className="w-4 h-4" />}>
          Add operator
        </Button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        <Card className="!p-5">
          <div className="text-3xl font-bold text-white">{users.length}</div>
          <div className="text-xs text-white/40 uppercase tracking-wide mt-1">Operators</div>
        </Card>
        <Card className="!p-5">
          <div className="text-3xl font-bold text-green-300">{active}</div>
          <div className="text-xs text-white/40 uppercase tracking-wide mt-1">Active</div>
        </Card>
        <Card className="!p-5">
          <div className="text-3xl font-bold text-white/80">{users.filter((u) => u.auth === 'sso').length}</div>
          <div className="text-xs text-white/40 uppercase tracking-wide mt-1">Via SSO</div>
        </Card>
      </div>

      <Card className="!p-0 overflow-hidden">
        {users.length === 0 ? (
          <p className="text-sm text-white/40 p-6">No operators yet. Add the first one above.</p>
        ) : (
          <div className="divide-y divide-white/5">
            {users.map((u) => {
              const badge = AUTH_BADGE[u.auth || 'invited']
              const isSelf = me?.username === u.username
              return (
                <div key={u.id} className="flex items-center gap-3 px-5 py-3.5">
                  <div className="w-9 h-9 rounded-full bg-primary-500/15 text-primary-300 flex items-center justify-center shrink-0">
                    <UserCircle className="w-5 h-5" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-white truncate">
                      {u.full_name || u.username}
                      {isSelf && <span className="text-white/40 text-xs ml-2">(you)</span>}
                    </div>
                    <div className="text-xs text-white/40 truncate">@{u.username} · {u.email}</div>
                  </div>
                  <Badge variant={badge.variant}>{badge.label}</Badge>
                  <button
                    onClick={() => toggleActive(u)}
                    className={`text-xs px-2 py-1 rounded-lg border ${u.is_active ? 'border-green-400/30 text-green-300' : 'border-white/15 text-white/40'}`}
                    title={u.is_active ? 'Active — click to disable' : 'Disabled — click to enable'}
                  >
                    {u.is_active ? 'Active' : 'Disabled'}
                  </button>
                  <div className="text-xs text-white/30 w-20 text-right shrink-0 hidden md:block">
                    {u.last_login_at ? timeAgo(u.last_login_at) : 'never'}
                  </div>
                  <button onClick={() => setPwFor(u)} className="text-white/40 hover:text-white shrink-0" title="Set password" aria-label={`Set password for ${u.username}`}>
                    <KeyRound className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => remove(u)}
                    disabled={isSelf}
                    className="text-white/40 hover:text-red-300 shrink-0 disabled:opacity-30 disabled:hover:text-white/40"
                    title={isSelf ? "You can't remove yourself" : 'Remove operator'}
                    aria-label={`Remove ${u.username}`}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </Card>

      <div className="flex items-start gap-2 p-3 rounded-lg bg-blue-500/10 border border-blue-500/20">
        <ShieldCheck className="w-4 h-4 text-blue-300 shrink-0 mt-0.5" />
        <p className="text-xs text-blue-100/70">
          Single sign-on authenticates identity and matches the operator to their row here by email —
          nobody outside this list can get in. Configure SSO under Setup &amp; Integration.
        </p>
      </div>

      <Modal open={showAdd} onClose={() => setShowAdd(false)} title="Add operator">
        <div className="space-y-4">
          <Input label="Username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="e.g. jsmith" />
          <Input label="Email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="jsmith@yourprogram.gov" helperText="SSO matches the operator to this address." />
          <Input label="Full name (optional)" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setShowAdd(false)}>Cancel</Button>
            <Button onClick={create} isLoading={busy} leftIcon={<UserPlus className="w-4 h-4" />}>Add operator</Button>
          </div>
        </div>
      </Modal>

      <Modal open={!!pwFor} onClose={() => { setPwFor(null); setPw('') }} title={`Set password — ${pwFor?.username || ''}`}>
        <div className="space-y-4">
          <p className="text-sm text-white/50">
            Give this operator a password so they can sign in without SSO (first admin / break-fix).
          </p>
          <Input label="New password" type="password" value={pw} onChange={(e) => setPw(e.target.value)} helperText="At least 10 characters." />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => { setPwFor(null); setPw('') }}>Cancel</Button>
            <Button onClick={savePassword} isLoading={busy} disabled={pw.length < 10} leftIcon={<KeyRound className="w-4 h-4" />}>Set password</Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
