"use client";

import { ClipboardCheck } from "lucide-react";

import { PrepReviewSettings } from "@/components/settings/PrepReviewSettings";
import { hasSectionAccess } from "@/lib/section-access";
import { hasRole, useAuthStore } from "@/store/auth";

// Ustawienia → Rekrutacja → Ocena prepów (0505). Bramka jest lustrem
// backendu: odczyt rekruter, DL, HoR i admin w sekcji Pipeline; publikację
// (HoR, admin) rozstrzyga serwer polem `can_edit`.
export default function PrepReviewSettingsPage() {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }
  const allowed =
    hasRole(user, "admin", "head_of_recruitment", "delivery_lead", "recruiter") &&
    hasSectionAccess(user, "pipeline", "read");
  if (!allowed) {
    return (
      <div className="p-6 text-muted-foreground">
        Ustawienia oceny prepów widzą rekruter, Delivery Lead, Head of Recruitment i admin.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
          <ClipboardCheck className="h-5 w-5 text-primary" aria-hidden />
          Ocena prepów
        </h1>
        <p className="text-sm text-muted-foreground">
          Jak oceniamy Prep 1 i Prep 2 (follow-up) z nagrania w Teams: kryteria i wagi,
          tematy prowadzącego, skala odpowiedzi kandydata i co trafia do notatki na Prep 2.
        </p>
      </div>
      <PrepReviewSettings />
    </div>
  );
}
