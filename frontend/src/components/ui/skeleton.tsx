import { cn } from "@/lib/cn";

export function Skeleton({ className, label }: { className?: string; label: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn("animate-pulse rounded bg-border/50", className)}
    >
      <span className="sr-only">{label}</span>
    </div>
  );
}
