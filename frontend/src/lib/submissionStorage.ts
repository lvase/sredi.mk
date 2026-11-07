export type CreatedIssue = { id: number; tracking_code: string; status: string; status_label: string; receipt_delivery: "queued" | "sent" | "failed" | "not_requested" };

function read(key: string): string | null {
  try { return sessionStorage.getItem(key); } catch { return null; }
}

function write(key: string, value: string) {
  try { sessionStorage.setItem(key, value); } catch { /* Submission still works if storage is disabled. */ }
}

function randomKey() {
  // getRandomValues also supports the HTTP development server and older browsers.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function submissionKey(slug: string) {
  const key = `sredi:submission:${slug}`;
  const value = read(key) || randomKey();
  write(key, value);
  return value;
}

export function savedReceipt(slug: string): CreatedIssue | null {
  try {
    const receipt = JSON.parse(read(`sredi:receipt:${slug}`) || "null");
    return receipt && typeof receipt.tracking_code === "string" && typeof receipt.id === "number" ? receipt : null;
  } catch { return null; }
}

export function saveReceipt(slug: string, receipt: CreatedIssue) {
  write(`sredi:receipt:${slug}`, JSON.stringify(receipt));
}

export function clearSubmission(slug: string) {
  for (const key of [`sredi:submission:${slug}`, `sredi:receipt:${slug}`]) {
    try { sessionStorage.removeItem(key); } catch { /* Storage may be disabled. */ }
  }
}
