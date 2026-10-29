"use client";

import { ArrowLeftRight } from "lucide-react";

import { TwinRulesSettings } from "@/components/settings/TwinRulesSettings";
import { hasSectionAccess } from "@/lib/section-access";
import { hasRole, useAuthStore } from "@/store/auth";

// Ustawienia → Rekrutacja → Zasady bliźniaków (29.10.2026). Odczyt: admin,
// Head of Recruitment i Delivery Lead w sekcji Pipeline; zapis (HoR, admin)
// rozstrzyga serwer polem `can_edit`.
export default function TwinRulesSettingsPage() {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }
  const allowed =
    hasRole(user, "admin", "head_of_recruitment", "delivery_lead") && hasSectionAccess(user, "pipeline", "read");
  if (!allowed) {
    return (
      <div className="p-6 text-muted-foreground">
        Zasady bliźniaków widzą Delivery Lead, Head of Recruitment i admin.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
          <ArrowLeftRight className="h-5 w-5 text-primary" aria-hidden />
          Zasady bliźniaków
        </h1>
        <p className="text-sm text-muted-foreground">
          Kiedy dwie otwarte rekrutacje są bliźniakami. Zasady działają od razu u wszystkich: na liście „Możliwe
          bliźniaki”, w kaflu „Otwarte podobne” i w oknie łączenia. „Wymagane” zdejmuje parę z listy propozycji —
          połączyć ją ręcznie dalej można, okno pokaże ostrzeżenie.
        </p>
      </div>
      <TwinRulesSettings />
    </div>
  );
}
