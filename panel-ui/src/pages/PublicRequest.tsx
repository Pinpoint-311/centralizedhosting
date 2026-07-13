import { useState } from 'react'
import { motion } from 'framer-motion'
import { Send, CheckCircle, AlertCircle } from 'lucide-react'
import { api } from '../lib/api'
import { Button, Card, Input, Textarea } from '../components/ui'
import { Logo } from '../components/Logo'

/**
 * Public, unauthenticated self-service intake for a municipality to request
 * hosting. Only works when the panel has PUBLIC_REQUESTS_ENABLED.
 */
export function PublicRequest() {
  const [f, setF] = useState({ name: '', requested_slug: '', contact_name: '', contact_email: '', message: '' })
  const [state, setState] = useState<'form' | 'sent' | 'error'>('form')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const set = (k: keyof typeof f, v: string) => setF((s) => ({ ...s, [k]: v }))

  async function submit() {
    setSaving(true)
    setError('')
    try {
      await api.submitRequest({
        name: f.name,
        requested_slug: f.requested_slug || null,
        contact_name: f.contact_name || null,
        contact_email: f.contact_email || null,
        message: f.message || null,
      })
      setState('sent')
    } catch (e) {
      const msg = (e as Error).message
      setError(msg.includes('not enabled') ? 'Online requests are not currently open. Please contact your state program office.' : msg)
      setState('error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-lg">
        <Card className="p-8">
          <div className="text-center mb-6">
            <div className="flex justify-center mb-4"><Logo size={56} /></div>
            <h1 className="text-2xl font-bold text-white">Request Pinpoint 311 hosting</h1>
            <p className="text-white/50 mt-2">Tell us about your municipality and we'll be in touch.</p>
          </div>

          {state === 'sent' ? (
            <div className="text-center py-6">
              <CheckCircle className="w-12 h-12 text-green-400 mx-auto mb-3" />
              <p className="text-white font-medium">Request received</p>
              <p className="text-white/50 text-sm mt-1">Your state program office will review it and reach out.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {state === 'error' && (
                <div className="flex items-center gap-3 p-3 rounded-xl bg-red-500/20 border border-red-500/30 text-red-300">
                  <AlertCircle className="w-5 h-5 shrink-0" /><span className="text-sm">{error}</span>
                </div>
              )}
              <Input label="Municipality name" required value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="Springfield, IL" />
              <Input label="Preferred subdomain (optional)" value={f.requested_slug} onChange={(e) => set('requested_slug', e.target.value)} placeholder="springfield" />
              <div className="grid sm:grid-cols-2 gap-4">
                <Input label="Your name" value={f.contact_name} onChange={(e) => set('contact_name', e.target.value)} />
                <Input label="Email" type="email" value={f.contact_email} onChange={(e) => set('contact_email', e.target.value)} />
              </div>
              <Textarea label="Anything else?" value={f.message} onChange={(e) => set('message', e.target.value)} placeholder="Population, current system, timeline…" />
              <Button className="w-full" onClick={submit} isLoading={saving} disabled={!f.name.trim()} leftIcon={<Send className="w-4 h-4" />}>
                Submit request
              </Button>
            </div>
          )}
        </Card>
      </motion.div>
    </div>
  )
}
