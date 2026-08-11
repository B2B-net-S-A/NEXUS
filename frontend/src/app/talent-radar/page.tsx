"use client";

import { QueryStateNotice } from "@/components/ds";
import { RequireRole } from "@/components/RequireRole";
import { TalentRadarWorkspace } from "@/components/talent-radar/TalentRadarWorkspace";

/**
 * Role lustrzane wobec backendowego `require_candidate_write`
 * (`CANDIDATE_WRITE_ROLES` w `backend/app/api/candidate_access.py`) — świadomie
 * BEZ `head_of_recruitment`. Backend zostaje ostatecznym arbitrem; ta bramka
 * istnieje po to, żeby ktoś bez uprawnień zobaczył zdanie wyjaśniające zamiast
 * pustej listy po 403, bo pustka czyta się jak „nikogo nie ma w bazie".
 */
export default function TalentRadarPage() {
  return (
    <RequireRole
      roles={["admin", "delivery_lead", "tac", "recruiter", "sourcer"]}
      fallback={
        // `RequireRole` domyślnie renderuje `null`, czyli DOSŁOWNIE pusty DOM —
        // a docstring wyżej obiecuje zdanie wyjaśniające. Pusta strona czyta się
        // jak awaria albo jak „nic tu nie ma", nie jak „nie masz uprawnień",
        // i to ta sama pomyłka co renderowanie awarii jako pustego stanu.
        <QueryStateNotice
          state="forbidden"
          description="Talent Radar przeszukuje całą bazę kandydatów, więc wymaga uprawnień do pracy na kandydatach. Poproś administratora o dostęp."
        />
      }
    >
      <TalentRadarWorkspace />
    </RequireRole>
  );
}
