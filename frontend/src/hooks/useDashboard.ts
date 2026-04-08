import { useQuery } from "@tanstack/react-query";
import { dashboardApi, systemApi } from "@/api";

export function useDashboard() {
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: () => dashboardApi.summary(),
    refetchInterval: 30_000,
  });
}

export function useSystemInfo() {
  return useQuery({
    queryKey: ["system-info"],
    queryFn: () => systemApi.info(),
  });
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => systemApi.health(),
    refetchInterval: 60_000,
  });
}

export function useAsteriskHealth() {
  return useQuery({
    queryKey: ["asterisk-health"],
    queryFn: () => systemApi.asteriskHealth(),
    refetchInterval: 30_000,
    retry: 1,
  });
}
