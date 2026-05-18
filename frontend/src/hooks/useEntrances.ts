import { useQuery } from "@tanstack/react-query";
import { entrancesApi } from "@/api";

/** List of cloud-defined entrances cached locally on bridge. Read-only:
 * the list is pushed by cloud's bootstrap_snapshot — admin can only pick,
 * not create. */
export function useEntrances() {
  return useQuery({
    queryKey: ["entrances"],
    queryFn: entrancesApi.list,
    staleTime: 60_000,
  });
}
