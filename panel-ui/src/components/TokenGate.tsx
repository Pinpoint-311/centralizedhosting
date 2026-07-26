import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { KeyRound, ArrowRight, AlertCircle, LogIn, User as UserIcon } from 'lucide-react'
import { api, setToken } from '../lib/api'
import { Button, Card, Input } from './ui'
import { Logo } from './Logo'
import { getPlatformName, getTagline } from '../lib/config'

const SSO_ERRORS: Record<string, string> = {
  expired_state: 'Your sign-in attempt expired. Please try again.',
  verification_failed: 'We could not verify your identity provider response.',
  not_configured: 'Single sign-on is not configured.',
  not_provisioned: 'Your account is not authorized. Ask an admin to add you under Setup → Users.',
}

export function TokenGate({ onAuthed }: { onAuthed: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [ssoConfigured, setSsoConfigured] = useState(false)
  const [showToken, setShowToken] = useState(false)
  const [token, setTokenValue] = useState('')

  useEffect(() => {
    api.ssoStatus().then((s) => setSsoConfigured(s.configured)).catch(() => setSsoConfigured(false))
    const params = new URLSearchParams(window.location.search)
    const err = params.get('sso_error')
    if (err) {
      setError(SSO_ERRORS[err] || 'Single sign-on failed. Please try again.')
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  async function loginWithPassword() {
    if (!username.trim() || !password) return
    setLoading(true)
    setError('')
    try {
      await api.login(username.trim(), password)
      onAuthed()
    } catch (e) {
      const m = (e as Error).message || ''
      setError(m.includes('401') || /invalid/i.test(m) ? 'Incorrect username or password.' : m || 'Could not sign in.')
      setLoading(false)
    }
  }

  async function enterWithToken() {
    if (!token.trim()) return
    setLoading(true)
    setError('')
    setToken(token.trim())
    try {
      await api.whoami()
      onAuthed()
    } catch (e) {
      const m = (e as Error).message || ''
      setError(m.includes('401') || /invalid/i.test(m) ? 'That panel token was not accepted.' : m || 'Could not reach the control plane.')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-md">
        <Card className="p-8">
          <div className="text-center mb-8">
            <div className="flex justify-center mb-4">
              <Logo size={64} />
            </div>
            <h1 className="text-2xl font-bold text-white">{getPlatformName()}</h1>
            <p className="text-white/50 mt-2">{getTagline()}</p>
          </div>

          {error && (
            <div className="flex items-center gap-3 p-4 rounded-xl bg-red-500/20 border border-red-500/30 text-red-300 mb-6">
              <AlertCircle className="w-5 h-5 shrink-0" />
              <span className="text-sm">{error}</span>
            </div>
          )}

          {ssoConfigured && (
            <div className="space-y-3 mb-5 pb-5 border-b border-white/10">
              <Button
                className="w-full"
                onClick={() => { window.location.href = '/api/auth/sso/login' }}
                leftIcon={<LogIn className="w-4 h-4" />}
              >
                Sign in with SSO
              </Button>
              <p className="text-white/40 text-xs text-center">Secured by your organization's identity provider.</p>
            </div>
          )}

          <div className="space-y-4">
            <Input
              label="Username"
              placeholder="your operator username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && loginWithPassword()}
              leftIcon={<UserIcon className="w-4 h-4" />}
              autoFocus={!ssoConfigured}
            />
            <Input
              label="Password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && loginWithPassword()}
            />
            <Button className="w-full" onClick={loginWithPassword} isLoading={loading} leftIcon={<KeyRound className="w-4 h-4" />}>
              Sign in <ArrowRight className="w-4 h-4 ml-2" />
            </Button>
          </div>

          {!showToken ? (
            <button
              onClick={() => setShowToken(true)}
              className="w-full text-center text-xs text-white/40 hover:text-white/70 mt-5"
            >
              Use a panel operator token instead
            </button>
          ) : (
            <div className="mt-5 pt-5 border-t border-white/10 space-y-3">
              <Input
                label="Panel operator token"
                type="password"
                placeholder="Paste your PANEL_API_TOKEN"
                value={token}
                onChange={(e) => setTokenValue(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && enterWithToken()}
                helperText="Machine/bootstrap access. Create operators under Setup → Users."
              />
              <Button className="w-full" variant="secondary" onClick={enterWithToken} isLoading={loading}>
                Enter with token
              </Button>
            </div>
          )}

          <p className="text-white/30 text-xs text-center mt-6">
            Metadata-only control plane. Resident data never leaves a town's own instance.
          </p>
        </Card>
      </motion.div>
    </div>
  )
}
