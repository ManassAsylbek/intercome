import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { platesApi } from "@/api";
import type { PlateCreate, PlateUpdate } from "@/types";

export const PLATES_KEY = ["plates"] as const;
export const PLATE_LOG_KEY = ["plate-log"] as const;

export function usePlates() {
  return useQuery({
    queryKey: PLATES_KEY,
    queryFn: () => platesApi.list(),
  });
}

export function usePlateLog() {
  return useQuery({
    queryKey: PLATE_LOG_KEY,
    queryFn: () => platesApi.log(),
  });
}

export function usePlate(id: number) {
  return useQuery({
    queryKey: [...PLATES_KEY, id],
    queryFn: () => platesApi.get(id),
    enabled: !!id,
  });
}

export function useCreatePlate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: PlateCreate) => platesApi.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: PLATES_KEY }),
  });
}

export function useUpdatePlate(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: PlateUpdate) => platesApi.update(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: PLATES_KEY }),
  });
}

export function useDeletePlate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => platesApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: PLATES_KEY }),
  });
}
