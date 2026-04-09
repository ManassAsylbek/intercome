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
  door_station: "Панель домофона",
  home_station: "Домашний монитор",
  guard_station: "Пост охраны",
  sip_client: "SIP-клиент",
  camera: "Камера",
};

export const UNLOCK_METHOD_LABELS: Record<string, string> = {
  http_get: "HTTP GET",
  http_post: "HTTP POST",
  sip_dtmf: "SIP DTMF",
  none: "Нет",
};

export const ACTIVITY_ACTION_LABELS: Record<string, string> = {
  device_created: "Устройство добавлено",
  device_updated: "Устройство изменено",
  device_deleted: "Устройство удалено",
  unlock_test: "Тест открытия",
  connection_test: "Тест соединения",
  login: "Вход",
  rule_created: "Правило добавлено",
  rule_updated: "Правило изменено",
  rule_deleted: "Правило удалено",
  door_call: "🔔 Звонок с двери",
  door_call_end: "📵 Звонок завершён",
};
