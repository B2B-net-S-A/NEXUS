"use client";

import { RankingPanel } from "@/components/settings/ranking/RankingPanel";
import { hasSectionAccess } from "@/lib/section-access";
import { hasRole, useAuthStore } from "@/store/auth";

/**
 * Ustawienia → Rekrutacja → Ranking kandydatów (21.10.2026, makiety
 * LttSvWiuw2CLPPHU1jL7kN). Odczyt: admin, Delivery Lead, Head of Recruitment
 * z odczytem Insights; szkic i publikacja wag: admin albo HoR z zapisem
 * Insights (decyzja D1; lustro `WeightsReader` / `HeadOfRecruitmentPlus`).
 */
export default function ScoringWeightsPage() {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);
  const isAllowed =
    hasRole(user, "admin", "delivery_lead", "head_of_recruitment") &&
    hasSectionAccess(user, "insights", "read");

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }
  if (!isAllowed) {
    return <div className="p-6 text-muted-foreground">Brak dostępu do wag rankingu.</div>;
  }
  return (
    <div className="mx-auto max-w-7xl space-y-5">
      <div className="space-y-1.5">
        <h1 className="text-2xl font-bold text-foreground">Ranking kandydatów</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Co liczy się najbardziej przy dopasowaniu kandydata. Te same zasady działają w „Szukaj
          w bazie”, „Przeszukaj całą bazę (AI)”, Talent Radarze i nocnych propozycjach.
        </p>
      </div>
      <RankingPanel
        insightsWrite={hasSectionAccess(user, "insights", "write")}
        isAdmin={hasRole(user, "admin")}
      />
    </div>
  );
}
