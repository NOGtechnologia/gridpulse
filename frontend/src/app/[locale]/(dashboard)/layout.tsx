import type { ReactNode } from "react";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <Header />
      <main id="main" className="mx-auto max-w-screen-2xl px-4 py-4">
        {children}
      </main>
      <Footer />
    </>
  );
}
