import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { HistoryView } from "@/components/views/HistoryView";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "nav" });
  return { title: t("history") };
}

export default function Page() {
  return <HistoryView />;
}
