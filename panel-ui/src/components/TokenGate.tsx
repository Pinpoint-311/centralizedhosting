import { useState } from 'react'
import { motion } from 'framer-motion'
import { KeyRound, ArrowRight, AlertCircle } from 'lucide-react'
import { api, setToken } from '../lib/api'
import { Button, Card, Input } from './ui'
import { Logo } from './Logo'

export function TokenGate({ onAuthed }: { onAuthed: () => void }) {
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit() {
    if (!value.trim()) return
    setLoading(true)
    setError('')
    setToken(value.trim())
    try {
      await api.verifyToken()
      onAuthed()
    } catch (e) {
      setError(
        (e as Error).message?.includes('401')
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

          <div className="space-y-4">
            <Input
              label="Panel operator token"
              type="password"
              placeholder="Paste your PANEL_API_TOKEN"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
              autoFocus
            />
            <Button className="w-full" onClick={submit} isLoading={loading} leftIcon={<KeyRound className="w-4 h-4" />}>
              Enter control plane <ArrowRight className="w-4 h-4 ml-2" />
            </Button>
          </div>

          <p className="text-white/30 text-xs text-center mt-6">
            Metadata-only control plane. Resident data never leaves a town's own instance.
          </p>
        </Card>
      </motion.div>
    </div>
  )
}
