import { AlertTriangle, CheckCircle2 } from "lucide-react";

export type ActionFeedback = {
  tone: "success" | "error";
  message: string;
};

export function ActionNotice({ feedback }: { feedback: ActionFeedback | null }) {
  if (!feedback) return null;

  const isSuccess = feedback.tone === "success";
  const Icon = isSuccess ? CheckCircle2 : AlertTriangle;

  return (
    <div
      className={`flex items-center gap-2 rounded-md border p-3 text-sm font-semibold ${
        isSuccess
          ? "border-green-200 bg-green-50 text-green-800"
          : "border-red-200 bg-red-50 text-red-800"
      }`}
      role={isSuccess ? "status" : "alert"}
      aria-live="polite"
    >
      <Icon className="h-5 w-5 shrink-0" />
      {feedback.message}
    </div>
  );
}
