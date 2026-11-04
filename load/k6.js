import http from "k6/http";
import { check } from "k6";
import { Counter } from "k6/metrics";

const baseUrl = __ENV.BASE_URL || "https://localhost";
const municipality = __ENV.MUNICIPALITY_SLUG;
const staffSession = __ENV.STAFF_SESSION_COOKIE || "";
const submissions = Number(__ENV.SUBMISSION_COUNT || 0);
const failures = new Counter("unexpected_responses");
if (!municipality) throw new Error("MUNICIPALITY_SLUG is required");
if (!Number.isInteger(submissions) || submissions < 0 || submissions > 100) throw new Error("SUBMISSION_COUNT must be 0–100");
if ((submissions || __ENV.CHECK_THROTTLING === "1") && (!__ENV.SETTLEMENT_ID || !__ENV.CATEGORY_ID)) throw new Error("Submission tests need SETTLEMENT_ID and CATEGORY_ID on a disposable municipality");

const scenarios = {
  burst: { executor: "per-vu-iterations", vus: 100, iterations: 1, maxDuration: "30s", exec: "read" },
  paced_reads: { executor: "constant-arrival-rate", rate: Number(__ENV.READ_RPS || 3), timeUnit: "1s", duration: __ENV.DURATION || "5m", startTime: "15s", preAllocatedVUs: 10, maxVUs: 100, exec: "read" }
};
if (submissions) scenarios.submissions = { executor: "per-vu-iterations", vus: submissions, iterations: 1, startTime: "30s", maxDuration: "2m", exec: "submitReport" };
if (__ENV.CHECK_THROTTLING === "1") scenarios.throttling = { executor: "per-vu-iterations", vus: 1, iterations: 1, startTime: "45s", maxDuration: "1m", exec: "checkThrottle" };

export const options = {
  scenarios,
  thresholds: {
    "http_req_duration{scenario:burst}": ["p(95)<5000"],
    "http_req_duration{scenario:paced_reads}": ["p(95)<1000"],
    "http_req_duration{surface:submission}": ["p(95)<10000"],
    unexpected_responses: ["count==0"],
    checks: ["rate==1"],
    http_req_failed: ["rate<0.01"]
  }
};

function expect(response, status, name) {
  const passed = check(response, { [name]: (item) => item.status === status });
  failures.add(passed ? 0 : 1);
}

export function read() {
  const variant = __VU % 5;
  const staff = variant === 4 && staffSession;
  const path = staff ? "/api/staff/issues/?page_size=25" : variant === 3
    ? `/api/municipalities/${municipality}/statistics/?period=90`
    : `/api/municipalities/${municipality}/`;
  const response = http.get(baseUrl + path, { headers: staff ? { Cookie: `sessionid=${staffSession}` } : {}, tags: { surface: staff ? "staff" : "public" } });
  expect(response, 200, "read succeeds");
}

function key() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
    const value = Math.floor(Math.random() * 16);
    return (character === "x" ? value : (value & 3) | 8).toString(16);
  });
}

function postReport() {
  const payload = {
    settlement: __ENV.SETTLEMENT_ID, category: __ENV.CATEGORY_ID,
    title: `Load report ${__VU}-${Date.now()}`, description: "Controlled load test",
    location_text: "Load location", consent: "on", website: "", submission_key: key()
  };
  const url = `${baseUrl}/api/municipalities/${municipality}/issues/`;
  const parameters = { headers: { "Content-Type": "application/json" }, tags: { surface: "submission" },
    responseCallback: http.expectedStatuses(201, 429) };
  return { response: http.post(url, JSON.stringify(payload), parameters), payload, url, parameters };
}

export function submitReport() {
  expect(http.get(`${baseUrl}/api/auth/csrf/`), 200, "browser identity established");
  const { response, payload, url, parameters } = postReport();
  expect(response, 201, "submission accepted");
  const replay = http.post(url, JSON.stringify(payload), parameters);
  expect(replay, 201, "retry accepted");
  if (response.status === 201 && replay.status === 201) {
    check(replay, { "retry returns original report": (item) => item.json("data.tracking_code") === response.json("data.tracking_code") });
  }
}

export function checkThrottle() {
  expect(http.get(`${baseUrl}/api/auth/csrf/`), 200, "browser identity established");
  for (let attempt = 0; attempt < 4; attempt += 1) {
    expect(postReport().response, attempt < 3 ? 201 : 429, "browser submission quota enforced");
  }
}
