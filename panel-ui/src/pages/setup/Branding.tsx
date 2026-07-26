import { useEffect, useState } from 'react'
import { Save, Sparkles, X } from 'lucide-react'
import { api } from '../../lib/api'
import type { PlatformConfig } from '../../lib/types'
import { Button, Card, Input, Spinner } from '../../components/ui'
import { useToast } from '../../components/Toast'
import { useSession } from '../../lib/session'

// Pick black or white text for a background so the label stays legible (and
// meets WCAG contrast) whatever accent color the operator chooses. Uses the
// WCAG relative-luminance threshold (~0.179).
function readableOn(hex: string): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return '#fff'
  const n = parseInt(m[1], 16)
  const chan = (c: number) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  const lum = 0.2126 * chan((n >> 16) & 255) + 0.7152 * chan((n >> 8) & 255) + 0.0722 * chan(n & 255)
  return lum > 0.179 ? '#000' : '#fff'
}

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

  const color = cfg.primary_color || '#6366f1'

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white">Branding Settings</h1>
          <p className="text-white/50 text-sm mt-1">
            How this control plane presents itself — the name, tagline, and mark shown in the
            sidebar, login screen, and browser. This is your hosting program's brand, not a
            municipality's.
          </p>
        </div>
        <Button
          className="w-full sm:w-auto"
          leftIcon={<Save className="w-4 h-4" />}
          onClick={save}
          isLoading={saving}
          disabled={!can('admin')}
        >
          {can('admin') ? 'Save Changes' : 'Admin role required'}
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-6">
        <Card>
          <div className="space-y-4">
            <Input
              label="Platform Name"
              value={cfg.platform_name || ''}
              placeholder="e.g. New Jersey 311 Cloud"
              onChange={(e) => set('platform_name', e.target.value)}
            />
            <Input
              label="Tagline"
              value={cfg.tagline || ''}
              placeholder="Hosting Control Plane"
              onChange={(e) => set('tagline', e.target.value)}
            />
            <div>
              <label className="block text-sm font-medium text-white/70 mb-2">Logo</label>
              <div className="flex items-center gap-3">
                {cfg.logo_url && <img src={cfg.logo_url} alt="Current logo" className="h-10 rounded" />}
                <Input
                  className="flex-1"
                  aria-label="Logo URL"
                  value={cfg.logo_url || ''}
                  placeholder="https://…/logo.svg"
                  onChange={(e) => set('logo_url', e.target.value)}
                />
                {cfg.logo_url && (
                  <button
                    onClick={() => set('logo_url', '')}
                    className="p-2 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
                    title="Remove logo"
                    aria-label="Remove logo"
                  >
                    <X className="w-4 h-4" aria-hidden="true" />
                  </button>
                )}
              </div>
              <p className="text-xs text-white/40 mt-1.5">
                Square image works best; falls back to the default mark.
              </p>
            </div>
            <Input
              label="Support Email"
              type="email"
              value={cfg.support_email || ''}
              placeholder="support@yourprogram.gov"
              onChange={(e) => set('support_email', e.target.value)}
            />
            <div>
              <label className="block text-sm font-medium text-white/70 mb-2">Primary Color</label>
              <div className="flex items-center gap-3">
                <input
                  type="color"
                  value={color}
                  onChange={(e) => set('primary_color', e.target.value)}
                  className="w-12 h-12 rounded-lg cursor-pointer bg-transparent"
                  aria-label="Primary color picker"
                />
                <Input
                  className="flex-1"
                  aria-label="Primary color hex value"
                  value={color}
                  onChange={(e) => set('primary_color', e.target.value)}
                />
              </div>
            </div>
          </div>
        </Card>

        <Card>
          <h3 className="text-lg font-semibold text-white mb-4">Preview</h3>
          <div className="p-4 rounded-xl bg-black/20 space-y-4">
            {cfg.logo_url ? (
              <img src={cfg.logo_url} alt="Logo preview" className="h-16" />
            ) : (
              <div
                className="w-16 h-16 rounded-2xl flex items-center justify-center"
                style={{ background: `linear-gradient(135deg, ${color}, ${color}dd)` }}
              >
                <Sparkles className="w-8 h-8 text-white" />
              </div>
            )}
            <div>
              <div className="text-lg font-bold text-white">{cfg.platform_name || 'Pinpoint 311'}</div>
              <div className="text-sm text-white/50">{cfg.tagline || 'Hosting Control Plane'}</div>
            </div>
            <button
              className="px-4 py-2 rounded-xl text-sm font-medium"
              style={{ background: color, color: readableOn(color) }}
            >
              Sample Button
            </button>
          </div>
        </Card>
      </div>
    </div>
  )
}
