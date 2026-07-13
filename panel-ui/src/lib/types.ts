export type TenantStatus =
  | 'pending'
  | 'provisioning'
  | 'active'
  | 'suspended'
  | 'failed'
  | 'decommissioned'

export interface Tenant {
  id: string
  slug: string
  name: string
  subdomain: string
  custom_domain: string | null
  region: string
  plan: string
  status: TenantStatus
  contact_name: string | null
  contact_email: string | null
  contact_phone: string | null
  contact_title: string | null
  address: string | null
  notes: string | null
  key_assignments: Record<string, string>
  running_version: string | null
  target_version: string | null
  db_name: string | null
  kms_key_ref: string | null
  storage_bucket: string | null
  backend_port: number | null
  frontend_port: number | null
  created_at: string
  updated_at: string
}

export interface ProvisionStep {
  position: number
  name: string
  status: string
  detail: string | null
}

export interface ProvisionJob {
  id: string
  tenant_id: string
  status: string
  error: string | null
  onboarding_link: string | null
  created_at: string
  finished_at: string | null
  steps: ProvisionStep[]
}

export interface AssignableService {
  id: string
  label: string
  description: string
  keys: string[]
  default_owner: string
  state_hint: string
}

export interface KeyCatalog {
  assignable: AssignableService[]
  infrastructure: string[]
  infrastructure_prefixes: string[]
  owners: string[]
}

export interface SecretOut {
  key_name: string
  updated_at: string
}

export interface Release {
  id: string
  version: string
  backend_image: string
  frontend_image: string
  db_revision: string | null
  min_db_revision: string | null
  notes: string | null
  published_at: string
}

export interface RolloutStep {
  tenant_id: string
  position: number
  phase: string
  status: string
  previous_version: string | null
  detail: string | null
}

export interface Rollout {
  id: string
  release_id: string
  status: string
  canary_count: number
  error: string | null
  created_at: string
  finished_at: string | null
  steps: RolloutStep[]
}

export interface FleetTown {
  id: string
  slug: string
  name: string
  host: string
  status: TenantStatus
  running_version: string | null
  target_version: string | null
  drift: boolean
  reachable: boolean | null
  last_seen: string | null
  telemetry: Record<string, unknown> | null
}

export interface FleetSummary {
  tenants_total: number
  status_counts: Record<string, number>
  version_counts: Record<string, number>
  latest_release: string | null
  drifted: number
  towns: FleetTown[]
}

export interface BreakGlassGrant {
  id: string
  tenant_id: string
  actor: string
  reason: string
  expires_at: string
  revoked_at: string | null
  created_at: string
  token?: string
}

export interface AuditEntry {
  id: string
  actor: string
  action: string
  tenant_id: string | null
  detail: Record<string, unknown>
  created_at: string
}
