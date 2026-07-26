import { useEffect, useState } from 'react'
import { Save, Landmark } from 'lucide-react'
import { api } from '../../lib/api'
import type { PlatformConfig } from '../../lib/types'
import { Button, Card, Input, Select, Textarea, Spinner } from '../../components/ui'
import { useToast } from '../../components/Toast'
import { useSession } from '../../lib/session'

const ORG_TYPES = [
  { value: 'state', label: 'State' },
  { value: 'county', label: 'County' },
  { value: 'city', label: 'City / Municipality' },
  { value: 'university', label: 'University' },
  { value: 'agency', label: 'Agency' },
  { value: 'other', label: 'Other' },
]

export function Organization() {
  const toast = useToast()
  const { can } = useSession()
  const [cfg, setCfg] = useState<PlatformConfig | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.getPlatformConfig().then(setCfg).catch((e) => toast.push((e as Error).message, 'error'))
  }, [])
  if (!cfg) return <Spinner />
  const set = (k: keyof PlatformConfig, v: string) => setCfg({ ...cfg, [k]: v })

  async function save() {
    setSaving(true)
    try {
      const out = await api.putPlatformConfig({
        org_legal_name: cfg!.org_legal_name || null,
        org_type: cfg!.org_type,
        jurisdiction: cfg!.jurisdiction || null,
        contact_name: cfg!.contact_name || null,
        contact_email: cfg!.contact_email || null,
        contact_phone: cfg!.contact_phone || null,
        address: cfg!.address || null,
        website: cfg!.website || null,
      })
      setCfg(out)
      toast.push('Organization saved')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <Card>
        <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
          <Landmark className="w-5 h-5" /> Hosting organization
        </h3>
        <p className="text-sm text-white/50 mb-4">
          Who runs this hosting program — a state, county, city, university, or agency. Used on
          compliance exports and operator-facing screens. This is not a hosted municipality.
        </p>
        <div className="grid sm:grid-cols-2 gap-4">
          <Input label="Legal name" placeholder="e.g. NJ Office of Innovation" value={cfg.org_legal_name || ''} onChange={(e) => set('org_legal_name', e.target.value)} />
          <Select label="Organization type" value={cfg.org_type} onChange={(e) => set('org_type', e.target.value)} options={ORG_TYPES} />
          <Input label="Jurisdiction" placeholder="e.g. State of New Jersey" value={cfg.jurisdiction || ''} onChange={(e) => set('jurisdiction', e.target.value)} />
          <Input label="Website" placeholder="https://…" value={cfg.website || ''} onChange={(e) => set('website', e.target.value)} />
        </div>
      </Card>

      <Card>
        <h3 className="font-semibold text-white mb-4">Primary contact</h3>
        <div className="grid sm:grid-cols-2 gap-4">
          <Input label="Contact name" value={cfg.contact_name || ''} onChange={(e) => set('contact_name', e.target.value)} />
          <Input label="Email" type="email" value={cfg.contact_email || ''} onChange={(e) => set('contact_email', e.target.value)} />
          <Input label="Phone" value={cfg.contact_phone || ''} onChange={(e) => set('contact_phone', e.target.value)} />
        </div>
        <div className="mt-4">
          <Textarea label="Mailing address" value={cfg.address || ''} onChange={(e) => set('address', e.target.value)} />
        </div>
      </Card>

      <div className="flex justify-end max-w-3xl">
        <Button onClick={save} isLoading={saving} disabled={!can('admin')} leftIcon={<Save className="w-4 h-4" />}>
          {can('admin') ? 'Save organization' : 'Admin role required'}
        </Button>
      </div>
    </div>
  )
}
