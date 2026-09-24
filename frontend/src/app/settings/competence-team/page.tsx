"use client"

import { CompetenceTeamPanel } from "@/components/v2/competence-team/CompetenceTeamPanel"
import { hasRole, useAuthStore } from "@/store/auth"

/** Ustawienia → Zespół i dostęp → „Kategorie kompetencji” (0371, 24.09.2026). */
export default function CompetenceTeamPage() {
  const user = useAuthStore((state) => state.user)
  const hydrated = useAuthStore((state) => state.hydrated)

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>
  }
  if (!hasRole(user, "admin", "head_of_recruitment")) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Brak dostępu — panel dla administratora i Head of Recruitment.
      </div>
    )
  }
  return (
    <div className="mx-auto max-w-[1400px] space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-[-0.02em] text-foreground">
          Kategorie kompetencji zespołu
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Automat przydziela requesty najpierw osobom z 1. priorytetem kategorii, potem z
          2. Kliknij „+ Dodaj”, żeby przypisać osobę.
        </p>
      </div>
      <CompetenceTeamPanel />
    </div>
  )
}
