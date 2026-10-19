import { cn } from "@/lib/cn";

export function Skeleton({
  className,
  label,
  height,
}: {
  className?: string;
  label: string;
  /** Final content height in px, so that loading does not shift the layout. */
  height?: number;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn("animate-pulse rounded bg-border/50", className)}
      style={height ? { height } : undefined}
    >
      <span className="sr-only">{label}</span>
    </div>
  );
}
