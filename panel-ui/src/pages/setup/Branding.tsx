import { useEffect, useState } from 'react'
import { Save, Palette } from 'lucide-react'
import { api } from '../../lib/api'
import type { PlatformConfig } from '../../lib/types'
import { Badge, Button, Card, Input, Spinner } from '../../components/ui'
import { Logo } from '../../components/Logo'
import { useToast } from '../../components/Toast'
import { useSession } from '../../lib/session'

export function Branding() {
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
        platform_name: cfg!.platform_name,
        tagline: cfg!.tagline,
        logo_url: cfg!.logo_url || null,
        primary_color: cfg!.primary_color || null,
        support_email: cfg!.support_email || null,
      })
      setCfg(out)
      toast.push('Branding saved — reload to see it across the panel')
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
          <Palette className="w-5 h-5" /> Platform branding
        </h3>
        <p className="text-sm text-white/50 mb-4">
          How this control plane presents itself — the name and tagline shown in the sidebar, the
          login screen, and the browser. This is your hosting program's brand, not a municipality's.
        </p>
        <div className="grid sm:grid-cols-2 gap-4">
          <Input label="Platform name" placeholder="e.g. New Jersey 311 Cloud" value={cfg.platform_name} onChange={(e) => set('platform_name', e.target.value)} />
          <Input label="Tagline" placeholder="Hosting Control Plane" value={cfg.tagline} onChange={(e) => set('tagline', e.target.value)} />
          <Input label="Logo URL (optional)" placeholder="https://…/logo.svg" value={cfg.logo_url || ''} onChange={(e) => set('logo_url', e.target.value)} helperText="Square image works best; falls back to the default mark." />
          <div>
            <label className="block text-sm font-medium text-white/70 mb-1.5">Primary color</label>
            <div className="flex items-center gap-2">
              <input type="color" value={cfg.primary_color || '#6366f1'} onChange={(e) => set('primary_color', e.target.value)} className="h-11 w-14 rounded-lg bg-transparent border border-white/15 cursor-pointer" />
              <Input className="flex-1" placeholder="#6366f1" value={cfg.primary_color || ''} onChange={(e) => set('primary_color', e.target.value)} />
            </div>
          </div>
          <Input label="Support email (optional)" type="email" placeholder="support@yourprogram.gov" value={cfg.support_email || ''} onChange={(e) => set('support_email', e.target.value)} />
        </div>
        <div className="flex justify-end mt-4">
          <Button onClick={save} isLoading={saving} disabled={!can('admin')} leftIcon={<Save className="w-4 h-4" />}>
            {can('admin') ? 'Save branding' : 'Admin role required'}
          </Button>
        </div>
      </Card>

      <Card>
        <h3 className="font-semibold text-white mb-3">Preview</h3>
        <div className="flex items-center gap-3 p-4 rounded-2xl bg-white/[0.03] border border-white/10 w-fit">
          {cfg.logo_url ? (
            <img src={cfg.logo_url} alt="" className="w-9 h-9 rounded-xl object-cover" />
          ) : (
            <Logo size={38} />
          )}
          <div>
            <div className="font-semibold text-white leading-tight">{cfg.platform_name || 'Pinpoint 311'}</div>
            <div className="text-xs text-white/50">{cfg.tagline || 'Hosting Control Plane'}</div>
          </div>
        </div>
        {cfg.primary_color && (
          <div className="mt-3 flex items-center gap-2">
            <span className="text-xs text-white/40">Accent</span>
            <span className="inline-block w-6 h-6 rounded-md border border-white/15" style={{ background: cfg.primary_color }} />
            <Badge>{cfg.primary_color}</Badge>
          </div>
        )}
      </Card>
    </div>
  )
}
