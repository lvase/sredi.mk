import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ensureCsrf, setCsrfToken } from "../lib/api";
import { clearStaffCache } from "../lib/staffCache";
import type { LoginResult, SessionPayload } from "../lib/types";

export function useSession() {
  return useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      const session = await api.get<SessionPayload>("/auth/session/");
      setCsrfToken(session.csrfToken);
      return session;
    }
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { username: string; password: string }) => {
      await ensureCsrf();
      return api.post<LoginResult>("/auth/login/", payload);
    },
    onSuccess: (data) => {
      setCsrfToken(data.csrfToken);
      if (data.authenticated) {
        clearStaffCache(queryClient);
        queryClient.invalidateQueries({ queryKey: ["session"] });
      }
    }
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await ensureCsrf();
      return api.post<{ loggedOut: boolean }>("/auth/logout/");
    },
    onSuccess: () => {
      setCsrfToken(null);
      clearStaffCache(queryClient);
      queryClient.invalidateQueries({ queryKey: ["session"] });
    }
  });
}
