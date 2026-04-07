import { apiClient } from "./client";
import type {
  ActionResult,
  DashboardSummary,
  Device,
  DeviceCreate,
  DeviceListOut,
  DeviceUpdate,
  HealthOut,
  LoginRequest,
  RoutingRule,
  RoutingRuleCreate,
  RoutingRuleListOut,
  RoutingRuleUpdate,
  SystemInfo,
  TokenResponse,
  User,
} from "@/types";

// ─── Auth ─────────────────────────────────────────────────────────────────────

export const authApi = {
  login: (data: LoginRequest) =>
    apiClient.post<TokenResponse>("/auth/login", data).then((r) => r.data),
  me: () => apiClient.get<User>("/auth/me").then((r) => r.data),
};

// ─── Devices ──────────────────────────────────────────────────────────────────

export const devicesApi = {
  list: (params?: {
    skip?: number;
    limit?: number;
    device_type?: string;
    enabled?: boolean;
  }) =>
    apiClient.get<DeviceListOut>("/devices", { params }).then((r) => r.data),

  get: (id: number) =>
    apiClient.get<Device>(`/devices/${id}`).then((r) => r.data),

  create: (data: DeviceCreate) =>
    apiClient.post<Device>("/devices", data).then((r) => r.data),

  update: (id: number, data: DeviceUpdate) =>
    apiClient.put<Device>(`/devices/${id}`, data).then((r) => r.data),

  delete: (id: number) => apiClient.delete(`/devices/${id}`),

  testConnection: (id: number) =>
    apiClient
      .post<ActionResult>(`/devices/${id}/test-connection`)
      .then((r) => r.data),

  testUnlock: (id: number) =>
    apiClient
      .post<ActionResult>(`/devices/${id}/test-unlock`)
      .then((r) => r.data),
};

// ─── Routing Rules ────────────────────────────────────────────────────────────

export const routingApi = {
  list: () =>
    apiClient.get<RoutingRuleListOut>("/routing-rules").then((r) => r.data),

  get: (id: number) =>
    apiClient.get<RoutingRule>(`/routing-rules/${id}`).then((r) => r.data),

  create: (data: RoutingRuleCreate) =>
    apiClient.post<RoutingRule>("/routing-rules", data).then((r) => r.data),

  update: (id: number, data: RoutingRuleUpdate) =>
    apiClient
      .put<RoutingRule>(`/routing-rules/${id}`, data)
      .then((r) => r.data),

  delete: (id: number) => apiClient.delete(`/routing-rules/${id}`),
};

// ─── Dashboard / System ───────────────────────────────────────────────────────

export const dashboardApi = {
  summary: () =>
    apiClient.get<DashboardSummary>("/dashboard/summary").then((r) => r.data),
};

export const systemApi = {
  health: () => apiClient.get<HealthOut>("/health").then((r) => r.data),
  info: () => apiClient.get<SystemInfo>("/system/info").then((r) => r.data),
};
