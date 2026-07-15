import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(value?: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("mk-MK", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

export function statusTone(status?: string) {
  if (status === "resolved" || status === "closed") return "success";
  if (status === "pending_triage") return "warning";
  if (status === "rejected_spam") return "destructive";
  if (status === "duplicate" || status === "not_jurisdiction") return "secondary";
  return "default";
}

export function priorityTone(priority?: string) {
  if (priority === "urgent") return "destructive";
  if (priority === "high") return "warning";
  if (priority === "low") return "secondary";
  return "outline";
}
