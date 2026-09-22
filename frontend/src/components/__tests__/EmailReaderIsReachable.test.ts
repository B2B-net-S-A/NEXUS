/**
 * Czytnik wątków M365 musi mieć wejście z profilu kandydata.
 *
 * Ten komponent już raz osierociał po cichu. Commit 4925ac53 (PR #539,
 * 2026-06-18) usunął zakładkę „Maile" z uzasadnieniem, że „Email jest już
 * dostępny w menu Więcej (przeniesiony w #538)" — ale tym, co wylądowało
 * w tamtym menu, jest KOMPOZYTOR `mailto:`, a nie czytnik wątków. Parytet,
 * który tamten commit deklarował, nigdy nie był prawdą.
 *
 * Skutek trwał dwa miesiące: 1473 linie komponentów i 7 żywych endpointów
 * bez jednego importu, podczas gdy synchronizacja M365 dalej zapisywała na
 * produkcji treści maili kandydatów i załączniki — dane, których produkt
 * nie umiał pokazać. To jest gorszy stan niż jedno albo drugie: przechowujemy
 * korespondencję pod RODO i nie dajemy do niej dostępu.
 *
 * Test patrzy w ŹRÓDŁO, a nie renderuje profilu: profil ciągnie kilkanaście
 * zapytań i sesję, więc test renderujący padałby z powodów niezwiązanych
 * z tym, czego pilnuje.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { parseCandidateProfileView } from "@/components/v2/pages/candidate-profile-navigation";

const ROOT = join(__dirname, "..", "..", "..");
// Od 09.2026 czytnik żyje w zakładce „Historia” jako filtr „Maile”
// (dawna osobna zakładka „Maile”; `?tab=emails` jest aliasem).
const HISTORY = join(ROOT, "src/components/v2/candidate-profile/HistoryTab.tsx");
const DETAIL = join(ROOT, "src/components/v2/pages/CandidateDetailV2.tsx");
const READER = "src/components/emails/EmailThreadList.tsx";

describe("czytnik maili — wejście z profilu kandydata", () => {
  const src = readFileSync(HISTORY, "utf8");

  it("zakładka Historia importuje czytnik wątków", () => {
    expect(src).toContain("components/emails/EmailThreadList");
  });

  it("filtr „Maile” jest w filtrach historii", () => {
    expect(src).toMatch(/emails:\s*"Maile"/);
  });

  it("filtr ma swój panel — sama pozycja w liście niczego nie renderuje", () => {
    expect(src).toMatch(/activityView === "emails" \?/);
    expect(src).toContain("<EmailThreadList");
  });

  it("profil montuje zakładkę Historia", () => {
    expect(readFileSync(DETAIL, "utf8")).toContain("<HistoryTab");
  });

  it("stary link `?tab=emails` otwiera filtr „Maile”", () => {
    expect(parseCandidateProfileView(new URLSearchParams("tab=emails"))).toMatchObject({
      section: "activity",
      activity: "emails",
    });
  });

  it("czytnik przestaje być wyspą bez importerów", () => {
    // Dokładnie ten warunek był fałszywy przez dwa miesiące: `grep -rn
    // "components/emails"` poza samym katalogiem nie zwracał NICZEGO.
    expect(src.includes(READER.replace("src/", "@/").replace(".tsx", ""))).toBe(
      true,
    );
  });
});
