import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearSubmission, savedReceipt, saveReceipt, submissionKey } from "./submissionStorage";
import { ApiError, parseRetryAfter } from "./api";

beforeEach(() => { sessionStorage.clear(); vi.restoreAllMocks(); });

describe("submission recovery", () => {
  it("keeps the same identity for a retry and changes it only for an explicit new report", () => {
    const key = submissionKey("konce");
    expect(key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(submissionKey("konce")).toBe(key);
    expect(submissionKey("radovis")).not.toBe(key);
    clearSubmission("konce");
    expect(submissionKey("konce")).not.toBe(key);
  });
  it("restores the receipt after a reload without storing citizen contact", () => {
    saveReceipt("konce", { id: 1, tracking_code: "TESTCODE", status: "pending_triage", status_label: "Примена", receipt_delivery: "queued" });
    expect(savedReceipt("konce")?.tracking_code).toBe("TESTCODE");
    expect(savedReceipt("radovis")).toBeNull();
    clearSubmission("konce");
    expect(savedReceipt("konce")).toBeNull();
  });
  it("still submits when browser storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(submissionKey("konce")).toMatch(/^[0-9a-f-]{36}$/);
    expect(savedReceipt("konce")).toBeNull();
  });
});

describe("server retry delays", () => {
  it("honors Nginx Retry-After even without API metadata", () => {
    expect(new ApiError("Limited", 429, {}, "60").retryAfterSeconds).toBe(60);
    expect(new ApiError("Limited", 429, { meta: { retry_after_seconds: 120 } }, "60").retryAfterSeconds).toBe(120);
  });
  it("supports dates and rejects malformed values", () => {
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-11-04T00:00:00Z"));
    expect(parseRetryAfter("Wed, 04 Nov 2026 00:01:00 GMT")).toBe(60);
    expect(parseRetryAfter("garbage")).toBe(0);
    expect(parseRetryAfter(null)).toBe(0);
  });
});
