import { type ClassValue, clsx } from "clsx";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function formatDate(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function formatLatency(ms: number | null | undefined) {
  if (ms == null) return "—";
  return `${ms.toFixed(0)} ms`;
}

export const DEVICE_TYPE_LABELS: Record<string, string> = {
  door_station: "Door Station",
  home_station: "Home Station",
  guard_station: "Guard Station",
  sip_client: "SIP Client",
  camera: "Camera",
};

export const UNLOCK_METHOD_LABELS: Record<string, string> = {
  http_get: "HTTP GET",
  http_post: "HTTP POST",
  sip_dtmf: "SIP DTMF",
  none: "None",
};

export const ACTIVITY_ACTION_LABELS: Record<string, string> = {
  device_created: "Device Created",
  device_updated: "Device Updated",
  device_deleted: "Device Deleted",
  unlock_test: "Unlock Test",
  connection_test: "Connection Test",
  login: "Login",
  rule_created: "Rule Created",
  rule_updated: "Rule Updated",
  rule_deleted: "Rule Deleted",
  door_call: "🔔 Door Call",
  door_call_end: "📵 Call Ended",
};
