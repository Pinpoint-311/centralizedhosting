export type TenantStatus =
  | 'pending'
  | 'provisioning'
  | 'active'
  | 'suspended'
  | 'offline'
  | 'failed'
  | 'migrating'
  | 'migrated'
  | 'decommissioned'

export interface PlatformConfig {
  platform_name: string
  tagline: string
  logo_url: string | null
  primary_color: string | null
  support_email: string | null
  org_legal_name: string | null
  org_type: string
  jurisdiction: string | null
  contact_name: string | null
  contact_email: string | null
  contact_phone: string | null
  address: string | null
  website: string | null
}

export interface SystemHealth {
  version: string
  checks: Record<string, { ok: boolean; detail: string }>
  background_loops: Record<string, number>
  fleet: { total: number; active: number }
}

export interface PostureControl {
  key: string
  label: string
  enabled: boolean
  /** Severity of the gap when the control is OFF; 'ok' when enabled. */
  severity: 'ok' | 'warning' | 'info'
  /** What the control does when on, or what it exposes when off. */
  detail: string
}
export interface PostureSummary {
  enabled: number
  total: number
  warnings: number
}
export interface SystemConfig {
  deployment: Record<string, unknown>
  posture: PostureControl[]
  summary: PostureSummary
}

export interface Operators {
  operators: { actor: string; actions: number; last_action_at: string | null }[]
  role_map: Record<string, string>
  default_role: string
  sso_enabled: boolean
  you: { actor: string; role: string }
}

export interface BackupRecord {
  id: string
  kind: string
  status: string
  path: string | null
  size_bytes: number
  detail: string | null
  created_at: string | null
}

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
  auth_method?: 'sso' | 'token'
  kms_provider: string
  kms_backend: string
  require_signed_images: boolean
}

// Uptime monitoring — the app's UptimeStats / UptimeHistory shapes.
export interface UptimeStats {
  services: Record<string, Record<'24h' | '7d' | '30d', { uptime_percent: number; checks: number; healthy: number }>>
}
export interface UptimeHistory {
  period_hours: number
  since: string
  services: Record<string, { status: string; response_time_ms: number | null; error: string | null; checked_at: string }[]>
}

export interface RetentionState {
  code: string
  name: string
  retention_days: number
  retention_years: number
  source: string
  public_records_law: string
}
export interface RetentionPolicy {
  state_code: string
  policy: RetentionState & { state_code: string }
  override_days: number | null
  effective_days: number
  mode: 'anonymize' | 'delete'
  stats: { towns_covered: number }
}

export interface ProactiveCheck {
  key: string
  label: string
  status: 'ok' | 'warning' | 'critical' | 'unknown'
  value: number | null
  message: string
  action: string
}
export interface ProactiveHealth {
  overall_status: 'ok' | 'warning' | 'critical'
  summary: { level: string; label: string; detail: string }
  checks: ProactiveCheck[]
  timestamp: string
}

// Service-provider types — the app's contract verbatim, so the ported
// ServiceProviders component compiles unchanged against the control plane.
export interface ProviderFieldSpec {
  key: string
  label: string
  secret?: boolean
}

export interface ProviderModelSpec {
  id: string
  label: string
  discovered?: boolean // newly found live, not in the curated list
}

export interface ProviderInfo {
  provider: string
  name: string
  description?: string
  boundary?: string
  models?: ProviderModelSpec[]
  default_model?: string
  credential_fields: ProviderFieldSpec[]
  field_help?: Record<string, string>
  models_source?: 'live' | 'curated'
  models_fetched_at?: number | null // epoch seconds
}

export interface ProviderCatalog {
  current_provider: string
  default_provider?: string
  current_model?: string | null
  current_model_available?: boolean
  configured?: Record<string, boolean>
  providers: ProviderInfo[]
}

export interface AIModelRefreshResult {
  provider: string
  models: ProviderModelSpec[]
  source: 'live' | 'curated'
  fetched_at?: number | null
  current_model?: string | null
  current_model_available?: boolean
}

export interface ProviderSave {
  provider: string
  model?: string
  settings?: Record<string, string>
}

export interface CloudProfileOption {
  id: string
  label: string
  boundary: string
  ai: string
  translation: string
  secrets: string
  kms: string
  email: string
  sms: string
  identity_recommended: string
}

export interface CloudProfileComponents {
  ai: string
  translation: string
  secrets: string
  kms: string
  identity: string
  email: string
  sms: string
}

export interface CloudProfileState {
  profile: 'google' | 'azure' | 'aws' | 'mixed'
  managed: boolean
  components: CloudProfileComponents
  maps: { provider: string; locked: boolean; label: string }
  profiles: CloudProfileOption[]
}

export interface CloudProfileResult {
  ok: boolean
  profile: string
  components: { ai: string; translation: string; secrets: string; kms: string; email: string; sms: string }
  identity_recommended: string
  identity_applied: boolean
  warnings: string[]
}

export interface AuthStatus {
  /** App-compatible field name: any identity provider is configured. */
  auth0_configured: boolean
  provider: string | null
  message: string
  /** First-run password sign-in is still permitted (no IdP configured yet). */
  bootstrap_available: boolean
}

export interface PanelUser {
  id: number | null
  username: string
  email: string | null
  full_name: string | null
  role: string
  is_active: boolean
  has_password?: boolean
  auth?: 'sso' | 'password' | 'invited'
  created_at?: string | null
  last_login_at?: string | null
  via?: 'user' | 'token'
}

export interface FederationConfig {
  enabled: boolean
  provider: string
  issuer: string | null
  client_id: string | null
  client_secret_set: boolean
  groups_claim: string
  group_role_map: Record<string, Role>
  default_role: Role
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

// GIS / State Map
export interface GeoFeature {
  type: 'Feature'
  geometry: { type: string; coordinates: unknown }
  properties: {
    // 'jurisdiction' marks the hosting organization's own outline (the base
    // layer). Municipality features carry the town fields below instead.
    kind?: 'jurisdiction'
    id: string
    name: string
    slug: string
    status: string
    county: string | null
    has_boundary: boolean
  }
}

export interface GeoFeatureCollection {
  type: 'FeatureCollection'
  features: GeoFeature[]
  placed?: number
  total?: number
}

export interface OsmResult {
  osm_id: number
  display_name: string
  type: string | null
  class: string | null
  lat: string | null
  lon: string | null
  geojson: unknown
}
