import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apartmentsApi } from "@/api";
import type { ApartmentCreate, ApartmentUpdate } from "@/types";

export const APARTMENTS_KEY = ["apartments"] as const;

export function useApartments() {
  return useQuery({
    queryKey: APARTMENTS_KEY,
    queryFn: () => apartmentsApi.list(),
  });
}

export function useCreateApartment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ApartmentCreate) => apartmentsApi.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: APARTMENTS_KEY }),
  });
}

export function useUpdateApartment(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ApartmentUpdate) => apartmentsApi.update(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: APARTMENTS_KEY }),
  });
}

export function useDeleteApartment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apartmentsApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: APARTMENTS_KEY }),
  });
}
