// ─── Enums ────────────────────────────────────────────────────────────────────

export type DeviceType =
  | "door_station"
  | "home_station"
  | "guard_station"
  | "sip_client"
  | "camera";

export type UnlockMethod = "http_get" | "http_post" | "sip_dtmf" | "none";

export type ActivityAction =
  | "device_created"
  | "device_updated"
  | "device_deleted"
  | "unlock_test"
  | "connection_test"
  | "login"
  | "rule_created"
  | "rule_updated"
  | "rule_deleted"
  | "door_call"
  | "door_call_end";

// ─── Auth ─────────────────────────────────────────────────────────────────────

export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface User {
  id: number;
  username: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
}

// ─── Device ───────────────────────────────────────────────────────────────────

export interface Device {
  id: number;
  name: string;
  device_type: DeviceType;
  ip_address: string | null;
  web_port: number | null;
  enabled: boolean;
  notes: string | null;
  // Cloud mirror
  mac_address: string | null;
  model: string | null;
  entrance_id: number | null;
  cloud_id: number | null;
  cloud_synced: boolean;
  last_cloud_sync_error: string | null;
  // SIP
  sip_enabled: boolean;
  sip_account: string | null;
  sip_password: string | null;
  sip_server: string | null;
  sip_port: number | null;
  sip_proxy: string | null;
  rtsp_enabled: boolean;
  rtsp_url: string | null;
  anpr_enabled: boolean;
  unlock_enabled: boolean;
  unlock_method: UnlockMethod;
  unlock_url: string | null;
  unlock_username: string | null;
  unlock_password: string | null;
  apartment_id: number | null;
  is_online: boolean | null;
  last_seen: string | null;
  created_at: string;
  updated_at: string;
}

export type DeviceCreate = Omit<
  Device,
  | "id"
  | "cloud_id"
  | "cloud_synced"
  | "last_cloud_sync_error"
  | "is_online"
  | "last_seen"
  | "created_at"
  | "updated_at"
> & {
  // entrance_id is required on create (backend validates 422 otherwise).
  entrance_id: number;
};
export type DeviceUpdate = Partial<DeviceCreate>;

export interface DeviceListOut {
  items: Device[];
  total: number;
}

// ─── Routing Rules ────────────────────────────────────────────────────────────

export interface RoutingRule {
  id: number;
  name: string;
  call_code: string;
  source_device_id: number | null;
  target_device_id: number | null;
  target_sip_account: string | null;
  enabled: boolean;
  priority: number;
  notes: string | null;
  source_device: Device | null;
  target_device: Device | null;
  created_at: string;
  updated_at: string;
}

export type RoutingRuleCreate = Omit<
  RoutingRule,
  "id" | "source_device" | "target_device" | "created_at" | "updated_at"
>;
export type RoutingRuleUpdate = Partial<RoutingRuleCreate>;

export interface RoutingRuleListOut {
  items: RoutingRule[];
  total: number;
}

// ─── Plate whitelist (parking ANPR) ───────────────────────────────────────────

export interface Plate {
  id: number;
  plate: string;
  owner_name: string | null;
  apartment_id: number | null;
  entrance_id: number | null;
  enabled: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export type PlateCreate = Omit<Plate, "id" | "created_at" | "updated_at">;
export type PlateUpdate = Partial<PlateCreate>;

export interface PlateListOut {
  items: Plate[];
  total: number;
}

export interface PlateAccessLog {
  id: number;
  device_id: number | null;
  plate: string;
  plate_raw: string | null;
  matched: boolean;
  whitelist_id: number | null;
  action: string;
  detail: string | null;
  created_at: string;
}

export interface PlateAccessLogListOut {
  items: PlateAccessLog[];
  total: number;
}

// ─── Dashboard ────────────────────────────────────────────────────────────────

export interface ActivityLog {
  id: number;
  action: ActivityAction;
  actor: string | null;
  device_id: number | null;
  detail: string | null;
  success: boolean;
  created_at: string;
}

export interface DashboardSummary {
  total_devices: number;
  online_devices: number;
  offline_devices: number;
  unknown_devices: number;
  door_stations: number;
  home_stations: number;
  guard_stations: number;
  sip_clients: number;
  cameras: number;
  total_routing_rules: number;
  active_routing_rules: number;
  recent_activity: ActivityLog[];
}

// ─── Actions ──────────────────────────────────────────────────────────────────

export interface ActionResult {
  success: boolean;
  message: string;
  detail: string | null;
  latency_ms: number | null;
}

// ─── System ───────────────────────────────────────────────────────────────────

export interface SystemInfo {
  server_ip: string;
  database_url_safe: string;
  app_env: string;
  version: string;
  asterisk_integration: string;
  rtsp_integration: string;
}

export interface HealthOut {
  status: string;
  version: string;
  environment: string;
}

// ─── SIP ──────────────────────────────────────────────────────────────────────

export interface SipApplyRequest {
  sip_account: string;
  sip_password: string;
  update_device?: boolean;
}

export interface AsteriskHealth {
  status: string; // "configured" | "not_configured"
  mode: string; // "local" | "ssh"
  pjsip_conf: string;
  pjsip_readable: boolean;
  detail: string;
}

// ─── Apartments ───────────────────────────────────────────────────────────────

export interface ApartmentMonitor {
  id: number;
  sip_account: string;
  label: string | null;
  mac_address: string | null;
  model: string | null;
  name: string | null;
  cloud_id: number | null;
}

export interface ApartmentMonitorIn {
  sip_account: string;
  label?: string | null;
  mac_address?: string | null;
  model?: string | null;
  name?: string | null;
}

export interface Entrance {
  id: number;
  cloud_id: number;
  number: string;
  building_id: number | null;
  building_address: string | null;
}

export interface ApartmentSourceDevice {
  id: number;
  name: string;
  device_type: DeviceType;
  sip_account: string | null;
  enabled: boolean;
}

export interface Apartment {
  id: number;
  number: string;
  call_code: string;
  notes: string | null;
  enabled: boolean;
  floor: number | null;
  entrance_id: number | null;
  cloud_id: number | null;
  cloud_synced: boolean;
  last_cloud_sync_error: string | null;
  cloud_relay_enabled: boolean;
  cloud_sip_account: string | null;
  monitors: ApartmentMonitor[];
  source_devices: ApartmentSourceDevice[];
  created_at: string;
  updated_at: string;
}

export interface ApartmentCreate {
  number: string;
  call_code: string;
  notes?: string | null;
  enabled: boolean;
  floor?: number | null;
  // Required by backend — pick from GET /api/entrances.
  entrance_id: number;
  cloud_relay_enabled: boolean;
  cloud_sip_account?: string | null;
  monitors: ApartmentMonitorIn[];
}

export type ApartmentUpdate = Partial<ApartmentCreate>;

export interface ApartmentListOut {
  items: Apartment[];
  total: number;
}
