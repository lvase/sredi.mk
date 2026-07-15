import { expect, test } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { clearStaffCache } from "./staffCache.ts";

test("staff cache is removed without clearing public or session data", () => {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["staff-issues", ""], { issues: ["konce"] });
  queryClient.setQueryData(["staff-issue", "42"], { municipality: "konce" });
  queryClient.setQueryData(["staff-choices"], { municipalities: ["konce"] });
  queryClient.setQueryData(["municipalities"], ["konce", "radovis"]);
  queryClient.setQueryData(["session"], { isAuthenticated: true });

  clearStaffCache(queryClient);

  expect(queryClient.getQueryData(["staff-issues", ""])).toBeUndefined();
  expect(queryClient.getQueryData(["staff-issue", "42"])).toBeUndefined();
  expect(queryClient.getQueryData(["staff-choices"])).toBeUndefined();
  expect(queryClient.getQueryData(["municipalities"])).toEqual(["konce", "radovis"]);
  expect(queryClient.getQueryData(["session"])).toEqual({ isAuthenticated: true });
});
