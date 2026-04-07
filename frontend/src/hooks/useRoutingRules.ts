import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { routingApi } from "@/api";
import type { RoutingRuleCreate, RoutingRuleUpdate } from "@/types";

export const RULES_KEY = ["routing-rules"] as const;

export function useRoutingRules() {
  return useQuery({
    queryKey: RULES_KEY,
    queryFn: () => routingApi.list(),
  });
}

export function useRoutingRule(id: number) {
  return useQuery({
    queryKey: [...RULES_KEY, id],
    queryFn: () => routingApi.get(id),
    enabled: !!id,
  });
}

export function useCreateRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: RoutingRuleCreate) => routingApi.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: RULES_KEY }),
  });
}

export function useUpdateRule(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: RoutingRuleUpdate) => routingApi.update(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: RULES_KEY }),
  });
}

export function useDeleteRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => routingApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: RULES_KEY }),
  });
}
