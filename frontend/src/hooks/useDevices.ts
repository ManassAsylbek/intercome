import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { devicesApi } from "@/api";
import type { DeviceCreate, DeviceUpdate } from "@/types";

export const DEVICES_KEY = ["devices"] as const;

export function useDevices(params?: {
  device_type?: string;
  enabled?: boolean;
}) {
  return useQuery({
    queryKey: [...DEVICES_KEY, params],
    queryFn: () => devicesApi.list(params),
  });
}

export function useDevice(id: number) {
  return useQuery({
    queryKey: [...DEVICES_KEY, id],
    queryFn: () => devicesApi.get(id),
    enabled: !!id,
  });
}

export function useCreateDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: DeviceCreate) => devicesApi.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: DEVICES_KEY }),
  });
}

export function useUpdateDevice(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: DeviceUpdate) => devicesApi.update(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: DEVICES_KEY });
      qc.invalidateQueries({ queryKey: [...DEVICES_KEY, id] });
    },
  });
}

export function useDeleteDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => devicesApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: DEVICES_KEY }),
  });
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (id: number) => devicesApi.testConnection(id),
  });
}

export function useTestUnlock() {
  return useMutation({
    mutationFn: (id: number) => devicesApi.testUnlock(id),
  });
}
