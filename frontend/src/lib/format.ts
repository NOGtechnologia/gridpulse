/** Locale-aware formatting. All instants are displayed in Europe/Berlin (spec 5.4, 8). */

export const TIME_ZONE = "Europe/Berlin";

const DIGITS: Record<string, number> = {
  MW: 0,
  "EUR/MWh": 2,
  Hz: 3,
  "%": 1,
  "gCO2/kWh": 0,
  degC: 1,
  "km/h": 1,
  "W/m2": 0,
  h: 1,
};

const UNIT_LABEL: Record<string, string> = {
  degC: "°C",
  "gCO2/kWh": "g CO₂/kWh",
  "EUR/MWh": "€/MWh",
  "W/m2": "W/m²",
};

export function unitLabel(unit: string): string {
  return UNIT_LABEL[unit] ?? unit;
}

export function formatNumber(value: number, locale: string, digits = 0): string {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** e.g. formatValue(1234.5, "MW", "de", 1) -> "1.234,5 MW" */
export function formatValue(
  value: number | null | undefined,
  unit: string,
  locale: string,
  digits?: number,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const d = digits ?? DIGITS[unit] ?? 1;
  return `${formatNumber(value, locale, d)} ${unitLabel(unit)}`;
}

export function formatDateTime(iso: string | Date, locale: string, withSeconds = false): string {
  const date = typeof iso === "string" ? new Date(iso) : iso;
  return new Intl.DateTimeFormat(locale, {
    timeZone: TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
  }).format(date);
}

export function formatTime(iso: string | Date, locale: string): string {
  const date = typeof iso === "string" ? new Date(iso) : iso;
  return new Intl.DateTimeFormat(locale, {
    timeZone: TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/** "vor 5 Minuten" / "5 minutes ago" */
export function formatAge(seconds: number | null | undefined, locale: string): string {
  if (seconds === null || seconds === undefined) return "–";
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto", style: "short" });
  const abs = Math.abs(seconds);
  if (abs < 90) return rtf.format(-Math.round(seconds), "second");
  if (abs < 90 * 60) return rtf.format(-Math.round(seconds / 60), "minute");
  if (abs < 48 * 3600) return rtf.format(-Math.round(seconds / 3600), "hour");
  return rtf.format(-Math.round(seconds / 86400), "day");
}

/** Convert a Europe/Berlin wall-clock "YYYY-MM-DDTHH:mm" (datetime-local) to UTC ISO. */
export function berlinLocalToUtcIso(local: string): string {
  const [datePart = "", timePart = "00:00"] = local.split("T");
  const [y = 0, m = 1, d = 1] = datePart.split("-").map(Number);
  const [hh = 0, mm = 0] = timePart.split(":").map(Number);
  const guess = Date.UTC(y, m - 1, d, hh, mm);
  // Offset of Berlin at the guessed instant; iterate once to settle around DST changes.
  let ts = guess - berlinOffsetMs(guess);
  ts = guess - berlinOffsetMs(ts);
  return new Date(ts).toISOString().replace(".000Z", "Z");
}

export function berlinOffsetMs(utcMs: number): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: TIME_ZONE,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(new Date(utcMs));
  const get = (type: string): number => Number(parts.find((p) => p.type === type)?.value ?? 0);
  const asUtc = Date.UTC(
    get("year"),
    get("month") - 1,
    get("day"),
    get("hour"),
    get("minute"),
    get("second"),
  );
  return asUtc - Math.floor(utcMs / 1000) * 1000;
}

/** UTC ISO -> Europe/Berlin "YYYY-MM-DDTHH:mm" for <input type="datetime-local">. */
export function utcIsoToBerlinLocal(iso: string): string {
  const ms = new Date(iso).getTime();
  const local = new Date(ms + berlinOffsetMs(ms));
  return local.toISOString().slice(0, 16);
}
