let baseDomain = '311.example.gov'
let regionLabel = 'County'
let regions: string[] = []
let publicRequestsEnabled = false
let mapsApiKey = ''
let mapsMapId = ''

export function getBaseDomain(): string {
  return baseDomain
}
export function getRegionLabel(): string {
  return regionLabel
}
/** Pluralize the region label (e.g. "County" → "Counties", "Region" → "Regions"). */
export function getRegionLabelPlural(): string {
  return /y$/i.test(regionLabel) ? regionLabel.replace(/y$/i, 'ies') : `${regionLabel}s`
}
export function getRegions(): string[] {
  return regions
}
export function publicRequestsOn(): boolean {
  return publicRequestsEnabled
}
export function getMapsApiKey(): string {
  return mapsApiKey
}
export function getMapsMapId(): string {
  return mapsMapId
}

export async function loadPanelConfig(): Promise<void> {
  try {
    const resp = await fetch('/api/panel-config')
    if (resp.ok) {
      const cfg = await resp.json()
      if (cfg.base_domain) baseDomain = cfg.base_domain
      if (cfg.region_label) regionLabel = cfg.region_label
      if (Array.isArray(cfg.regions)) regions = cfg.regions
      publicRequestsEnabled = !!cfg.public_requests_enabled
      if (cfg.maps_api_key) mapsApiKey = cfg.maps_api_key
      if (cfg.maps_map_id) mapsMapId = cfg.maps_map_id
    }
  } catch {
    // keep defaults; the panel still works, hostnames just use the fallback
  }
}
