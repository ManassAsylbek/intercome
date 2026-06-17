import { useQuery } from "@tanstack/react-query";
import { entrancesApi } from "@/api";

/** List of cloud-defined entrances cached locally on bridge. Read-only:
 * the list is pushed by cloud's bootstrap_snapshot — admin can only pick,
 * not create.
 *
 * staleTime is short (5s) so a freshly arrived entrance from cloud shows up
 * in the dropdown as soon as the next render happens. Forms that open via
 * portal (Modal) should additionally call ``refetch()`` on open, because
 * the form component stays mounted between opens and React Query has no
 * mount-cycle to hook into.
 */
export function useEntrances() {
  return useQuery({
    queryKey: ["entrances"],
    queryFn: entrancesApi.list,
    staleTime: 5_000,
    refetchOnWindowFocus: true,
  });
}
