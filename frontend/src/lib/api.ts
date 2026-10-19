import type { ApiEnvelope, ApiErrorEnvelope } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

let csrfToken: string | null = null;
let csrfRequest: Promise<string> | null = null;

export class ApiError extends Error {
  errors: ApiErrorEnvelope;
  status: number;
  meta?: ApiErrorEnvelope["meta"];

  constructor(message: string, status: number, errors: ApiErrorEnvelope) {
    super(message);
    this.status = status;
    this.errors = errors;
    this.meta = errors.meta;
  }
}

export function apiErrorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

export function isNotFoundError(error: unknown) {
  return error instanceof ApiError && error.status === 404;
}

function errorMessage(payload: ApiErrorEnvelope) {
  const detail = payload.detail || ("errors" in payload && payload.errors && "detail" in payload.errors ? payload.errors.detail : null);
  if (typeof detail === "string") return detail;
  if (payload.errors && typeof payload.errors === "object") {
    for (const value of Object.values(payload.errors)) {
      if (typeof value === "string") return value;
      if (Array.isArray(value)) {
        const firstMessage = value.find((item) => typeof item === "string");
        if (typeof firstMessage === "string") return firstMessage;
      }
    }
  }
  return "Настана грешка. Провери ги податоците и обиди се повторно.";
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const isFormData = options.body instanceof FormData;
  if (!isFormData && options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (csrfToken && !["GET", "HEAD", "OPTIONS"].includes((options.method || "GET").toUpperCase())) {
    headers.set("X-CSRFToken", csrfToken);
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    ...options,
    headers
  });
  const payload = (await response.json().catch(() => ({}))) as ApiEnvelope<T> | ApiErrorEnvelope;
  if (!response.ok) {
    throw new ApiError(errorMessage(payload as ApiErrorEnvelope), response.status, payload as ApiErrorEnvelope);
  }
  return (payload as ApiEnvelope<T>).data;
}

async function upload<T>(path: string, body: FormData, onProgress?: (percent: number) => void) {
  if (!csrfToken) await ensureCsrf();
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}${path}`);
    xhr.withCredentials = true;
    xhr.timeout = 120_000;
    if (csrfToken) xhr.setRequestHeader("X-CSRFToken", csrfToken);
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100));
    });
    xhr.addEventListener("load", () => {
      const payload = (() => {
        try { return JSON.parse(xhr.responseText || "{}") as ApiEnvelope<T> | ApiErrorEnvelope; }
        catch { return {} as ApiErrorEnvelope; }
      })();
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new ApiError(errorMessage(payload as ApiErrorEnvelope), xhr.status, payload as ApiErrorEnvelope));
        return;
      }
      onProgress?.(100);
      resolve((payload as ApiEnvelope<T>).data);
    });
    xhr.addEventListener("error", () => reject(new ApiError("Мрежна грешка при испраќањето.", 0, {})));
    xhr.addEventListener("timeout", () => reject(new ApiError("Испраќањето траеше предолго. Обиди се повторно.", 0, {})));
    xhr.addEventListener("abort", () => reject(new ApiError("Испраќањето е прекинато.", 0, {})));
    xhr.send(body);
  });
}

export async function ensureCsrf() {
  if (csrfToken) return csrfToken;
  if (!csrfRequest) {
    csrfRequest = request<{ csrfToken: string }>("/auth/csrf/")
      .then((data) => {
        csrfToken = data.csrfToken;
        return csrfToken;
      })
      .finally(() => { csrfRequest = null; });
  }
  return csrfRequest;
}

export function setCsrfToken(token?: string | null) {
  csrfToken = token || null;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body instanceof FormData ? body : JSON.stringify(body || {})
    }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PATCH",
      body: JSON.stringify(body || {})
    }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload,
  url: (path: string) => `${API_BASE_URL}${path}`
};
