export function LoadingState({ label = "Се вчитува..." }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="surface flex min-h-40 items-center justify-center p-8 text-sm text-muted-foreground">
      {label}
    </div>
  );
}
