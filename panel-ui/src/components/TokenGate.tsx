import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { AlertCircle, Shield, LogIn, KeyRound } from 'lucide-react'
import { Button, Card, Input } from './ui'
import { api, setToken } from '../lib/api'
import { Logo } from './Logo'
import { getPlatformName } from '../lib/config'

/**
 * Operator sign-in — the app's Login page, ported to the control plane.
 * Same layout, states and copy structure (logo block, alert region, SSO
 * primary action, footer). The control plane adds two paths the app doesn't
 * need: a password sign-in for the first admin / break-fix, and the machine
 * operator token.
 */

const SSO_ERRORS: Record<string, string> = {
    expired_state: 'Your sign-in attempt expired. Please try again.',
    verification_failed: 'We could not verify your identity provider response.',
    not_configured: 'Single sign-on is not configured.',
    not_provisioned: 'Your account is not authorized. Ask an admin to add you under Setup → Users.',
}

export function TokenGate({ onAuthed }: { onAuthed: () => void }) {
    const [error, setError] = useState('')
    const [isLoading, setIsLoading] = useState(false)
    const [authStatus, setAuthStatus] = useState<{ configured: boolean } | null>(null)
    const [showAlternate, setShowAlternate] = useState(false)
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [token, setTokenValue] = useState('')

    // Check auth status on mount
    useEffect(() => {
        api.ssoStatus().then(setAuthStatus).catch(() => setAuthStatus({ configured: false }))
        const params = new URLSearchParams(window.location.search)
        const urlError = params.get('sso_error')
        if (urlError) {
            setError(SSO_ERRORS[urlError] || 'Single sign-on failed. Please try again.')
            window.history.replaceState({}, '', window.location.pathname)
        }
    }, [])

    const handleLogin = () => {
        setError('')
        setIsLoading(true)
        window.location.href = '/api/auth/sso/login'
    }

    const handlePasswordLogin = async () => {
        if (!username.trim() || !password) return
        setError('')
        setIsLoading(true)
        try {
            await api.login(username.trim(), password)
            onAuthed()
        } catch (err) {
            const m = (err as Error).message || ''
            setError(m.includes('401') || /invalid/i.test(m) ? 'Incorrect username or password.' : m || 'Failed to sign in')
            setIsLoading(false)
        }
    }

    const handleTokenLogin = async () => {
        if (!token.trim()) return
        setError('')
        setIsLoading(true)
        setToken(token.trim())
        try {
            await api.whoami()
            onAuthed()
        } catch (err) {
            const m = (err as Error).message || ''
            setError(m.includes('401') || /invalid/i.test(m) ? 'That panel token was not accepted.' : m || 'Could not reach the control plane.')
            setIsLoading(false)
        }
    }

    return (
        <div className="min-h-screen flex items-center justify-center p-4">
            {/* Main content landmark */}
            <main id="main-content" className="w-full max-w-md">
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                >
                    <Card className="p-8">
                        {/* Logo */}
                        <div className="text-center mb-8">
                            <div className="flex justify-center mb-4">
                                <Logo size={64} />
                            </div>
                            <h1 className="text-2xl font-bold text-white" data-no-translate>
                                {getPlatformName()}
                            </h1>
                            <p className="text-white/50 mt-2">Hosting Control Plane</p>
                        </div>

                        {/* Global Error Message */}
                        {error && (
                            <motion.div
                                initial={{ opacity: 0, y: -10 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="flex items-center gap-3 p-4 rounded-xl bg-red-500/20 border border-red-500/30 text-red-300 mb-6"
                                role="alert"
                                aria-live="assertive"
                            >
                                <AlertCircle className="w-5 h-5 flex-shrink-0" aria-hidden="true" />
                                <span className="text-sm">{error}</span>
                            </motion.div>
                        )}

                        {/* SSO Login Button */}
                        {authStatus?.configured && (
                            <div className="space-y-4">
                                <Button
                                    size="lg"
                                    className="w-full"
                                    onClick={handleLogin}
                                    disabled={isLoading}
                                    isLoading={isLoading}
                                    leftIcon={<LogIn className="w-5 h-5" />}
                                    aria-label={isLoading ? 'Signing in, please wait' : 'Sign in with your organization account'}
                                >
                                    Sign In with SSO
                                </Button>

                                <div className="flex items-center justify-center gap-2 text-white/40 text-sm">
                                    <Shield className="w-4 h-4" />
                                    <span>Secured by your organization's identity provider</span>
                                </div>
                            </div>
                        )}

                        {/* Password / token sign-in — the control plane's break-fix paths */}
                        {(!authStatus?.configured || showAlternate) ? (
                            <div className={`space-y-4 ${authStatus?.configured ? 'mt-5 pt-5 border-t border-white/10' : ''}`}>
                                <Input
                                    label="Username"
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && handlePasswordLogin()}
                                    autoFocus={!authStatus?.configured}
                                />
                                <Input
                                    label="Password"
                                    type="password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && handlePasswordLogin()}
                                />
                                <Button
                                    className="w-full"
                                    variant={authStatus?.configured ? 'secondary' : 'primary'}
                                    onClick={handlePasswordLogin}
                                    isLoading={isLoading}
                                    leftIcon={<KeyRound className="w-4 h-4" />}
                                >
                                    Sign In
                                </Button>

                                <div className="pt-3 border-t border-white/10 space-y-3">
                                    <Input
                                        label="Panel operator token"
                                        type="password"
                                        placeholder="Paste your PANEL_API_TOKEN"
                                        value={token}
                                        onChange={(e) => setTokenValue(e.target.value)}
                                        onKeyDown={(e) => e.key === 'Enter' && handleTokenLogin()}
                                        helperText="Machine/bootstrap access. Create operators under Setup → Users."
                                    />
                                    <Button className="w-full" variant="ghost" onClick={handleTokenLogin} isLoading={isLoading}>
                                        Enter with token
                                    </Button>
                                </div>
                            </div>
                        ) : (
                            <button
                                onClick={() => setShowAlternate(true)}
                                className="w-full text-center text-xs text-white/40 hover:text-white/70 mt-5"
                            >
                                Use a password or operator token instead
                            </button>
                        )}

                        {/* Footer */}
                        <div className="mt-8 pt-6 border-t border-white/10 text-center">
                            <p className="text-sm text-white/40">
                                Authorized users only. Contact an administrator to request access.
                            </p>
                            <p className="text-white/20 text-xs mt-4">
                                Metadata-only control plane. Resident data never leaves a town's own instance.
                            </p>
                        </div>
                    </Card>
                </motion.div>
            </main>
        </div>
    )
}
