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
  sip_enabled: boolean;
  sip_account: string | null;
  sip_password: string | null;
  sip_server: string | null;
  sip_port: number | null;
  sip_proxy: string | null;
  rtsp_enabled: boolean;
  rtsp_url: string | null;
  unlock_enabled: boolean;
  unlock_method: UnlockMethod;
  unlock_url: string | null;
  unlock_username: string | null;
  unlock_password: string | null;
  is_online: boolean | null;
  last_seen: string | null;
  created_at: string;
  updated_at: string;
}

export type DeviceCreate = Omit<
  Device,
  "id" | "is_online" | "last_seen" | "created_at" | "updated_at"
>;
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
