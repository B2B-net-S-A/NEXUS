import { describe, expect, it } from "vitest";

import {
  autoCvSkipReason,
  backgroundEventMessage,
  backgroundEventTone,
  latestAutoCvSkip,
  type JobBackgroundEvent,
} from "@/lib/job-background-events";

const ev = (extra: Partial<JobBackgroundEvent>): JobBackgroundEvent => ({
  id: 1,
  kind: "auto_full_review",
  created_at: "2026-09-21T05:00:00Z",
  ...extra,
});

describe("job-background-events", () => {
  it("zdania po polsku z poprawną liczbą mnogą", () => {
    expect(backgroundEventMessage(ev({ proposals: 1, eligible: 5 }))).toBe(
      "Automatyczny przegląd bazy: 1 nowa propozycja (wymagania spełnia 5 osób).",
    );
    expect(backgroundEventMessage(ev({ proposals: 0 }))).toBe(
      "Automatyczny przegląd bazy: bez nowych propozycji.",
    );
    expect(backgroundEventMessage(ev({ kind: "new_cv_proposals", count: 3, trigger: "cv_ingest" }))).toBe(
      "Nowe CV w bazie: 3 propozycje.",
    );
    expect(backgroundEventMessage(ev({ kind: "new_cv_proposals", count: 5, trigger: "job_publish" }))).toBe(
      "Po publikacji rekrutacji: 5 propozycji.",
    );
  });

  it("auto-CV: stan dokumentu czytany na żywo; zredagowane nazwisko to „Kandydat #id”", () => {
    const base = { kind: "cv_auto_generate", candidate: { id: 7, name: null }, generated_id: 3 };
    expect(backgroundEventMessage(ev({ ...base, document_status: "processing" }))).toBe(
      "Kandydat #7: CV generuje się automatycznie po weryfikacji…",
    );
    expect(backgroundEventMessage(ev({ ...base, candidate: { id: 7, name: "Ola Kot" }, document_status: "ready" }))).toBe(
      "Ola Kot: CV wygenerowane automatycznie — sprawdź przed wysyłką.",
    );
    expect(backgroundEventTone(ev({ ...base, document_status: "failed" }))).toBe("failed");
    expect(backgroundEventTone(ev({ ...base, document_status: "ready" }))).toBe("neutral");
  });

  it("awarie niosą polski powód z serwera; pominięcie ma własny ton", () => {
    const failed = ev({ kind: "new_cv_proposals_failed", reason: "AutoMatchUnavailable", message: "Wyszukiwanie semantyczne było niedostępne." });
    expect(backgroundEventMessage(failed)).toBe(
      "Propozycje z nowych CV nie powstały. Wyszukiwanie semantyczne było niedostępne.",
    );
    expect(backgroundEventTone(failed)).toBe("failed");
    expect(backgroundEventTone(ev({ kind: "cv_auto_generate_skipped" }))).toBe("skipped");
    expect(backgroundEventMessage(ev({ kind: "cos_nowego", message: null }))).toBe("Zdarzenie automatu.");
  });

  it("powody pominięcia: znany kod, walidacja generatora, nieznany kod bez udawania", () => {
    expect(autoCvSkipReason({ reason: "consent_screenshot_required" })).toBe(
      "reguła klienta wymaga zrzutu zgody RODO",
    );
    expect(autoCvSkipReason({ reason: "client_rule_inputs_missing", detail: "Brak stanowiska." })).toBe(
      "reguła klienta wymaga danych, których automat nie ma (Brak stanowiska)",
    );
    expect(autoCvSkipReason({ reason: "generation_unavailable", detail: "503" })).toBe("generator CV był niedostępny");
    expect(autoCvSkipReason({ reason: "already_generated" })).toBe(
      "CV z tego samego pliku już wygenerowano w tej rekrutacji — nowego nie tworzono",
    );
    expect(autoCvSkipReason({ reason: "xyz" })).toBe("powód: xyz");
    expect(autoCvSkipReason({})).toBe("powód nieznany");
  });

  it("latestAutoCvSkip: rozstrzyga NAJNOWSZE zdarzenie auto-CV tej osoby", () => {
    const skip = ev({ id: 2, kind: "cv_auto_generate_skipped", candidate: { id: 5, name: null } });
    const started = ev({ id: 3, kind: "cv_auto_generate", candidate: { id: 5, name: null } });
    const other = ev({ id: 4, kind: "cv_auto_generate_skipped", candidate: { id: 6, name: null } });
    expect(latestAutoCvSkip([other, skip], 5)).toBe(skip);
    expect(latestAutoCvSkip([started, skip], 5)).toBeNull();
    expect(latestAutoCvSkip([ev({})], 5)).toBeNull();
  });
});
