import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { EventsView } from "@/components/views/EventsView";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "nav" });
  return { title: t("events") };
}

export default function Page() {
  return <EventsView />;
}
