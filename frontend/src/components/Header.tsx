"use client";

import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Link, usePathname } from "@/i18n/navigation";
import { locales } from "@/i18n/routing";
import { applyTheme, currentTheme, type Theme } from "@/lib/theme";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/", key: "situation" },
  { href: "/outlook", key: "outlook" },
  { href: "/events", key: "events" },
  { href: "/history", key: "history" },
  { href: "/status", key: "status" },
  { href: "/kiosk", key: "kiosk" },
] as const;

export function ThemeToggle() {
  const t = useTranslations("common");
  const [theme, setTheme] = useState<Theme>("dark");
  useEffect(() => {
    setTheme(currentTheme());
  }, []);
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="rounded border border-border px-2 py-1 text-sm hover:border-accent"
      aria-label={`${t("theme")}: ${theme === "dark" ? t("themeDark") : t("themeLight")}`}
      onClick={() => {
        applyTheme(next);
        setTheme(next);
      }}
    >
      {theme === "dark" ? "☾" : "☀"} {theme === "dark" ? t("themeDark") : t("themeLight")}
    </button>
  );
}

export function LocaleSwitch() {
  const t = useTranslations("common");
  const locale = useLocale();
  const pathname = usePathname();
  return (
    <nav aria-label={t("language")} className="flex gap-1 text-sm">
      {locales.map((l) => (
        <Link
          key={l}
          href={pathname}
          locale={l}
          aria-current={l === locale ? "true" : undefined}
          className={cn(
            "rounded px-2 py-1 uppercase",
            l === locale ? "bg-border font-semibold" : "text-muted hover:text-fg",
          )}
          lang={l}
        >
          {l}
        </Link>
      ))}
    </nav>
  );
}

export function Header() {
  const t = useTranslations();
  const pathname = usePathname();
  return (
    <header className="border-b border-border bg-panel">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-panel focus:p-2"
      >
        {t("app.skip")}
      </a>
      <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center gap-4 px-4 py-2">
        <Link href="/" className="flex items-baseline gap-2">
          <span className="text-lg font-bold text-fg">{t("app.name")}</span>
          <span className="hidden text-xs text-muted md:inline">{t("app.tagline")}</span>
        </Link>
        <nav aria-label={t("nav.main")} className="flex flex-1 flex-wrap gap-1">
          {NAV.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded px-3 py-1.5 text-sm",
                  active ? "bg-border font-semibold text-fg" : "text-muted hover:text-fg",
                )}
              >
                {t(`nav.${item.key}`)}
              </Link>
            );
          })}
        </nav>
        <ThemeToggle />
        <LocaleSwitch />
      </div>
    </header>
  );
}
