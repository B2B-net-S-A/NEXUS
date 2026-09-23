"use client";

import { Target } from "lucide-react";

import { KpiTargetsSettings } from "@/components/settings/KpiTargetsSettings";
import { hasSectionAccess } from "@/lib/section-access";
import { hasRole, useAuthStore } from "@/store/auth";

// Ustawienia → Rekrutacja → Cele KPI (plan PR3). Bramka jest lustrem
// backendu: `HeadOfRecruitmentPlus` + zapis sekcji Insights.
export default function KpiTargetsPage() {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }
  const allowed =
    hasRole(user, "admin", "head_of_recruitment") &&
    hasSectionAccess(user, "insights", "write");
  if (!allowed) {
    return (
      <div className="p-6 text-muted-foreground">
        Cele KPI zmienia administrator albo Head of Recruitment.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
          <Target className="h-5 w-5 text-primary" aria-hidden />
          Cele KPI
        </h1>
        <p className="text-sm text-muted-foreground">
          Cele rekruterów, sourcerów i TAC — dla ról i dla pojedynczych osób.
          Zmiana działa od razu w panelu „Moje KPI”, w widgecie i w wyścigach.
        </p>
      </div>
      <KpiTargetsSettings />
    </div>
  );
}
