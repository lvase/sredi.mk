import { AlertTriangle } from "lucide-react";

export function ErrorState({ message = "Настана грешка." }: { message?: string }) {
  return (
    <div className="surface flex items-start gap-3 border-destructive/30 p-5 text-sm">
      <AlertTriangle className="mt-0.5 h-5 w-5 text-destructive" />
      <p>{message}</p>
    </div>
  );
}
