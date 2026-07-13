import type {
  Alert,
  AuditEntry,
  BreakGlassGrant,
  BulkResultRow,
  CostSummary,
  FleetSummary,
  KeyCatalog,
  ProvisionJob,
  Release,
  Rollout,
  SecretOut,
  SlaSummary,
  Tenant,
  TownRequest,
  WhoAmI,
} from './types'

const TOKEN_KEY = 'pp311_panel_token'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(t: string) {
  localStorage.setItem(TOKEN_KEY, t)
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'X-Panel-Token': getToken() }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const resp = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (resp.status === 204) return undefined as T
  const text = await resp.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (!resp.ok) {
    const detail =
      (data as { detail?: string } | null)?.detail ||
      (typeof data === 'string' ? data : '') ||
      `Request failed (${resp.status})`
    throw new ApiError(resp.status, Array.isArray(detail) ? JSON.stringify(detail) : String(detail))
  }
  return data as T
}

export const api = {
  // auth probe — any authenticated call works; we use the tenant list
  verifyToken: () => req<Tenant[]>('GET', '/api/tenants'),

  // tenants
  listTenants: () => req<Tenant[]>('GET', '/api/tenants'),
  getTenant: (id: string) => req<Tenant>('GET', `/api/tenants/${id}`),
  createTenant: (body: Record<string, unknown>) => req<Tenant>('POST', '/api/tenants', body),
  updateTenant: (id: string, body: Record<string, unknown>) =>
    req<Tenant>('PATCH', `/api/tenants/${id}`, body),
  provision: (id: string) => req<ProvisionJob>('POST', `/api/tenants/${id}/provision`),
  listJobs: (id: string) => req<ProvisionJob[]>('GET', `/api/tenants/${id}/jobs`),
  suspend: (id: string) => req<Tenant>('POST', `/api/tenants/${id}/suspend`),
  resume: (id: string) => req<Tenant>('POST', `/api/tenants/${id}/resume`),
  takeOffline: (id: string) => req<Tenant>('POST', `/api/tenants/${id}/take-offline`),
  bringOnline: (id: string) => req<Tenant>('POST', `/api/tenants/${id}/bring-online`),
  decommission: (id: string, slug: string) =>
    req<Tenant>('POST', `/api/tenants/${id}/decommission?confirm_slug=${encodeURIComponent(slug)}`),

  // key responsibility
  keyCatalog: () => req<KeyCatalog>('GET', '/api/key-catalog'),
  getAssignments: (id: string) =>
    req<{ assignments: Record<string, string> }>('GET', `/api/tenants/${id}/key-assignments`),
  setAssignments: (id: string, assignments: Record<string, string>) =>
    req<{ assignments: Record<string, string> }>('PUT', `/api/tenants/${id}/key-assignments`, {
      assignments,
    }),

  // shared state credential pool (entered once, injected into shared towns)
  listStateCredentials: () => req<SecretOut[]>('GET', '/api/state-credentials'),
  putStateCredential: (key: string, value: string) =>
    req<SecretOut>('PUT', `/api/state-credentials/${encodeURIComponent(key)}`, { value }),
  deleteStateCredential: (key: string) =>
    req<void>('DELETE', `/api/state-credentials/${encodeURIComponent(key)}`),

  // brokered per-town secrets
  listSecrets: (id: string) => req<SecretOut[]>('GET', `/api/tenants/${id}/secrets`),
  putSecret: (id: string, key: string, value: string) =>
    req<SecretOut>('PUT', `/api/tenants/${id}/secrets/${encodeURIComponent(key)}`, { value }),
  deleteSecret: (id: string, key: string) =>
    req<void>('DELETE', `/api/tenants/${id}/secrets/${encodeURIComponent(key)}`),

  // releases & rollouts
  listReleases: () => req<Release[]>('GET', '/api/releases'),
  publishRelease: (body: Record<string, unknown>) => req<Release>('POST', '/api/releases', body),
  listRollouts: () => req<Rollout[]>('GET', '/api/rollouts'),
  startRollout: (body: Record<string, unknown>) => req<Rollout>('POST', '/api/rollouts', body),
  promoteRollout: (id: string) => req<Rollout>('POST', `/api/rollouts/${id}/promote`),
  rollbackRollout: (id: string) => req<Rollout>('POST', `/api/rollouts/${id}/rollback`),

  // fleet
  fleetSummary: () => req<FleetSummary>('GET', '/api/fleet/summary'),
  fleetRefresh: () => req<{ polled: number; reachable: number }>('POST', '/api/fleet/refresh'),

  // break-glass
  listGrants: () => req<BreakGlassGrant[]>('GET', '/api/breakglass'),
  issueGrant: (body: Record<string, unknown>) =>
    req<BreakGlassGrant>('POST', '/api/breakglass', body),
  revokeGrant: (id: string) => req<BreakGlassGrant>('POST', `/api/breakglass/${id}/revoke`),

  // audit
  audit: (params = '') => req<AuditEntry[]>('GET', `/api/audit${params}`),
  auditVerify: () => req<{ ok: boolean; entries?: number; broken_at_seq?: number; reason?: string }>('GET', '/api/audit/verify'),

  // identity / admin
  whoami: () => req<WhoAmI>('GET', '/api/whoami'),
  reencryptSecrets: () => req<{ reencrypted: number; key_version: number }>('POST', '/api/maintenance/reencrypt-secrets'),

  // insights
  cost: () => req<CostSummary>('GET', '/api/cost/summary'),
  sla: (days = 30) => req<SlaSummary>('GET', `/api/sla/summary?days=${days}`),
  alerts: (openOnly = true) => req<Alert[]>('GET', `/api/alerts?open_only=${openOnly}`),
  evaluateAlerts: () => req<{ new_alerts: number }>('POST', '/api/alerts/evaluate'),
  ackAlert: (id: string) => req<Alert>('POST', `/api/alerts/${id}/ack`),

  // bulk onboarding
  bulkCreate: (tenants: Record<string, unknown>[]) =>
    req<BulkResultRow[]>('POST', '/api/tenants/bulk', { tenants }),

  // stack preview
  stackPreview: (id: string) =>
    req<{ version: string; compose: string; env: string }>('GET', `/api/tenants/${id}/stack-preview`),

  // self-service requests
  listRequests: (status = '') =>
    req<TownRequest[]>('GET', `/api/requests${status ? `?status=${status}` : ''}`),
  submitRequest: (body: Record<string, unknown>) => req<TownRequest>('POST', '/api/requests', body),
  approveRequest: (id: string) => req<Tenant>('POST', `/api/requests/${id}/approve`),
  rejectRequest: (id: string) => req<TownRequest>('POST', `/api/requests/${id}/reject`),
}
