/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { MapPin, Building2, AlertTriangle } from 'lucide-react'
import { api } from '../lib/api'
import type { GeoFeatureCollection } from '../lib/types'
import { Badge, Card, EmptyState, Spinner, StatusBadge, STATUS_COLOR } from '../components/ui'
import { PageHeader } from '../components/Shell'
import { getMapsApiKey, getMapsMapId } from '../lib/config'
import { loadGoogleMaps, extendBoundsFromFeature } from '../lib/googlemaps'
import { useToast } from '../components/Toast'

// Dark map style so the panel's map matches the indigo glass UI (used only when
// no Cloud Map ID is configured; a Map ID takes over styling when present).
const DARK_STYLE: any[] = [
  { elementType: 'geometry', stylers: [{ color: '#1a1633' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#1a1633' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#9aa0c3' }] },
  { featureType: 'poi', stylers: [{ visibility: 'off' }] },
  { featureType: 'transit', stylers: [{ visibility: 'off' }] },
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#2a2450' }] },
  { featureType: 'road', elementType: 'labels', stylers: [{ visibility: 'off' }] },
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#12102a' }] },
  { featureType: 'administrative', elementType: 'geometry', stylers: [{ color: '#3a3470' }] },
]

export function StateMap() {
  const toast = useToast()
  const navigate = useNavigate()
  const mapEl = useRef<HTMLDivElement>(null)
  const mapObj = useRef<any>(null)
  const [fc, setFc] = useState<GeoFeatureCollection | null>(null)
  const [loading, setLoading] = useState(true)
  const [mapError, setMapError] = useState('')
  const apiKey = getMapsApiKey()

  useEffect(() => {
    api
      .gisMap()
      .then(setFc)
      .catch((e) => toast.push((e as Error).message, 'error'))
      .finally(() => setLoading(false))
  }, [])

  // Build/refresh the Google map once data + SDK are ready.
  useEffect(() => {
    if (!fc || !apiKey || !mapEl.current) return
    let cancelled = false
    loadGoogleMaps(apiKey)
      .then(() => {
        if (cancelled || !mapEl.current) return
        const g = window.google
        const mapId = getMapsMapId()
        const map =
          mapObj.current ||
          new g.maps.Map(mapEl.current, {
            center: { lat: 40.3, lng: -74.5 },
            zoom: 8,
            mapTypeControl: false,
            streetViewControl: false,
            fullscreenControl: true,
            zoomControl: true,
            ...(mapId ? { mapId } : { styles: DARK_STYLE }),
          })
        mapObj.current = map

        // Reset the data layer, then add every town as a Feature.
        map.data.forEach((f: any) => map.data.remove(f))
        map.data.addGeoJson(fc)

        // Color each town by status; polygons filled, points as circles.
        map.data.setStyle((feature: any) => {
          const status = feature.getProperty('status') || 'active'
          const color = STATUS_COLOR[status] || '#94a3b8'
          const isPoint = feature.getGeometry()?.getType() === 'Point'
          if (isPoint) {
            return {
              icon: {
                path: g.maps.SymbolPath.CIRCLE,
                scale: 7,
                fillColor: color,
                fillOpacity: 0.95,
                strokeColor: '#ffffff',
                strokeWeight: 1.5,
              },
              title: feature.getProperty('name'),
            }
          }
          return {
            fillColor: color,
            fillOpacity: 0.18,
            strokeColor: color,
            strokeWeight: 2,
            strokeOpacity: 0.9,
          }
        })

        // Hover emphasis.
        map.data.addListener('mouseover', (e: any) => {
          if (e.feature.getGeometry()?.getType() !== 'Point')
            map.data.overrideStyle(e.feature, { fillOpacity: 0.38, strokeWeight: 3 })
          map.getDiv().style.cursor = 'pointer'
        })
        map.data.addListener('mouseout', () => {
          map.data.revertStyle()
          map.getDiv().style.cursor = ''
        })
        // Click → open the town.
        map.data.addListener('click', (e: any) => {
          const id = e.feature.getProperty('id')
          if (id) navigate(`/towns/${id}`)
        })

        // Fit to all features.
        const bounds = new g.maps.LatLngBounds()
        map.data.forEach((f: any) => extendBoundsFromFeature(bounds, f))
        if (!bounds.isEmpty()) {
          map.fitBounds(bounds, 48)
          // Don't zoom absurdly close when there's a single small town.
          const once = g.maps.event.addListenerOnce(map, 'idle', () => {
            if (map.getZoom() > 13) map.setZoom(13)
          })
          void once
        }
      })
      .catch((e) => setMapError((e as Error).message))
    return () => {
      cancelled = true
    }
  }, [fc, apiKey, navigate])

  if (loading) return <Spinner />

  const feats = fc?.features || []
  const placed = feats.length
  const withBoundary = feats.filter((f) => f.properties.has_boundary).length
  const statusList = Array.from(new Set(feats.map((f) => f.properties.status)))

  return (
    <div>
      <PageHeader
        title="State Map"
        subtitle="Onboarded municipalities and their boundaries — public geography from OpenStreetMap, never resident data."
      />

      {placed === 0 ? (
        <Card>
          <EmptyState
            icon={<MapPin className="w-7 h-7" />}
            title="No municipalities to map yet"
            hint="Add a town, then attach its boundary from the Domain & contact tab."
          />
        </Card>
      ) : (
        <div className="grid lg:grid-cols-[1fr_18rem] gap-4">
          <Card className="!p-3 sm:!p-4">
            {!apiKey ? (
              <div className="rounded-xl bg-amber-500/10 border border-amber-500/25 p-6 text-center">
                <AlertTriangle className="w-8 h-8 text-amber-300 mx-auto mb-2" />
                <p className="text-white font-medium">Map key not configured</p>
                <p className="text-sm text-white/60 mt-1 max-w-md mx-auto">
                  Set <code>MAPS_API_KEY</code> (a referrer-restricted Google Maps JS key) on the
                  control plane to render the live map. Boundaries are already stored — the list on
                  the right stays available regardless.
                </p>
              </div>
            ) : mapError ? (
              <div className="rounded-xl bg-red-500/10 border border-red-500/25 p-6 text-center">
                <AlertTriangle className="w-8 h-8 text-red-300 mx-auto mb-2" />
                <p className="text-white font-medium">Map failed to load</p>
                <p className="text-sm text-white/60 mt-1">{mapError}</p>
              </div>
            ) : (
              <div
                ref={mapEl}
                className="w-full rounded-xl overflow-hidden border border-white/10"
                style={{ height: 520 }}
                role="img"
                aria-label={`Map of ${placed} onboarded municipalities. A full list follows.`}
              />
            )}
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
              <h3 className="font-semibold text-white mb-1">On the map ({placed})</h3>
              <p className="text-xs text-white/40 mb-3">{withBoundary} with a boundary polygon.</p>
              <ul className="space-y-1.5">
                {feats.map((f) => (
                  <li key={f.properties.id}>
                    <button
                      onClick={() => navigate(`/towns/${f.properties.id}`)}
                      className="w-full flex items-center gap-2 text-left px-2 py-1.5 rounded-lg hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                    >
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: STATUS_COLOR[f.properties.status] || '#94a3b8' }} />
                      <span className="text-sm text-white truncate flex-1">{f.properties.name}</span>
                      {!f.properties.has_boundary && (
                        <span title="Point only — no boundary yet"><MapPin className="w-3.5 h-3.5 text-white/30" /></span>
                      )}
                      <StatusBadge status={f.properties.status} />
                    </button>
                  </li>
                ))}
              </ul>
            </Card>

            <Card className="!p-4">
              <h3 className="font-semibold text-white mb-1 flex items-center gap-2">
                <Building2 className="w-4 h-4" /> Boundaries
              </h3>
              <p className="text-xs text-white/50">
                Attach a town's real boundary from its <b>Domain &amp; contact</b> tab — search
                OpenStreetMap and save the polygon. Towns without one show as a point.
              </p>
              {placed - withBoundary > 0 && (
                <div className="mt-2">
                  <Badge variant="warning">{placed - withBoundary} without a boundary</Badge>
                </div>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}
