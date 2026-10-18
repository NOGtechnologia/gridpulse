import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { StatusView } from "@/components/views/StatusView";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "nav" });
  return { title: t("status") };
}

export default function Page() {
  return <StatusView />;
}
