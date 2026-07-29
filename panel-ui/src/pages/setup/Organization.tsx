import { useEffect, useState } from 'react'
import { Save, Landmark, Map as MapIcon, Search, Check } from 'lucide-react'
import { api } from '../../lib/api'
import type { PlatformConfig, OsmResult } from '../../lib/types'
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
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white flex items-center gap-2">
            <Landmark className="w-6 h-6" /> Organization
          </h1>
          <p className="text-white/50 text-sm mt-1">
            Who runs this hosting program — a state, county, city, university, or agency. Used on
            compliance exports and operator-facing screens. This is not a hosted municipality.
          </p>
        </div>
        <Button
          className="w-full sm:w-auto"
          onClick={save}
          isLoading={saving}
          disabled={!can('admin')}
          leftIcon={<Save className="w-4 h-4" />}
        >
          {can('admin') ? 'Save Changes' : 'Admin role required'}
        </Button>
      </div>

      <Card>
        <h3 className="font-semibold text-white mb-4">Identity</h3>
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

      <JurisdictionBoundary jurisdictionHint={cfg.jurisdiction || cfg.org_legal_name || ''} />
    </div>
  )
}

/**
 * The hosting organization's own boundary, looked up on OpenStreetMap the same
 * way a town's is. It becomes the base outline on the Coverage Map, so the
 * participating municipalities read as sitting inside the jurisdiction rather
 * than floating on a blank map.
 */
function JurisdictionBoundary({ jurisdictionHint }: { jurisdictionHint: string }) {
  const toast = useToast()
  const { can } = useSession()
  const [label, setLabel] = useState<string | null>(null)
  const [hasBoundary, setHasBoundary] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<OsmResult[]>([])
  const [searching, setSearching] = useState(false)
  const [busy, setBusy] = useState('')

  useEffect(() => {
    api.getPlatformBoundary()
      .then((r) => { setHasBoundary(r.has_boundary); setLabel(r.label) })
      .catch(() => { })
  }, [])
  useEffect(() => { if (!query && jurisdictionHint) setQuery(jurisdictionHint) }, [jurisdictionHint])

  async function search() {
    if (!query.trim()) return
    setSearching(true)
    setResults([])
    try {
      const r = await api.osmSearch(query.trim())
      setResults(r.results)
      if (r.results.length === 0) toast.push('No boundary found — try the official name, e.g. "State of New Jersey"')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setSearching(false)
    }
  }

  async function choose(r: OsmResult) {
    setBusy(String(r.osm_id))
    try {
      // Nominatim already returns a boundary; fall back to the detail fetch if absent.
      let geojson: unknown = r.geojson
      if (!geojson) geojson = (await api.osmBoundary(r.osm_id)).geojson
      const saved = await api.setPlatformBoundary({ geojson, name: r.display_name?.split(',')[0] })
      setHasBoundary(true)
      setLabel(saved.label)
      setResults([])
      toast.push('Jurisdiction saved — it now frames the Coverage Map')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }

  async function clear() {
    setBusy('clear')
    try {
      await api.clearPlatformBoundary()
      setHasBoundary(false)
      setLabel(null)
      toast.push('Jurisdiction boundary cleared')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }

  return (
    <Card>
      <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
        <MapIcon className="w-5 h-5" /> Jurisdiction boundary
      </h3>
      <p className="text-sm text-white/50 mb-4">
        Look up your organization's own area on OpenStreetMap. It draws as the base outline on the
        Coverage Map, with every participating municipality shown inside it. Public geography only.
      </p>

      {hasBoundary && (
        <div className="flex items-center justify-between gap-3 mb-4 p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/25">
          <span className="text-sm text-emerald-200 flex items-center gap-2 min-w-0">
            <Check className="w-4 h-4 shrink-0" />
            <span className="truncate">Using <b>{label || 'saved boundary'}</b> as the map base.</span>
          </span>
          {can('operator') && (
            <Button size="sm" variant="ghost" onClick={clear} isLoading={busy === 'clear'}>Remove</Button>
          )}
        </div>
      )}

      {can('operator') && (
        <>
          <div className="flex flex-col sm:flex-row gap-2">
            <Input
              label="Search OpenStreetMap"
              className="flex-1"
              placeholder='e.g. "State of New Jersey" or "Essex County, NJ"'
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && search()}
            />
            <div className="sm:pt-7">
              <Button variant="secondary" onClick={search} isLoading={searching} leftIcon={<Search className="w-4 h-4" />}>
                Search
              </Button>
            </div>
          </div>

          {results.length > 0 && (
            <div className="mt-3 space-y-2">
              {results.map((r) => (
                <div key={r.osm_id} className="flex items-center justify-between gap-3 p-3 rounded-xl bg-white/[0.03] border border-white/10">
                  <div className="min-w-0">
                    <p className="text-sm text-white truncate">{r.display_name}</p>
                    <p className="text-xs text-white/40">{r.class} · {r.type}</p>
                  </div>
                  <Button size="sm" onClick={() => choose(r)} isLoading={busy === String(r.osm_id)}>
                    {hasBoundary ? 'Replace' : 'Use this'}
                  </Button>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Card>
  )
}
