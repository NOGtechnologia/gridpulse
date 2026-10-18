import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { KioskView } from "@/components/views/KioskView";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "nav" });
  return { title: t("kiosk") };
}

export default function KioskPage() {
  return <KioskView />;
}
