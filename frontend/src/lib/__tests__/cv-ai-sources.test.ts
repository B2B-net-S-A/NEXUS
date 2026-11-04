import { describe, expect, it } from "vitest";

import {
  CV_AI_SOURCE_DEFAULTS,
  aiSourceRows,
  initialAiSources,
  type CvAiSources,
} from "@/lib/cv-ai-sources";

const DATA: CvAiSources = {
  original_cv: { document_id: 31, filename: "Anna_Przykladowa_CV.pdf", uploaded_at: "2026-09-12T09:00:00Z" },
  champion: true,
  answers: { count: 6, excluded: 2 },
  notes: { count: 3, excluded: 0 },
  transcripts: { count: 4, excluded: 1 },
  prep: { count: 1, excluded: 0 },
  rate_notes: { count: 2, excluded: 0 },
  defaults: { answers: true, notes: true, transcripts: false, prep: false },
  last_used: null,
};

describe("initialAiSources — przełączniki na start", () => {
  it("bez wersji z wyborem: domyślne z serwera", () => {
    expect(initialAiSources(DATA)).toEqual({ answers: true, notes: true, transcripts: false, prep: false });
  });

  it("wybór, z którego powstała bieżąca wersja, wygrywa z domyślnymi", () => {
    expect(
      initialAiSources({ ...DATA, last_used: { answers: false, notes: true, transcripts: true, prep: false } }),
    ).toEqual({ answers: false, notes: true, transcripts: true, prep: false });
  });

  it("brakujący klucz bierze z domyślnych serwera, a bez nich — z lustra frontu", () => {
    expect(initialAiSources({ defaults: { prep: true }, last_used: { transcripts: true } })).toEqual({
      ...CV_AI_SOURCE_DEFAULTS,
      transcripts: true,
      prep: true,
    });
    expect(initialAiSources(null)).toEqual(CV_AI_SOURCE_DEFAULTS);
  });
});

describe("aiSourceRows — „Z czego powstało”", () => {
  it("oryginał i Champion zawsze, cztery przełączniki, notatki ze stawką zawsze wycinane", () => {
    const rows = aiSourceRows(DATA);
    expect(rows.map((row) => [row.id, row.mode])).toEqual([
      ["original", "always"],
      ["champion", "always"],
      ["answers", "toggle"],
      ["notes", "toggle"],
      ["transcripts", "toggle"],
      ["prep", "toggle"],
      ["rate_notes", "never"],
    ]);
    const detail = Object.fromEntries(rows.map((row) => [row.id, row.detail]));
    expect(detail.original).toBe("Anna_Przykladowa_CV.pdf");
    expect(detail.answers).toBe("6 odpowiedzi, 2 przeczą pytaniu — nie są dowodem");
    expect(detail.notes).toBe("3 notatki");
    expect(detail.transcripts).toBe("4 rozmowy, 1 spoza tej rekrutacji nie wchodzi");
    expect(detail.prep).toBe("1 podsumowanie");
    expect(detail.rate_notes).toBe("zawsze wycinane · 2 notatki");
  });

  it("odmiana i braki: jedna przecząca, pięć spoza okna, brak pliku i Championa", () => {
    const rows = aiSourceRows({
      ...DATA,
      original_cv: null,
      champion: false,
      answers: { count: 1, excluded: 1 },
      notes: { count: 0, excluded: 0 },
      transcripts: { count: 5, excluded: 5 },
      prep: { count: 0, excluded: 0 },
      rate_notes: { count: 0, excluded: 0 },
    });
    const byId = Object.fromEntries(rows.map((row) => [row.id, row]));
    expect(byId.original).toMatchObject({ mode: "missing", detail: "brak pliku CV — dodaj go na profilu kandydata" });
    expect(byId.champion).toMatchObject({ mode: "missing", detail: "brak" });
    expect(byId.answers.detail).toBe("1 odpowiedź, 1 przeczy pytaniu — nie jest dowodem");
    expect(byId.notes).toMatchObject({ detail: "brak notatek w tej rekrutacji", empty: true });
    // Wszystkie rozmowy sprzed okna rekrutacji — przełącznik nic by nie zmienił.
    expect(byId.transcripts).toMatchObject({ detail: "5 rozmów, 5 spoza tej rekrutacji nie wchodzi", empty: true });
    expect(byId.prep.empty).toBe(true);
    expect(byId.rate_notes.detail).toBe("zawsze wycinane");
  });
});
