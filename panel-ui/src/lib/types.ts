export type TenantStatus =
  | 'pending'
  | 'provisioning'
  | 'active'
  | 'suspended'
  | 'offline'
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
  latitude: number | null
  longitude: number | null
  county: string | null
  tags: string[]
  managed_settings: Record<string, unknown>
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
  backend_digest: string | null
  frontend_digest: string | null
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
  seq: number
  actor: string
  action: string
  tenant_id: string | null
  detail: Record<string, unknown>
  created_at: string
  entry_hash: string
}

export type Role = 'viewer' | 'operator' | 'approver' | 'admin'

export interface WhoAmI {
  actor: string
  role: Role
  key_provider: string
  require_signed_images: boolean
}

export interface CostTownService {
  service: string
  bucket: string
  cost: number
  borne_by: 'state' | 'town'
}
export interface CostTown {
  id: string
  slug: string
  name: string
  state_borne: number
  town_borne: number
  total: number
  services: CostTownService[]
}
export interface CostSummary {
  fleet_total: number
  state_borne: number
  town_borne: number
  by_service: Record<string, number>
  towns: CostTown[]
  note: string
}

export interface SlaTown {
  id: string
  slug: string | null
  name: string | null
  checks: number
  reachable: number
  uptime_percent: number | null
  incidents: number
}
export interface SlaSummary {
  period_days: number
  towns: SlaTown[]
}

export interface Alert {
  id: string
  tenant_id: string | null
  tenant_slug: string | null
  kind: string
  severity: 'info' | 'warning' | 'critical'
  message: string
  created_at: string
  acknowledged_at: string | null
  acknowledged_by: string | null
}

export interface BulkResultRow {
  slug: string
  ok: boolean
  id: string | null
  error: string | null
}

export interface TownRequest {
  id: string
  ref_code: string | null
  name: string
  requested_slug: string | null
  county: string | null
  contact_name: string | null
  contact_email: string | null
  contact_phone: string | null
  message: string | null
  details: Record<string, unknown>
  key_preferences: Record<string, string>
  status: 'pending' | 'approved' | 'rejected'
  tenant_id: string | null
  created_at: string
  decided_at: string | null
  decided_by: string | null
}

export interface Analytics {
  program_total_requests: number
  by_canonical_category: Record<string, number>
  regions: Record<string, string | number | null>[]
  unmapped_requests: number
  min_cell: number
  towns_withheld_for_privacy: number
  note: string
}

export interface ManagedField {
  key: string
  label: string
  type: 'int' | 'bool' | 'str'
  default: unknown
  help: string
  group: string
  scope: 'state' | 'shared'
}

export interface LegalHold {
  state_hold: boolean
  town_hold: boolean
  effective: boolean
  pushed_to_instance?: boolean
}

export interface ComplianceTown {
  id: string
  slug: string
  name: string
  county: string | null
  checks: Record<string, boolean>
  score: number
  legal_hold: boolean
}
export interface ComplianceSummary {
  towns: ComplianceTown[]
  total: number
  passing_by_check: Record<string, number>
}

export interface Transparency {
  town: { name: string; slug: string; host: string }
  metadata_panel_holds: string[]
  panel_never_holds: string[]
  state_access_events: { action: string; actor: string; at: string; detail: Record<string, unknown> }[]
  break_glass_grants: { actor: string; reason: string; at: string; expires_at: string; revoked: boolean }[]
}

export interface PublicStatus {
  program: string
  overall: 'operational' | 'maintenance' | 'incident'
  municipalities_operational: number
  municipalities_total: number
  announcements: { title: string; body: string | null; severity: string; starts_at: string | null; ends_at: string | null }[]
}

export interface Announcement2 {
  id: string
  title: string
  body: string | null
  severity: string
  active: boolean
  starts_at: string | null
  ends_at: string | null
  created_at: string
  created_by: string | null
}
