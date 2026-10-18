import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type BadgeTone = "ok" | "warn" | "crit" | "neutral";

const TONES: Record<BadgeTone, string> = {
  ok: "border-ok text-ok",
  warn: "border-warn text-warn",
  crit: "border-crit text-crit",
  neutral: "border-border text-muted",
};

/** Status badge. Always carries text; colour is only an additional cue (spec 8). */
export function Badge({
  tone = "neutral",
  children,
  className,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
