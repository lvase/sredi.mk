import http from "k6/http";
import { check } from "k6";
import encoding from "k6/encoding";

const baseUrl = __ENV.BASE_URL || "https://localhost";
const municipality = __ENV.MUNICIPALITY_SLUG;
const settlementId = __ENV.SETTLEMENT_ID;
const categoryId = __ENV.CATEGORY_ID;
const trackingCode = __ENV.TRACKING_CODE || "";
const staffSession = __ENV.STAFF_SESSION_COOKIE || "";
const onePixelPng = encoding.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "std");

if (!municipality) throw new Error("MUNICIPALITY_SLUG is required");

const scenarios = {
  public_visitors: { executor: "constant-vus", vus: 20, duration: __ENV.DURATION || "5m", exec: "publicReads" },
  upload_burst: { executor: "per-vu-iterations", vus: 5, iterations: 1, startTime: "10s", maxDuration: "2m", exec: "uploadReport" }
};
if (staffSession) scenarios.staff_inbox = { executor: "constant-vus", vus: 2, duration: __ENV.DURATION || "5m", exec: "staffInbox" };

export const options = {
  scenarios,
  thresholds: {
    "http_req_duration{surface:public}": ["p(95)<500"],
    "http_req_duration{surface:staff}": ["p(95)<750"],
    "http_req_duration{surface:upload}": ["p(95)<10000"],
    http_req_failed: ["rate<0.01"]
  }
};

export function publicReads() {
  const responses = http.batch([
    ["GET", `${baseUrl}/api/municipalities/${municipality}/`, null, { tags: { surface: "public" } }],
    ["GET", `${baseUrl}/api/municipalities/${municipality}/statistics/?period=90`, null, { tags: { surface: "public" } }],
    ...(trackingCode ? [["GET", `${baseUrl}/api/municipalities/${municipality}/track/?code=${trackingCode}`, null, { tags: { surface: "public" } }]] : [])
  ]);
  responses.forEach((response) => check(response, { "public response is successful": (item) => item.status === 200 }));
}

export function staffInbox() {
  const response = http.get(`${baseUrl}/api/staff/issues/?page=1&page_size=25`, {
    headers: { Cookie: `sessionid=${staffSession}` },
    tags: { surface: "staff" }
  });
  check(response, { "staff inbox is successful": (item) => item.status === 200 });
}

export function uploadReport() {
  if (!settlementId || !categoryId) throw new Error("SETTLEMENT_ID and CATEGORY_ID are required for uploads");
  const suffix = `${__VU}-${__ITER}-${Date.now()}`;
  const response = http.post(`${baseUrl}/api/municipalities/${municipality}/issues/`, {
    settlement: settlementId,
    category: categoryId,
    title: `Load upload ${suffix}`,
    description: "Synthetic upload used by the approved load profile.",
    location_text: `Load location ${suffix}`,
    consent: "on",
    website: "",
    photos: http.file(onePixelPng, `load-${suffix}.png`, "image/png")
  }, { tags: { surface: "upload" }, timeout: "120s" });
  check(response, { "upload is accepted": (item) => item.status === 201 });
}
