import { useState } from 'react'
import { motion } from 'framer-motion'
import { Send, CheckCircle, AlertCircle } from 'lucide-react'
import { api } from '../lib/api'
import { Button, Card, Input, Textarea } from '../components/ui'
import { Logo } from '../components/Logo'
import { getRegionLabel } from '../lib/config'

/**
 * Public, unauthenticated self-service intake for a municipality to request
 * hosting. Only works when the panel has PUBLIC_REQUESTS_ENABLED.
 */
export function PublicRequest() {
  const [f, setF] = useState({
    name: '', requested_slug: '', county: '', contact_name: '', contact_title: '',
    contact_email: '', contact_phone: '', population: '', current_system: '', timeline: '',
    message: '', website: '',
  })
  const [ref, setRef] = useState('')
  const [state, setState] = useState<'form' | 'sent' | 'error'>('form')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const set = (k: keyof typeof f, v: string) => setF((s) => ({ ...s, [k]: v }))

  async function submit() {
    setSaving(true)
    setError('')
    try {
      const r = await api.submitRequest({
        name: f.name,
        requested_slug: f.requested_slug || null,
        county: f.county || null,
        contact_name: f.contact_name || null,
        contact_email: f.contact_email || null,
        contact_phone: f.contact_phone || null,
        message: f.message || null,
        website: f.website || null, // honeypot
        details: {
          contact_title: f.contact_title || undefined,
          population: f.population ? Number(f.population) : undefined,
          current_system: f.current_system || undefined,
          timeline: f.timeline || undefined,
        },
      })
      setRef(r.ref_code || '')
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
              {ref && <p className="text-white/70 text-sm mt-1">Reference <code className="text-indigo-200">{ref}</code></p>}
              <p className="text-white/50 text-sm mt-1">Your program office will review it and reach out.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {state === 'error' && (
                <div className="flex items-center gap-3 p-3 rounded-xl bg-red-500/20 border border-red-500/30 text-red-300">
                  <AlertCircle className="w-5 h-5 shrink-0" /><span className="text-sm">{error}</span>
                </div>
              )}
              {/* Honeypot — hidden from humans; bots fill it and get silently dropped */}
              <input
                type="text"
                tabIndex={-1}
                autoComplete="off"
                aria-hidden="true"
                className="hidden"
                value={f.website}
                onChange={(e) => set('website', e.target.value)}
              />
              <div className="grid sm:grid-cols-2 gap-4">
                <Input label="Municipality name" required value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. Riverside" />
                <Input label={getRegionLabel()} value={f.county} onChange={(e) => set('county', e.target.value)} placeholder={`Which ${getRegionLabel().toLowerCase()}?`} />
              </div>
              <Input label="Preferred subdomain (optional)" value={f.requested_slug} onChange={(e) => set('requested_slug', e.target.value)} placeholder="riverside" />
              <div className="grid sm:grid-cols-2 gap-4">
                <Input label="Your name" value={f.contact_name} onChange={(e) => set('contact_name', e.target.value)} />
                <Input label="Title" value={f.contact_title} onChange={(e) => set('contact_title', e.target.value)} />
                <Input label="Email" type="email" value={f.contact_email} onChange={(e) => set('contact_email', e.target.value)} />
                <Input label="Phone" value={f.contact_phone} onChange={(e) => set('contact_phone', e.target.value)} />
              </div>
              <div className="grid sm:grid-cols-2 gap-4">
                <Input label="Population (approx.)" inputMode="numeric" value={f.population} onChange={(e) => set('population', e.target.value)} />
                <Input label="Target go-live" value={f.timeline} onChange={(e) => set('timeline', e.target.value)} placeholder="e.g. this fall" />
              </div>
              <Input label="Current 311 / CRM system" value={f.current_system} onChange={(e) => set('current_system', e.target.value)} placeholder="e.g. spreadsheet, SeeClickFix, none" />
              <Textarea label="Anything else?" value={f.message} onChange={(e) => set('message', e.target.value)} placeholder="Data migration needs, records/OPRA contact, questions…" />
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
