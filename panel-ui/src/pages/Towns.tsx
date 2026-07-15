import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Building2, Plus, Search, ArrowRight, ArrowLeft, Check, Globe, Upload, X } from 'lucide-react'
import { api } from '../lib/api'
import { useSession } from '../lib/session'
import type { BulkResultRow, KeyCatalog, Tenant } from '../lib/types'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Modal,
  Select,
  Spinner,
  StatusBadge,
  Textarea,
} from '../components/ui'
import { PageToolbar } from '../components/Shell'
import { useToast } from '../components/Toast'

const REGIONS = [
  { value: 'us', label: 'United States' },
  { value: 'us-east', label: 'US East' },
  { value: 'us-west', label: 'US West' },
  { value: 'us-central', label: 'US Central' },
]
const PLANS = [
  { value: 'standard', label: 'Standard' },
  { value: 'small', label: 'Small (< 5k residents)' },
  { value: 'large', label: 'Large (metro)' },
]

import { getBaseDomain, getRegionLabel, getRegions } from '../lib/config'

function slugify(s: string) {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 63)
}

export function Towns() {
  const BASE_DOMAIN = getBaseDomain()
  const { can } = useSession()
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [tagFilter, setTagFilter] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [showBulk, setShowBulk] = useState(false)
  const toast = useToast()

  async function load() {
    try {
      setTenants(await api.listTenants())
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  const allTags = useMemo(
    () => Array.from(new Set(tenants.flatMap((t) => t.tags || []))).sort(),
    [tenants],
  )
  const filtered = useMemo(
    () =>
      tenants.filter(
        (t) =>
          (t.name.toLowerCase().includes(query.toLowerCase()) ||
            t.slug.includes(query.toLowerCase())) &&
          (!tagFilter || (t.tags || []).includes(tagFilter)),
      ),
    [tenants, query, tagFilter],
  )

  return (
    <div>
      {can('operator') && (
        <PageToolbar>
          <Button variant="secondary" onClick={() => setShowBulk(true)} leftIcon={<Upload className="w-4 h-4" />}>
            Bulk import
          </Button>
          <Button onClick={() => setShowAdd(true)} leftIcon={<Plus className="w-4 h-4" />}>
            Add municipality
          </Button>
        </PageToolbar>
      )}

      {loading ? (
        <Spinner />
      ) : tenants.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Building2 className="w-7 h-7" />}
            title="No municipalities yet"
            hint="Add a town to provision its dedicated, isolated Pinpoint 311 instance."
            action={
              <Button onClick={() => setShowAdd(true)} leftIcon={<Plus className="w-4 h-4" />}>
                Add your first municipality
              </Button>
            }
          />
        </Card>
      ) : (
        <>
          <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-4">
            <div className="relative max-w-sm flex-1">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
              <input
                className="glass-input pl-10"
                placeholder="Search municipalities…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search municipalities"
              />
            </div>
            {allTags.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                <button
                  onClick={() => setTagFilter(null)}
                  className={`px-2.5 py-1 text-xs rounded-full border ${!tagFilter ? 'bg-indigo-500/30 border-indigo-400/40 text-white' : 'border-white/15 text-white/60 hover:text-white'}`}
                >
                  All
                </button>
                {allTags.map((tag) => (
                  <button
                    key={tag}
                    onClick={() => setTagFilter(tag)}
                    className={`px-2.5 py-1 text-xs rounded-full border ${tagFilter === tag ? 'bg-indigo-500/30 border-indigo-400/40 text-white' : 'border-white/15 text-white/60 hover:text-white'}`}
                  >
                    {tag}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {filtered.map((t, i) => (
              <motion.div key={t.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}>
                <Link to={`/towns/${t.id}`}>
                  <Card hover className="h-full">
                    <div className="flex items-start justify-between mb-3">
                      <div className="w-11 h-11 rounded-xl bg-primary-500/20 text-primary-300 flex items-center justify-center">
                        <Building2 className="w-6 h-6" />
                      </div>
                      <StatusBadge status={t.status} />
                    </div>
                    <div className="font-semibold text-white truncate">{t.name}</div>
                    <div className="text-sm text-white/40 truncate flex items-center gap-1 mt-0.5">
                      <Globe className="w-3.5 h-3.5" />
                      {t.custom_domain || `${t.subdomain}.${BASE_DOMAIN}`}
                    </div>
                    <div className="flex items-center gap-2 mt-3 text-xs text-white/50 flex-wrap">
                      <Badge>{t.plan}</Badge>
                      {t.running_version && <Badge variant="info">v{t.running_version}</Badge>}
                      {(t.tags || []).map((tag) => <Badge key={tag}>{tag}</Badge>)}
                    </div>
                  </Card>
                </Link>
              </motion.div>
            ))}
          </div>
        </>
      )}

      {showBulk && <BulkImport onClose={() => setShowBulk(false)} onDone={() => { setShowBulk(false); load() }} />}

      {showAdd && (
        <AddTownWizard
          onClose={() => setShowAdd(false)}
          onCreated={() => {
            setShowAdd(false)
            load()
          }}
        />
      )}
    </div>
  )
}

// ------------------------------------------------------------- Add wizard

interface Draft {
  name: string
  slug: string
  slugTouched: boolean
  domainMode: 'subdomain' | 'custom'
  custom_domain: string
  region: string
  county: string
  plan: string
  contact_name: string
  contact_title: string
  contact_email: string
  contact_phone: string
  address: string
  notes: string
  key_assignments: Record<string, string>
}

function AddTownWizard({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const BASE_DOMAIN = getBaseDomain()
  const REGION_LABEL = getRegionLabel()
  const REGION_OPTIONS = getRegions().map((r) => ({ value: r, label: r }))
  const [step, setStep] = useState(0)
  const [saving, setSaving] = useState(false)
  const [catalog, setCatalog] = useState<KeyCatalog | null>(null)
  const toast = useToast()
  const [d, setD] = useState<Draft>({
    name: '',
    slug: '',
    slugTouched: false,
    domainMode: 'subdomain',
    custom_domain: '',
    region: 'us',
    county: '',
    plan: 'standard',
    contact_name: '',
    contact_title: '',
    contact_email: '',
    contact_phone: '',
    address: '',
    notes: '',
    key_assignments: {},
  })

  useEffect(() => {
    api.keyCatalog().then(setCatalog).catch(() => setCatalog(null))
  }, [])

  function set<K extends keyof Draft>(k: K, v: Draft[K]) {
    setD((prev) => ({ ...prev, [k]: v }))
  }

  const effectiveSlug = d.slugTouched ? d.slug : slugify(d.name)
  const steps = ['Identity', 'Contact', 'Review']

  const canNext = () => {
    if (step === 0) return d.name.trim() && effectiveSlug
    return true
  }

  async function create() {
    if (!catalog) return
    setSaving(true)
    try {
      const body: Record<string, unknown> = {
        name: d.name.trim(),
        slug: effectiveSlug,
        region: d.region,
        county: d.county.trim() || null,
        plan: d.plan,
        contact_name: d.contact_name || null,
        contact_title: d.contact_title || null,
        contact_email: d.contact_email || null,
        contact_phone: d.contact_phone || null,
        address: d.address || null,
        notes: d.notes || null,
        // New towns inherit the program-wide key defaults; adjust per-town later.
        key_assignments: {},
      }
      await api.createTenant(body)
      toast.push(`${d.name} added — provision it next.`)
      onCreated()
    } catch (e) {
      toast.push((e as Error).message, 'error')
      setSaving(false)
    }
  }

  return (
    <Modal open onClose={onClose} title="Add a municipality" wide>
      {/* Stepper */}
      <div className="flex items-center gap-2 mb-6 flex-wrap">
        {steps.map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            <div
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm ${
                i === step
                  ? 'bg-indigo-500/20 text-indigo-200 border border-indigo-500/40'
                  : i < step
                    ? 'text-green-300'
                    : 'text-white/40'
              }`}
            >
              {i < step ? <Check className="w-4 h-4" /> : <span className="w-4 text-center">{i + 1}</span>}
              {s}
            </div>
            {i < steps.length - 1 && <span className="text-white/20">›</span>}
          </div>
        ))}
      </div>

      {/* Step 0: identity */}
      {step === 0 && (
        <div className="space-y-4">
          <Input
            label="Municipality name"
            required
            placeholder="e.g. Springfield, IL"
            value={d.name}
            onChange={(e) => set('name', e.target.value)}
            autoFocus
          />
          <Input
            label="Slug (DNS label — used for the subdomain, DB, bucket)"
            required
            placeholder="springfield"
            value={effectiveSlug}
            onChange={(e) => {
              set('slugTouched', true)
              set('slug', slugify(e.target.value))
            }}
            helperText="Lowercase letters, digits, hyphens. Immutable after creation."
          />
          <div className="grid grid-cols-2 gap-4">
            <Select label="Region" options={REGIONS} value={d.region} onChange={(e) => set('region', e.target.value)} />
            <Select label="Plan" options={PLANS} value={d.plan} onChange={(e) => set('plan', e.target.value)} />
          </div>
          {REGION_OPTIONS.length > 0 ? (
            <Select label={REGION_LABEL} options={[{ value: '', label: `— select ${REGION_LABEL.toLowerCase()} —` }, ...REGION_OPTIONS]} value={d.county} onChange={(e) => set('county', e.target.value)} />
          ) : (
            <Input label={REGION_LABEL} value={d.county} onChange={(e) => set('county', e.target.value)} helperText="Used for region-level analytics rollups." />
          )}
        </div>
      )}

      {/* Step 1: contact */}
      {step === 1 && (
        <div className="space-y-4">
          <div className="grid sm:grid-cols-2 gap-4">
            <Input label="Primary contact" placeholder="Jane Doe" value={d.contact_name} onChange={(e) => set('contact_name', e.target.value)} />
            <Input label="Title" placeholder="Town Clerk" value={d.contact_title} onChange={(e) => set('contact_title', e.target.value)} />
            <Input label="Email" type="email" placeholder="clerk@springfield.gov" value={d.contact_email} onChange={(e) => set('contact_email', e.target.value)} />
            <Input label="Phone" placeholder="(555) 010-0100" value={d.contact_phone} onChange={(e) => set('contact_phone', e.target.value)} />
          </div>
          <Input label="Mailing address" placeholder="1 Main St, Springfield, IL" value={d.address} onChange={(e) => set('address', e.target.value)} />
          <Textarea label="Notes (internal)" placeholder="Onboarding context, billing account, escalation path…" value={d.notes} onChange={(e) => set('notes', e.target.value)} />
        </div>
      )}

      {/* Step 2: review */}
      {step === 2 && catalog && (
        <div className="space-y-4">
          <ReviewRow label="Name" value={d.name} />
          <ReviewRow label="Address (hostname)" value={`${effectiveSlug}.${BASE_DOMAIN}`} />
          <ReviewRow label="Region · Plan" value={`${d.region} · ${d.plan}`} />
          {d.county && <ReviewRow label={REGION_LABEL} value={d.county} />}
          {d.contact_name && <ReviewRow label="Contact" value={`${d.contact_name}${d.contact_title ? `, ${d.contact_title}` : ''}`} />}

          <div className="p-3 rounded-xl bg-white/[0.03] border border-white/10">
            <div className="text-sm text-white/70 mb-2">API keys use your program defaults</div>
            <div className="flex flex-wrap gap-1.5">
              {catalog.assignable.map((s) => {
                const isState = s.default_owner !== 'town'
                return (
                  <Badge key={s.id} variant={isState ? 'info' : 'default'}>
                    {s.label}: {isState ? 'State' : 'Town'}
                  </Badge>
                )
              })}
            </div>
            <p className="text-xs text-white/40 mt-2">
              Change any of these on the town's <b>API keys</b> tab after it's created.
            </p>
          </div>

          <p className="text-white/40 text-sm">
            Creating the record does not deploy anything yet — you'll trigger provisioning from the
            town's page. A custom domain (instead of the subdomain) can be set on its Domain tab.
          </p>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between mt-8 pt-5 border-t border-white/10">
        <Button
          variant="ghost"
          onClick={() => (step === 0 ? onClose() : setStep((s) => s - 1))}
          leftIcon={step > 0 ? <ArrowLeft className="w-4 h-4" /> : undefined}
        >
          {step === 0 ? 'Cancel' : 'Back'}
        </Button>
        {step < steps.length - 1 ? (
          <Button onClick={() => setStep((s) => s + 1)} disabled={!canNext()}>
            Continue <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
        ) : (
          <Button onClick={create} isLoading={saving} leftIcon={<Check className="w-4 h-4" />}>
            Add municipality
          </Button>
        )}
      </div>
    </Modal>
  )
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 py-2 border-b border-white/5">
      <span className="text-white/50 text-sm">{label}</span>
      <span className="text-white text-sm font-medium text-right">{value}</span>
    </div>
  )
}

// ------------------------------------------------------------- Bulk import

/**
 * Paste CSV (or upload a .csv) with headers: name, slug, contact_email,
 * contact_name, latitude, longitude, tags (tags are ';'-separated). Each row is
 * created independently; results are reported per row.
 */
function BulkImport({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const toast = useToast()
  const [text, setText] = useState('name,slug,contact_email\n')
  const [results, setResults] = useState<BulkResultRow[] | null>(null)
  const [saving, setSaving] = useState(false)

  function parse(): Record<string, unknown>[] {
    const lines = text.trim().split(/\r?\n/).filter(Boolean)
    if (lines.length < 2) return []
    const headers = lines[0].split(',').map((h) => h.trim())
    return lines.slice(1).map((line) => {
      const cells = line.split(',')
      const row: Record<string, unknown> = {}
      headers.forEach((h, i) => {
        const v = (cells[i] || '').trim()
        if (!v) return
        if (h === 'latitude' || h === 'longitude') row[h] = Number(v)
        else if (h === 'tags') row[h] = v.split(';').map((t) => t.trim()).filter(Boolean)
        else row[h] = v
      })
      return row
    })
  }

  async function importRows() {
    const rows = parse()
    if (rows.length === 0) {
      toast.push('Add at least one data row under the header', 'error')
      return
    }
    setSaving(true)
    try {
      setResults(await api.bulkCreate(rows))
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    file.text().then(setText)
  }

  const okCount = results?.filter((r) => r.ok).length ?? 0

  return (
    <Modal open onClose={onClose} title="Bulk import municipalities" wide>
      {results ? (
        <div>
          <p className="text-white mb-3">
            Imported <b className="text-green-300">{okCount}</b> of {results.length} rows.
          </p>
          <div className="max-h-80 overflow-y-auto space-y-1">
            {results.map((r, i) => (
              <div key={i} className="flex items-center gap-2 text-sm py-1.5 border-b border-white/5">
                {r.ok ? <Check className="w-4 h-4 text-green-400" /> : <X className="w-4 h-4 text-red-400" />}
                <code className="text-white/70">{r.slug}</code>
                {!r.ok && <span className="text-red-300">{r.error}</span>}
              </div>
            ))}
          </div>
          <div className="flex justify-end mt-6">
            <Button onClick={onDone}>Done</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-white/60">
            Paste CSV with a header row. Columns: <code>name</code>, <code>slug</code>,{' '}
            <code>contact_name</code>, <code>contact_email</code>, <code>latitude</code>,{' '}
            <code>longitude</code>, <code>tags</code> (<code>;</code>-separated). Each row is created
            independently.
          </p>
          <label className="inline-flex items-center gap-2 text-sm text-indigo-300 hover:text-indigo-200 cursor-pointer">
            <Upload className="w-4 h-4" /> Upload a .csv
            <input type="file" accept=".csv,text/csv" className="hidden" onChange={onFile} />
          </label>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="font-mono !min-h-[180px] text-sm"
            aria-label="CSV data"
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button onClick={importRows} isLoading={saving} leftIcon={<Upload className="w-4 h-4" />}>
              Import
            </Button>
          </div>
        </div>
      )}
    </Modal>
  )
}
