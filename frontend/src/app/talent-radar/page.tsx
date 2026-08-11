"use client";

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
    >
      <TalentRadarWorkspace />
    </RequireRole>
  );
}
