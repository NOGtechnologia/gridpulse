import { locale as rootLocale } from "next/root-params";
import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";
import { routing } from "./routing";

// Next.js ships `next/root-params` as an untyped placeholder module until it generates
// types during the build; the signature below matches the `[locale]` root segment.
const readRootLocale = rootLocale as () => Promise<string | undefined>;

export default getRequestConfig(async ({ locale: explicit }) => {
  // An explicit locale (e.g. getTranslations({ locale })) wins over the [locale] root param.
  const requested = explicit ?? (await readRootLocale());
  const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;
  const messages = (await import(`../../messages/${locale}.json`)) as {
    default: Record<string, unknown>;
  };
  return { locale, messages: messages.default, timeZone: "Europe/Berlin" };
});
