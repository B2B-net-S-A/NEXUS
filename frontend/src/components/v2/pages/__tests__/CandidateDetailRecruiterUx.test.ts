import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * `CandidateDetailV2` nie ma testu renderującego (ciężki komponent z kilkunastoma
 * zapytaniami), więc zmiany z przeglądu UX 17.09.2026 pilnujemy na źródle —
 * wzorzec `CandidateFormRemoteModeContract.test.tsx`.
 */
const SOURCE = readFileSync(
  join(__dirname, "..", "CandidateDetailV2.tsx"),
  "utf-8",
);

describe("profil kandydata — kontrakt zmian UX rekrutera", () => {
  it("ma „Dodaj notatkę” obok „Przypisz do rekrutacji” i fokusuje kompozytor", () => {
    const assign = SOURCE.indexOf("Przypisz do rekrutacji\n </Button>");
    const addNote = SOURCE.indexOf("Dodaj notatkę\n </Button>");
    expect(assign).toBeGreaterThan(-1);
    expect(addNote).toBeGreaterThan(assign);
    expect(SOURCE).toContain("onClick={openNoteComposer}");
    expect(SOURCE).toContain("textareaRef={composerTextareaRef}");
    expect(SOURCE).toContain('params.delete("compose")');
  });

  it("pokazuje CallButton tylko przy włączonym CloudTalku", () => {
    expect(SOURCE).toContain("canWriteSourcing && cloudTalkEnabled ? (\n <CallButton");
  });

  it("ma jedną kartę AI: podsumowanie z CV trafia do karty historii", () => {
    expect(SOURCE).toContain("cvSummary={aiSummary}");
    expect(SOURCE).not.toMatch(/<h3[^>]*>\s*Podsumowanie AI/);
  });

  it("nie dubluje rekrutacji widżetem pipeline'ów", () => {
    expect(SOURCE).not.toContain("<CandidatePipelinesWidget");
  });

  it("„Wróć do rekrutacji” otwiera dok tej osoby", () => {
    expect(SOURCE).toContain("href={`/jobs/${backJobId}?candidate=${id}`}");
  });

  it("oś czasu mówi o zdarzeniu, nie o rodzaju gramatycznym autora", () => {
    expect(SOURCE).not.toMatch(/zmienił etap|przypisał do etapu|dodał notatkę/);
    expect(SOURCE).toContain('"zmiana etapu" : "przypisanie do etapu"');
  });
});
