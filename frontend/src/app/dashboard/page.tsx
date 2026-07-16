"use client";

/**
 * /dashboard — router widoków Analytics v1 (plan PR 5).
 *
 * Widoki ?view=operations|recruitment|delivery|executive działają WYŁĄCZNIE
 * gdy Analytics v1 jest w trybie live (fail-closed) — do tego czasu strona
 * odsyła na klasyczny dashboard (/), a legacy UI pozostaje nietknięte
 * (shadow nie zmienia odpowiedzi starego frontendu — plan §8).
 */

import { Suspense, useEffect } from "react";
import { useRouter } from "next/navigation";

import { AnalyticsDashboard } from "@/components/v2/pages/AnalyticsDashboard";
import { useAuthStore } from "@/store/auth";

function DashboardViewRouter() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);

  const live = (user?.analytics_v1_mode ?? "off") === "live";

  useEffect(() => {
    if (!hydrated) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (!live) {
      router.replace("/");
    }
  }, [hydrated, user, live, router]);

  if (!hydrated || !user || !live) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }
  return <AnalyticsDashboard />;
}

export default function DashboardPage() {
  return (
    <Suspense
      fallback={<div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>}
    >
      <DashboardViewRouter />
    </Suspense>
  );
}
