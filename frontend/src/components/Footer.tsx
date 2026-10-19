import { useTranslations } from "next-intl";

export const DATA_SOURCES = [
  {
    name: "SMARD.de – Bundesnetzagentur",
    url: "https://www.smard.de",
    license: "CC BY 4.0",
  },
  {
    name: "Energy-Charts.info – Fraunhofer ISE",
    url: "https://www.energy-charts.info",
    license: "CC BY 4.0",
  },
  { name: "Open-Meteo.com", url: "https://open-meteo.com", license: "CC BY 4.0" },
  {
    name: "ENTSO-E Transparency Platform (optional)",
    url: "https://transparency.entsoe.eu",
    license: "ENTSO-E Terms and Conditions",
  },
] as const;

export function Footer() {
  const t = useTranslations("footer");
  return (
    <footer className="mt-8 border-t border-border bg-panel text-xs text-muted">
      <div className="mx-auto flex max-w-screen-2xl flex-col gap-2 px-4 py-4">
        <p role="note" className="font-medium text-fg">
          {t("disclaimer")}
        </p>
        <p>
          {t("sources")}:{" "}
          {DATA_SOURCES.map((s, i) => (
            <span key={s.url}>
              {i > 0 ? " · " : ""}
              <a className="underline hover:text-fg" href={s.url} rel="noreferrer">
                {s.name}
              </a>{" "}
              ({s.license})
            </span>
          ))}
        </p>
        <p>
          <a
            className="underline hover:text-fg"
            href="https://github.com/NOGtechnologia/gridpulse"
            rel="noreferrer"
          >
            {t("code")}
          </a>
        </p>
      </div>
    </footer>
  );
}
