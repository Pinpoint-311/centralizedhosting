let baseDomain = '311.example.gov'
let regionLabel = 'County'
let regions: string[] = []
let publicRequestsEnabled = false

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

export async function loadPanelConfig(): Promise<void> {
  try {
    const resp = await fetch('/api/panel-config')
    if (resp.ok) {
      const cfg = await resp.json()
      if (cfg.base_domain) baseDomain = cfg.base_domain
      if (cfg.region_label) regionLabel = cfg.region_label
      if (Array.isArray(cfg.regions)) regions = cfg.regions
      publicRequestsEnabled = !!cfg.public_requests_enabled
    }
  } catch {
    // keep defaults; the panel still works, hostnames just use the fallback
  }
}
