"use client";

import { useEffect, useState } from "react";
import { DEFAULT_THEME, type ChartTheme } from "@/components/charts/options";

export type Theme = "dark" | "light";
export const THEME_KEY = "gridpulse-theme";
export const THEME_EVENT = "gridpulse-theme-change";

/** Inline script (runs before paint) that applies the stored theme without flashing. */
export const THEME_INIT_SCRIPT = `try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"){document.documentElement.classList.remove("dark");document.documentElement.classList.add("light")}}catch(e){}`;

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.classList.toggle("light", theme === "light");
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    // Storage may be unavailable (private mode); the theme still applies for this page.
  }
  window.dispatchEvent(new Event(THEME_EVENT));
}

export function currentTheme(): Theme {
  return document.documentElement.classList.contains("light") ? "light" : "dark";
}

function rgbVar(style: CSSStyleDeclaration, name: string, fallback: string): string {
  const raw = style.getPropertyValue(name).trim();
  return raw ? `rgb(${raw.split(/\s+/).join(",")})` : fallback;
}

export function readChartTheme(): ChartTheme {
  const style = getComputedStyle(document.documentElement);
  return {
    fg: rgbVar(style, "--fg", DEFAULT_THEME.fg),
    muted: rgbVar(style, "--muted", DEFAULT_THEME.muted),
    border: rgbVar(style, "--border", DEFAULT_THEME.border),
  };
}

export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState<ChartTheme>(DEFAULT_THEME);
  useEffect(() => {
    const update = () => {
      setTheme(readChartTheme());
    };
    update();
    window.addEventListener(THEME_EVENT, update);
    return () => {
      window.removeEventListener(THEME_EVENT, update);
    };
  }, []);
  return theme;
}
