import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Plus, Shield, Trash2, Users, User as UserIcon, KeyRound } from 'lucide-react'
import { api } from '../../lib/api'
import type { PanelUser } from '../../lib/types'
import { Button, Input, Modal, Spinner, timeAgo } from '../../components/ui'
import { useToast } from '../../components/Toast'

/**
 * User Management — the app's AdminConsole "users" tab, ported verbatim
 * (premium stats cards, avatar monogram table, mobile card layout, empty
 * state) and pointed at the control plane's /api/users endpoints.
 *
 * One difference by design: the control plane has a single access level, so
 * there's no role picker — every operator here is an administrator. Access is
 * granted by adding someone and revoked by removing them.
 */
export function UsersPage() {
    const toast = useToast()
    const [users, setUsers] = useState<PanelUser[] | null>(null)
    const [me, setMe] = useState<PanelUser | null>(null)
    const [showUserModal, setShowUserModal] = useState(false)
    const [pwFor, setPwFor] = useState<PanelUser | null>(null)
    const [password, setPassword] = useState('')
    const [busy, setBusy] = useState(false)
    const [newUser, setNewUser] = useState({ username: '', full_name: '', email: '' })

    const load = async () => {
        try {
            setUsers(await api.listUsers())
        } catch (e: any) {
            toast.push(e?.message || 'Failed to load users', 'error')
        }
    }
    useEffect(() => {
        load()
        api.me().then(setMe).catch(() => { })
    }, [])

    const handleCreateUser = async (e: React.FormEvent) => {
        e.preventDefault()
        setBusy(true)
        try {
            await api.createUser({
                username: newUser.username.trim(),
                email: newUser.email.trim(),
                full_name: newUser.full_name.trim() || undefined,
            })
            setShowUserModal(false)
            setNewUser({ username: '', full_name: '', email: '' })
            load()
        } catch (err: any) {
            toast.push(err?.message || 'Failed to create user', 'error')
        } finally {
            setBusy(false)
        }
    }

    const handleDeleteUser = async (userId: number) => {
        const u = users?.find(x => x.id === userId)
        if (!window.confirm(`Remove ${u?.username}? They'll lose access immediately.`)) return
        try {
            await api.deleteUser(userId)
            load()
        } catch (err: any) {
            toast.push(err?.message || 'Failed to delete user', 'error')
        }
    }

    const handleSetPassword = async () => {
        if (!pwFor || password.length < 10) return
        setBusy(true)
        try {
            await api.resetUserPassword(pwFor.id as number, password)
            toast.push(`Password set for ${pwFor.username}`)
            setPwFor(null)
            setPassword('')
            load()
        } catch (err: any) {
            toast.push(err?.message || 'Failed to set password', 'error')
        } finally {
            setBusy(false)
        }
    }

    if (!users) return <Spinner />

    return (
        <div className="space-y-6">
            {/* Premium Header */}
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div>
                    <h1 className="text-xl sm:text-2xl font-bold text-white">User Management</h1>
                    <p className="text-sm text-white/50 mt-1">Manage operator accounts for this control plane</p>
                </div>
                <Button
                    leftIcon={<Plus className="w-4 h-4" />}
                    onClick={() => setShowUserModal(true)}
                    className="w-full sm:w-auto bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500 shadow-lg shadow-primary-500/25"
                >
                    Add User
                </Button>
            </div>

            {/* Stats Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="p-4 rounded-2xl bg-gradient-to-br from-blue-500/10 to-blue-600/5 border border-blue-500/20 backdrop-blur-sm">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-blue-500/20 flex items-center justify-center">
                            <UserIcon className="w-5 h-5 text-blue-400" />
                        </div>
                        <div>
                            <p className="text-2xl font-bold text-white">{users.length}</p>
                            <p className="text-xs text-blue-300/70">Total Users</p>
                        </div>
                    </div>
                </div>
                <div className="p-4 rounded-2xl bg-gradient-to-br from-amber-500/10 to-amber-600/5 border border-amber-500/20 backdrop-blur-sm">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-amber-500/20 flex items-center justify-center">
                            <Shield className="w-5 h-5 text-amber-400" />
                        </div>
                        <div>
                            <p className="text-2xl font-bold text-white">{users.filter(u => u.is_active).length}</p>
                            <p className="text-xs text-amber-300/70">Active</p>
                        </div>
                    </div>
                </div>
                <div className="p-4 rounded-2xl bg-gradient-to-br from-emerald-500/10 to-emerald-600/5 border border-emerald-500/20 backdrop-blur-sm">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-emerald-500/20 flex items-center justify-center">
                            <Users className="w-5 h-5 text-emerald-400" />
                        </div>
                        <div>
                            <p className="text-2xl font-bold text-white">{users.filter(u => u.auth === 'sso').length}</p>
                            <p className="text-xs text-emerald-300/70">Signed in via SSO</p>
                        </div>
                    </div>
                </div>
            </div>

            {/* Premium Table */}
            <div className="rounded-2xl bg-white/[0.03] backdrop-blur-xl border border-white/10 overflow-hidden shadow-2xl">
                {/* Table Header - Hidden on mobile */}
                <div className="hidden md:block px-6 py-4 border-b border-white/10 bg-gradient-to-r from-white/[0.05] to-transparent">
                    <div className="grid grid-cols-12 gap-4 items-center">
                        <div className="col-span-4 text-xs font-semibold text-white/50 uppercase tracking-wider">User</div>
                        <div className="col-span-3 text-xs font-semibold text-white/50 uppercase tracking-wider">Email</div>
                        <div className="col-span-2 text-xs font-semibold text-white/50 uppercase tracking-wider text-center">Access</div>
                        <div className="col-span-2 text-xs font-semibold text-white/50 uppercase tracking-wider">Last sign-in</div>
                        <div className="col-span-1 text-xs font-semibold text-white/50 uppercase tracking-wider text-right">Actions</div>
                    </div>
                </div>

                {/* Table Body */}
                <div className="divide-y divide-white/5">
                    {users.map((u, index) => (
                        <motion.div
                            key={u.id}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: index * 0.05 }}
                            className="px-4 md:px-6 py-4 hover:bg-white/[0.03] transition-all duration-200 group"
                        >
                            {/* Mobile: Card Layout */}
                            <div className="md:hidden space-y-3">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-3">
                                        <div className="relative w-10 h-10 rounded-xl flex items-center justify-center font-bold text-sm ring-1 ring-white/10 shadow-xl bg-gradient-to-br from-amber-300 to-orange-500 text-amber-950 drop-shadow-sm shadow-orange-900/50">
                                            {u.full_name ? u.full_name.charAt(0).toUpperCase() : u.username.charAt(0).toUpperCase()}
                                            {u.is_active && <div className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-emerald-500 border-2 border-slate-900 shadow-md shadow-emerald-900/70" />}
                                        </div>
                                        <div>
                                            <p className="font-semibold text-white text-sm">{u.full_name || u.username}</p>
                                            <p className="text-xs text-white/40">@{u.username}</p>
                                        </div>
                                    </div>
                                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold bg-gradient-to-r from-amber-500/20 to-orange-500/20 text-amber-300 border border-amber-500/30">
                                        <Shield className="w-3 h-3" />
                                        Admin
                                    </span>
                                </div>
                                <p className="text-xs text-white/50 truncate">{u.email}</p>
                                <div className="flex items-center justify-between">
                                    <span className="text-xs text-white/40">
                                        {u.last_login_at ? timeAgo(u.last_login_at) : 'never signed in'}
                                    </span>
                                    <div className="flex items-center gap-1">
                                        <button
                                            onClick={() => setPwFor(u)}
                                            className="p-2 rounded-lg hover:bg-white/10 text-white/40 hover:text-white"
                                            title="Set password"
                                            aria-label={`Set password for ${u.username}`}
                                        >
                                            <KeyRound className="w-4 h-4" />
                                        </button>
                                        <button
                                            onClick={() => handleDeleteUser(u.id as number)}
                                            disabled={u.id === me?.id}
                                            className={`p-2 rounded-lg ${u.id === me?.id
                                                ? 'text-white/20 cursor-not-allowed'
                                                : 'hover:bg-red-500/20 text-white/40 hover:text-red-400'
                                                }`}
                                            title={u.id === me?.id ? 'Cannot delete yourself' : 'Delete user'}
                                            aria-label={`Delete ${u.username}`}
                                        >
                                            <Trash2 className="w-4 h-4" />
                                        </button>
                                    </div>
                                </div>
                            </div>

                            {/* Desktop: Grid Layout */}
                            <div className="hidden md:grid grid-cols-12 gap-4 items-center">
                                {/* User Info */}
                                <div className="col-span-4 flex items-center gap-4">
                                    <div className="relative w-12 h-12 rounded-xl flex items-center justify-center font-bold text-lg ring-1 ring-white/10 shadow-xl bg-gradient-to-br from-amber-400 to-orange-500 text-white shadow-orange-900/50">
                                        {u.full_name ? u.full_name.charAt(0).toUpperCase() : u.username.charAt(0).toUpperCase()}
                                        {/* Active indicator */}
                                        {u.is_active && <div className="absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 rounded-full bg-emerald-500 border-2 border-slate-900 shadow-md shadow-emerald-900/70" />}
                                    </div>
                                    <div>
                                        <p className="font-semibold text-white group-hover:text-primary-300 transition-colors">{u.full_name || u.username}</p>
                                        <p className="text-sm text-white/40">@{u.username}</p>
                                    </div>
                                </div>

                                {/* Email */}
                                <div className="col-span-3">
                                    <p className="text-sm text-white/60 truncate">{u.email}</p>
                                </div>

                                {/* Access Badge */}
                                <div className="col-span-2 flex justify-center">
                                    {u.is_active ? (
                                        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-gradient-to-r from-amber-500/20 to-orange-500/20 text-amber-300 border border-amber-500/30 shadow-lg shadow-amber-500/10">
                                            <Shield className="w-3 h-3" />
                                            Admin
                                        </span>
                                    ) : (
                                        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-white/5 text-white/40 border border-white/10">
                                            Disabled
                                        </span>
                                    )}
                                </div>

                                {/* Last sign-in */}
                                <div className="col-span-2">
                                    <span className="text-sm text-white/50">
                                        {u.last_login_at ? timeAgo(u.last_login_at) : <span className="text-white/25 italic">never</span>}
                                    </span>
                                </div>

                                {/* Actions */}
                                <div className="col-span-1 flex justify-end">
                                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                        <button
                                            onClick={() => setPwFor(u)}
                                            className="p-2 rounded-lg transition-all hover:bg-white/10 text-white/40 hover:text-white"
                                            title="Set password"
                                            aria-label={`Set password for ${u.username}`}
                                        >
                                            <KeyRound className="w-4 h-4" />
                                        </button>
                                        <button
                                            onClick={() => handleDeleteUser(u.id as number)}
                                            disabled={u.id === me?.id}
                                            className={`p-2 rounded-lg transition-all ${u.id === me?.id
                                                ? 'text-white/20 cursor-not-allowed'
                                                : 'hover:bg-red-500/20 text-white/40 hover:text-red-400'
                                                }`}
                                            title={u.id === me?.id ? 'Cannot delete yourself' : 'Delete user'}
                                            aria-label={`Delete ${u.username}`}
                                        >
                                            <Trash2 className="w-4 h-4" />
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </motion.div>
                    ))}
                </div>

                {/* Empty State */}
                {users.length === 0 && (
                    <div className="px-6 py-16 text-center">
                        <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-white/5 flex items-center justify-center">
                            <Users className="w-8 h-8 text-white/20" />
                        </div>
                        <p className="text-white/50 mb-2">No users found</p>
                        <p className="text-sm text-white/30">Add your first user to get started</p>
                    </div>
                )}
            </div>

            {/* Add User Modal */}
            <Modal open={showUserModal} onClose={() => setShowUserModal(false)} title="Add New User">
                <form onSubmit={handleCreateUser} className="space-y-4">
                    <Input
                        label="Username"
                        value={newUser.username}
                        onChange={(e) => setNewUser((p) => ({ ...p, username: e.target.value }))}
                        required
                    />
                    <Input
                        label="Full Name"
                        value={newUser.full_name}
                        onChange={(e) => setNewUser((p) => ({ ...p, full_name: e.target.value }))}
                    />
                    <Input
                        label="Email"
                        type="email"
                        value={newUser.email}
                        onChange={(e) => setNewUser((p) => ({ ...p, email: e.target.value }))}
                        required
                    />

                    {/* SSO Info */}
                    <div className="p-3 rounded-lg bg-blue-500/10 border border-blue-500/20 text-sm text-blue-200">
                        <p className="font-medium">🔐 SSO Authentication</p>
                        <p className="text-blue-200/70 mt-1">
                            Operators sign in with SSO using their email address. No password is required —
                            set one only for the first admin or break-fix access.
                        </p>
                    </div>

                    <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-sm text-amber-200">
                        <p className="font-medium">Full control-plane access</p>
                        <p className="text-amber-200/70 mt-1">
                            Everyone added here is an administrator — there is a single access level.
                        </p>
                    </div>

                    <div className="flex justify-end gap-3 pt-4">
                        <Button variant="ghost" onClick={() => setShowUserModal(false)}>Cancel</Button>
                        <Button type="submit" isLoading={busy}>Create User</Button>
                    </div>
                </form>
            </Modal>

            {/* Set Password Modal */}
            <Modal open={!!pwFor} onClose={() => { setPwFor(null); setPassword('') }} title={`Set password — ${pwFor?.username || ''}`}>
                <div className="space-y-4">
                    <p className="text-sm text-white/50">
                        Give this operator a password so they can sign in without SSO (first admin / break-fix).
                    </p>
                    <Input
                        label="New password"
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        helperText="At least 10 characters."
                    />
                    <div className="flex justify-end gap-3 pt-4">
                        <Button variant="ghost" onClick={() => { setPwFor(null); setPassword('') }}>Cancel</Button>
                        <Button onClick={handleSetPassword} isLoading={busy} disabled={password.length < 10} leftIcon={<KeyRound className="w-4 h-4" />}>
                            Set password
                        </Button>
                    </div>
                </div>
            </Modal>
        </div>
    )
}
