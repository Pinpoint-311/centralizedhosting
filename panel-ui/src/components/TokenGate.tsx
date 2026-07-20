import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { KeyRound, ArrowRight, AlertCircle, LogIn } from 'lucide-react'
import { api, setToken } from '../lib/api'
import { Button, Card, Input } from './ui'
import { Logo } from './Logo'

const SSO_ERRORS: Record<string, string> = {
  expired_state: 'Your sign-in attempt expired. Please try again.',
  verification_failed: 'We could not verify your identity provider response.',
  not_configured: 'Single sign-on is not configured.',
}

export function TokenGate({ onAuthed }: { onAuthed: () => void }) {
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [ssoConfigured, setSsoConfigured] = useState(false)
  const [showToken, setShowToken] = useState(false)

  useEffect(() => {
    api.ssoStatus().then((s) => setSsoConfigured(s.configured)).catch(() => setSsoConfigured(false))
    // Surface an SSO callback error passed back on the URL.
    const params = new URLSearchParams(window.location.search)
    const err = params.get('sso_error')
    if (err) {
      setError(SSO_ERRORS[err] || 'Single sign-on failed. Please try again.')
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  async function submit() {
    if (!value.trim()) return
    setLoading(true)
    setError('')
    setToken(value.trim())
    try {
      await api.whoami()
      onAuthed()
    } catch (e) {
      setError(
        (e as Error).message?.includes('401') || (e as Error).message?.includes('Invalid')
          ? 'That panel token was not accepted.'
          : (e as Error).message || 'Could not reach the control plane.',
      )
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
            <h1 className="text-2xl font-bold text-white">Pinpoint 311</h1>
            <p className="text-white/50 mt-2">Centralized Hosting Control Plane</p>
          </div>

          {error && (
            <div className="flex items-center gap-3 p-4 rounded-xl bg-red-500/20 border border-red-500/30 text-red-300 mb-6">
              <AlertCircle className="w-5 h-5 shrink-0" />
              <span className="text-sm">{error}</span>
            </div>
          )}

          {ssoConfigured && (
            <div className="space-y-3">
              <Button
                className="w-full"
                onClick={() => { window.location.href = '/api/auth/sso/login' }}
                leftIcon={<LogIn className="w-4 h-4" />}
              >
                Sign in with SSO
              </Button>
              <p className="text-white/40 text-xs text-center">Secured by your organization's identity provider.</p>
              {!showToken && (
                <button
                  onClick={() => setShowToken(true)}
                  className="w-full text-center text-xs text-white/40 hover:text-white/70 mt-2"
                >
                  Use an operator token instead
                </button>
              )}
            </div>
          )}

          {(!ssoConfigured || showToken) && (
            <div className={`space-y-4 ${ssoConfigured ? 'mt-5 pt-5 border-t border-white/10' : ''}`}>
              <Input
                label="Panel operator token"
                type="password"
                placeholder="Paste your PANEL_API_TOKEN"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && submit()}
                autoFocus={!ssoConfigured}
              />
              <Button className="w-full" variant={ssoConfigured ? 'secondary' : 'primary'} onClick={submit} isLoading={loading} leftIcon={<KeyRound className="w-4 h-4" />}>
                Enter control plane <ArrowRight className="w-4 h-4 ml-2" />
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
