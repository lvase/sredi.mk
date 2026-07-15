import type { QueryClient } from "@tanstack/react-query";

export function clearStaffCache(queryClient: QueryClient) {
  queryClient.removeQueries({
    predicate: (query) => String(query.queryKey[0] || "").startsWith("staff-")
  });
}
