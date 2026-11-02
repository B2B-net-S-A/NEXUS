"use client";

import { Mail } from "lucide-react";

import { CproSettings } from "@/components/settings/CproSettings";
import { hasSectionAccess } from "@/lib/section-access";
import { hasRole, useAuthStore } from "@/store/auth";

// Ustawienia → Rekrutacja → CPro (02.11.2026). Odczyt: admin, Head of Recruitment
// i Delivery Lead w sekcji Pipeline; wyłączniki (HoR, admin) rozstrzyga serwer.
export default function CproSettingsPage() {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }
  const allowed =
    hasRole(user, "admin", "head_of_recruitment", "delivery_lead") && hasSectionAccess(user, "pipeline", "read");
  if (!allowed) {
    return <div className="p-6 text-muted-foreground">Dziennik CPro widzą Delivery Lead, Head of Recruitment i admin.</div>;
  }

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
          <Mail className="h-5 w-5 text-primary" aria-hidden />
          CPro (Nordea)
        </h1>
        <p className="text-sm text-muted-foreground">
          Zmiany z maili CPro w skrzynkach Delivery Leadów. NEXUS czyta tylko maile od noreply@onevms.se z potwierdzonym
          nadawcą i linkiem do nordea.onevms.se.
        </p>
      </div>
      <CproSettings />
    </div>
  );
}
