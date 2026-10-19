"use client";

import { useLocale, useTranslations } from "next-intl";
import { useId, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatAge, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/cn";

export interface Provenance {
  source?: string | null;
  license?: string | null;
  ts?: string | null;
  ageSeconds?: number | null;
  stale?: boolean;
}

/** Footer with source, licence and data timestamp - required for every number (spec 8). */
export function SourceFooter({ source, license, ts, ageSeconds, stale }: Provenance) {
  const t = useTranslations("common");
  const locale = useLocale();
  return (
    <CardFooter>
      <span>
        {t("source")}: {source ?? t("unknown")}
      </span>
      {license ? (
        <span>
          {" "}
          · {t("license")}: {license}
        </span>
      ) : null}
      {ts ? (
        <span>
          {" "}
          ·{" "}
          <time dateTime={ts} title={formatDateTime(ts, locale, true)}>
            {t("dataAge", { age: formatAge(ageSeconds ?? null, locale) })}
          </time>
        </span>
      ) : null}
      {stale ? (
        <Badge tone="warn" className="ml-2">
          ⚠ {t("stale")}
        </Badge>
      ) : null}
    </CardFooter>
  );
}

export function Tile({
  title,
  loading,
  error,
  empty,
  onRetry,
  provenance,
  children,
  className,
  actions,
  skeletonHeight = 64,
}: {
  title: string;
  loading?: boolean;
  error?: Error | undefined;
  empty?: boolean;
  onRetry?: () => void;
  provenance?: Provenance;
  children?: ReactNode;
  className?: string;
  actions?: ReactNode;
  /** Height of the loaded content in px; reserved while loading (no layout shift). */
  skeletonHeight?: number;
}) {
  const t = useTranslations("common");
  const headingId = useId();
  const showSkeleton = Boolean(loading && !children);
  let body: ReactNode = children;
  if (showSkeleton) {
    body = <Skeleton className="w-full" height={skeletonHeight} label={t("loading")} />;
  } else if (error && !children) {
    body = (
      <div role="alert" className="flex flex-col items-start gap-2 text-sm text-crit">
        <span>{t("error")}</span>
        {onRetry ? <Button onClick={onRetry}>{t("retry")}</Button> : null}
      </div>
    );
  } else if (empty) {
    body = <p className="text-sm text-muted">{t("empty")}</p>;
  }
  return (
    <Card
      aria-labelledby={headingId}
      className={cn(provenance?.stale ? "opacity-80 grayscale" : undefined, className)}
    >
      <CardHeader>
        <CardTitle id={headingId}>{title}</CardTitle>
        {actions}
      </CardHeader>
      <CardContent>{body}</CardContent>
      {provenance?.stale ? <p className="sr-only">{t("staleHint")}</p> : null}
      {provenance ? <SourceFooter {...provenance} /> : null}
      {!provenance && showSkeleton ? (
        // Keeps the footer's height until source and data age are known.
        <CardFooter aria-hidden="true">&nbsp;</CardFooter>
      ) : null}
    </Card>
  );
}
