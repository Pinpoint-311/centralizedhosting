import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { MapPin, Building2 } from 'lucide-react'
import { api } from '../lib/api'
import type { Tenant } from '../lib/types'
import { Badge, Card, EmptyState, Spinner, StatusBadge } from '../components/ui'
import { PageHeader } from '../components/Shell'
import { useToast } from '../components/Toast'

// Status → marker color (matches the dashboard palette)
const STATUS_COLOR: Record<string, string> = {
  active: '#22c55e',
  pending: '#3b82f6',
  provisioning: '#f59e0b',
  suspended: '#f59e0b',
  offline: '#94a3b8',
  failed: '#ef4444',
  decommissioned: '#6b7280',
}

const W = 960
const H = 560

/**
 * Albers equal-area conic projection for the continental U.S. — the standard
 * projection for national maps. No tiles, no map API key, works offline: the
 * government-appropriate choice (and it means the map itself isn't one of the
 * API keys a town has to provide).
 *
 * The view auto-fits to the onboarded towns (so a single state's municipalities
 * fill the frame) and falls back to the whole lower-48 when there are too few
 * points to define an extent.
 */
function useProjector(placed: Tenant[]) {
  return useMemo(() => {
    const d2r = Math.PI / 180
    const phi1 = 29.5 * d2r
    const phi2 = 45.5 * d2r
    const lat0 = 37.5 * d2r
    const lon0 = -96 * d2r
    const n = (Math.sin(phi1) + Math.sin(phi2)) / 2
    const C = Math.cos(phi1) ** 2 + 2 * n * Math.sin(phi1)
    const rho0 = Math.sqrt(C - 2 * n * Math.sin(lat0)) / n
    const raw = (latDeg: number, lonDeg: number): [number, number] => {
      const lat = latDeg * d2r
      const lon = lonDeg * d2r
      const theta = n * (lon - lon0)
      const rho = Math.sqrt(C - 2 * n * Math.sin(lat)) / n
      return [rho * Math.sin(theta), rho0 - rho * Math.cos(theta)]
    }

    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
    const acc = (lat: number, lon: number) => {
      const [x, y] = raw(lat, lon)
      minX = Math.min(minX, x); maxX = Math.max(maxX, x)
      minY = Math.min(minY, y); maxY = Math.max(maxY, y)
    }

    if (placed.length >= 2) {
      // Fit to the towns' bounding box (plus margin) so the state fills the view.
      for (const t of placed) acc(t.latitude as number, t.longitude as number)
      const mx = (maxX - minX) * 0.18 + 0.02
      const my = (maxY - minY) * 0.18 + 0.02
      minX -= mx; maxX += mx; minY -= my; maxY += my
    } else {
      // Whole lower-48 as a fallback.
      for (let lat = 24; lat <= 49.5; lat += 0.5)
        for (let lon = -125; lon <= -66; lon += 0.5) acc(lat, lon)
    }

    const pad = 24
    const s = Math.min((W - 2 * pad) / (maxX - minX), (H - 2 * pad) / (maxY - minY))
    const ox = pad + (W - 2 * pad - s * (maxX - minX)) / 2
    const oy = pad + (H - 2 * pad - s * (maxY - minY)) / 2
    const project = (latDeg: number, lonDeg: number): [number, number] => {
      const [x, y] = raw(latDeg, lonDeg)
      return [ox + s * (x - minX), oy + s * (maxY - y)] // north → up
    }
    return { project, bounds: { minX, maxX, minY, maxY } }
  }, [placed])
}

export function StateMap() {
  const toast = useToast()
  const navigate = useNavigate()
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [loading, setLoading] = useState(true)
  const [hover, setHover] = useState<string | null>(null)

  useEffect(() => {
    api
      .listTenants()
      .then(setTenants)
      .catch((e) => toast.push((e as Error).message, 'error'))
      .finally(() => setLoading(false))
  }, [])

  const placed = useMemo(
    () => tenants.filter((t) => t.latitude != null && t.longitude != null),
    [tenants],
  )
  const unplaced = tenants.filter((t) => t.latitude == null || t.longitude == null)
  const { project } = useProjector(placed)

  // Graticule at whole-degree steps that span the fitted view (clipped by SVG).
  const meridians: string[] = []
  for (let lon = -125; lon <= -66; lon += 2) {
    const pts: string[] = []
    for (let lat = 22; lat <= 52; lat += 1) pts.push(project(lat, lon).join(','))
    meridians.push(pts.join(' '))
  }
  const parallels: string[] = []
  for (let lat = 22; lat <= 52; lat += 2) {
    const pts: string[] = []
    for (let lon = -125; lon <= -66; lon += 1) pts.push(project(lat, lon).join(','))
    parallels.push(pts.join(' '))
  }

  if (loading) return <Spinner />

  const statusList = Array.from(new Set(placed.map((t) => t.status)))

  return (
    <div>
      <PageHeader
        title="State Map"
        subtitle="Where your onboarded municipalities are — an equal-area U.S. projection, no external map service."
      />

      {tenants.length === 0 ? (
        <Card>
          <EmptyState icon={<MapPin className="w-7 h-7" />} title="No municipalities to map yet" />
        </Card>
      ) : (
        <div className="grid lg:grid-cols-[1fr_18rem] gap-4">
          <Card className="!p-3 sm:!p-4">
            <div className="w-full overflow-hidden rounded-xl bg-white/[0.02] border border-white/10">
              <svg
                viewBox={`0 0 ${W} ${H}`}
                className="w-full h-auto"
                role="img"
                aria-label={`Map of ${placed.length} onboarded municipalities across the continental United States. A full list follows.`}
              >
                {/* graticule */}
                {parallels.map((p, i) => (
                  <polyline key={`p${i}`} points={p} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={1} />
                ))}
                {meridians.map((m, i) => (
                  <polyline key={`m${i}`} points={m} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={1} />
                ))}
                {/* markers */}
                {placed.map((t) => {
                  const [cx, cy] = project(t.latitude as number, t.longitude as number)
                  const color = STATUS_COLOR[t.status] || '#94a3b8'
                  const active = hover === t.id
                  return (
                    <g
                      key={t.id}
                      transform={`translate(${cx},${cy})`}
                      className="cursor-pointer"
                      onMouseEnter={() => setHover(t.id)}
                      onMouseLeave={() => setHover(null)}
                      onClick={() => navigate(`/towns/${t.id}`)}
                      role="button"
                      tabIndex={0}
                      aria-label={`${t.name}, status ${t.status}. Open details.`}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          navigate(`/towns/${t.id}`)
                        }
                      }}
                    >
                      <circle r={active ? 9 : 6} fill={color} opacity={0.9} />
                      <circle r={active ? 9 : 6} fill="none" stroke="white" strokeOpacity={0.5} strokeWidth={1.5} />
                      {active && (
                        <text x={11} y={4} fill="white" fontSize={13} style={{ paintOrder: 'stroke' }} stroke="rgba(0,0,0,0.6)" strokeWidth={3}>
                          {t.name}
                        </text>
                      )}
                    </g>
                  )
                })}
              </svg>
            </div>
            {statusList.length > 0 && (
              <div className="flex flex-wrap gap-3 mt-3 px-1">
                {statusList.map((s) => (
                  <span key={s} className="flex items-center gap-1.5 text-sm text-white/60">
                    <span className="w-3 h-3 rounded-full" style={{ background: STATUS_COLOR[s] || '#94a3b8' }} />
                    <span className="capitalize">{s}</span>
                  </span>
                ))}
              </div>
            )}
          </Card>

          <div className="space-y-4">
            <Card className="!p-4">
              <h3 className="font-semibold text-white mb-3">On the map ({placed.length})</h3>
              <ul className="space-y-1.5">
                {placed.map((t) => (
                  <li key={t.id}>
                    <button
                      onClick={() => navigate(`/towns/${t.id}`)}
                      className="w-full flex items-center gap-2 text-left px-2 py-1.5 rounded-lg hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                    >
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: STATUS_COLOR[t.status] || '#94a3b8' }} />
                      <span className="text-sm text-white truncate flex-1">{t.name}</span>
                      <StatusBadge status={t.status} />
                    </button>
                  </li>
                ))}
                {placed.length === 0 && <li className="text-sm text-white/40 px-2">None placed yet.</li>}
              </ul>
            </Card>

            {unplaced.length > 0 && (
              <Card className="!p-4">
                <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
                  <Building2 className="w-4 h-4" /> Not on the map ({unplaced.length})
                </h3>
                <p className="text-xs text-white/40 mb-3">Add latitude/longitude on a town's Domain &amp; contact tab to place it.</p>
                <div className="flex flex-wrap gap-1.5">
                  {unplaced.map((t) => (
                    <button key={t.id} onClick={() => navigate(`/towns/${t.id}`)} className="focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 rounded-full">
                      <Badge>{t.name}</Badge>
                    </button>
                  ))}
                </div>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
