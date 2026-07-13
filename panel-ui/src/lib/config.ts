let baseDomain = '311.example.gov'

export function getBaseDomain(): string {
  return baseDomain
}

export async function loadPanelConfig(): Promise<void> {
  try {
    const resp = await fetch('/api/panel-config')
    if (resp.ok) {
      const cfg = await resp.json()
      if (cfg.base_domain) baseDomain = cfg.base_domain
    }
  } catch {
    // keep the default; the panel still works, hostnames just use the fallback
  }
}
