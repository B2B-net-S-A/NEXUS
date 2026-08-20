"use client";

import { QueryStateNotice } from "@/components/ds";
import { RequireRole } from "@/components/RequireRole";
import { TalentRadarWorkspace } from "@/components/talent-radar/TalentRadarWorkspace";
import { CAPABILITY_ROLES } from "@/lib/capabilities";

/**
 * Radar jest dla KAŻDEJ zalogowanej roli (decyzja produktowa 19.08 — poszła po
 * zrzucie 403 od Head of Recruitment). Backend trzyma oba endpointy na
 * `CurrentUser`, `middleware.ts` celowo NIE ma wpisu dla `/talent-radar`
 * (brak wpisu = brak zawężenia ról), a sidebar i paleta ⌘K czytają
 * `nav.talent_radar`. Ta strona była czwartą, rozjechaną kopią tej decyzji:
 * niosła listę lustrzaną wobec `require_candidate_write`, więc HoR widział
 * pozycję w menu, klikał i dostawał „Brak uprawnień".
 *
 * Lista jest WYLICZONA z rejestru, nie przepisana — inaczej rozjedzie się po
 * raz drugi. `RequireRole` zostaje (zamiast `useCapability`), bo jako jedyny
 * zna okno przed hydracją: przed `hydrate()` store ma `user === null`, więc
 * bramka liczona wprost twierdziłaby adminowi przez kilka sekund, że nie ma
 * uprawnień. Fallback zostaje jako fail-closed dla roli, której ktoś
 * w przyszłości nie dopisze do zbioru.
 */
export default function TalentRadarPage() {
  return (
    <RequireRole
      // `CAPABILITY_ROLES` jest `readonly`, prop `roles` mutowalny → kopia.
      roles={[...CAPABILITY_ROLES["nav.talent_radar"]]}
      fallback={
        // `RequireRole` domyślnie renderuje `null`, czyli DOSŁOWNIE pusty DOM —
        // a docstring wyżej obiecuje zdanie wyjaśniające. Pusta strona czyta się
        // jak awaria albo jak „nic tu nie ma", nie jak „nie masz uprawnień",
        // i to ta sama pomyłka co renderowanie awarii jako pustego stanu.
        <QueryStateNotice
          state="forbidden"
          description="Talent Radar wymaga zalogowania. Jeśli widzisz ten komunikat mimo aktywnej sesji — zgłoś to administratorowi."
        />
      }
    >
      <TalentRadarWorkspace />
    </RequireRole>
  );
}
