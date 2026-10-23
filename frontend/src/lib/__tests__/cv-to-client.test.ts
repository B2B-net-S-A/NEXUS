import { describe, expect, it } from "vitest";

import type { QcCheck } from "@/lib/api/cvQc";
import {
  cvChecksBeforeSending,
  cvToClientShouldPoll,
  forwardProgress,
  pairSourceStageId,
  resolveCvToClient,
  stageCvBadge,
  stageCvOrigin,
  stageCvStatus,
  type StageGeneratedCvRow,
} from "@/lib/cv-to-client";

const row = (overrides: Partial<StageGeneratedCvRow> & { id: number }): StageGeneratedCvRow => ({
  status: "ready",
  ...overrides,
});

describe("stageCvStatus / stageCvBadge", () => {
  it("szkic starego szablonu to „stary szablon”, nie gotowe CV", () => {
    expect(stageCvStatus({ status: "draft", from_generator: false })).toBe("legacy");
    // Plik Word wybrany z profilu (09.10.2026) to zwykły szkic, nie stary szablon.
    expect(stageCvStatus({ status: "draft", from_generator: false, source: "document" })).toBe("ready");
    expect(stageCvBadge({ status: "draft", from_generator: false })?.label).toBe(
      "CV do klienta: stary szablon",
    );
  });

  it("szkic z generatora i wersja zatwierdzona to „CV do klienta”", () => {
    expect(stageCvBadge({ status: "draft", from_generator: true })?.label).toBe("CV do klienta: szkic");
    expect(stageCvBadge({ status: "finalized", from_generator: true })?.label).toBe("CV do klienta: gotowe");
    // Stara ZATWIERDZONA wersja mogła już pójść do klienta — to dokument, nie odczyt.
    expect(stageCvStatus({ status: "finalized", from_generator: false })).toBe("ready");
  });

  it("brak CV nie jest plakietką", () => {
    expect(stageCvBadge({ status: "none" })).toBeNull();
    expect(stageCvBadge(undefined)).toBeNull();
  });
});

describe("resolveCvToClient", () => {
  it("audyt 22.10 (F64): CV odrzucone „Odrzuć to CV” nie wraca jako „Użyj tej wersji”", () => {
    const state = resolveCvToClient({
      branded: { status: "none", generated_document_id: null },
      rows: [row({ id: 7, discarded: true }), row({ id: 5, discarded: true })],
    });
    expect(state.kind).toBe("none");
    expect(state.candidate).toBeNull();
    // Nowa generacja po odrzuceniu jest znowu CV do podpięcia.
    const fresh = resolveCvToClient({
      branded: { status: "none", generated_document_id: null },
      rows: [row({ id: 9 }), row({ id: 7, discarded: true })],
    });
    expect(fresh.kind).toBe("unattached");
    expect(fresh.candidate?.id).toBe(9);
  });

  it("gotowe CV niesie brak zgody RODO i auto-CV do przejrzenia (bez osobnego licznika kontroli AI)", () => {
    const state = resolveCvToClient({
      branded: { status: "draft", from_generator: true, generated_document_id: 5 },
      rows: [
        row({
          id: 5,
          origin: "auto",
          needs_review: true,
          consent_missing: true,
          factual_review: { status: "advisory", findings: 2 },
        }),
      ],
    });
    expect(state.kind).toBe("ready");
    // Od 13.10.2026 liczba rzeczy do sprawdzenia jest jedna (`cvChecksBeforeSending`).
    expect(state).not.toHaveProperty("findings");
    expect(state.consentMissing).toBe(true);
    expect(state.needsReview).toBe(true);
    expect(state.candidate).toBeNull();
  });

  it("nowsza gotowa generacja obok podpiętej = „Użyj nowej wersji”, ale nie drugi język z tego samego pakietu", () => {
    const withNewer = resolveCvToClient({
      branded: { status: "finalized", from_generator: true, generated_document_id: 5 },
      rows: [row({ id: 5, package_id: 1 }), row({ id: 9, package_id: 2 })],
    });
    expect(withNewer.candidate?.id).toBe(9);

    const sibling = resolveCvToClient({
      branded: { status: "finalized", from_generator: true, generated_document_id: 5 },
      rows: [row({ id: 5, package_id: 1, language: "pl" }), row({ id: 6, package_id: 1, language: "en" })],
    });
    expect(sibling.candidate).toBeNull();
  });

  it("generacja w toku bez CV etapu = „generuje się” i odpytywanie", () => {
    const state = resolveCvToClient({
      branded: { status: "none" },
      rows: [row({ id: 3, status: "processing", origin: "auto" })],
    });
    expect(state.kind).toBe("generating");
    expect(cvToClientShouldPoll(state, null)).toBe(true);
  });

  it("nowa generacja obok gotowego CV też jest odpytywana (pojawi się „Użyj nowej wersji”)", () => {
    const state = resolveCvToClient({
      branded: { status: "finalized", from_generator: true, generated_document_id: 5 },
      rows: [row({ id: 5 }), row({ id: 6, status: "processing" })],
    });
    expect(state.kind).toBe("ready");
    expect(state.generating?.id).toBe(6);
    expect(cvToClientShouldPoll(state, null)).toBe(true);
  });

  it("zlecona z karty generacja, która padła, to „failed” z powodem", () => {
    const state = resolveCvToClient({
      branded: { status: "none" },
      rows: [row({ id: 4, status: "failed", error_message: "Brak pliku CV." })],
      pendingGeneratedId: 4,
    });
    expect(state.kind).toBe("failed");
    expect(state.failed?.error_message).toBe("Brak pliku CV.");
    expect(cvToClientShouldPoll(state, 4)).toBe(false);
  });

  it("gotowe CV bez podpięcia = „unattached”; czekamy na serwer, dopóki zlecone z karty", () => {
    const state = resolveCvToClient({
      branded: { status: "none" },
      rows: [row({ id: 7 })],
      pendingGeneratedId: 7,
    });
    expect(state.kind).toBe("unattached");
    expect(state.candidate?.id).toBe(7);
    expect(cvToClientShouldPoll(state, 7)).toBe(true);
    expect(cvToClientShouldPoll(state, null)).toBe(false);
  });

  it("stary szablon zostaje tylko do odczytu, a gotowa generacja jest proponowana obok", () => {
    const state = resolveCvToClient({
      branded: { status: "draft", from_generator: false },
      rows: [row({ id: 8 })],
    });
    expect(state.kind).toBe("legacy");
    expect(state.candidate?.id).toBe(8);
  });

  it("nic nie ma = „none”", () => {
    expect(resolveCvToClient({ branded: { status: "none" }, rows: [] }).kind).toBe("none");
  });
});

describe("pairSourceStageId (runda 12)", () => {
  it("wskazuje wiersz pary tylko wtedy, gdy bieżący wiersz nie ma CV", () => {
    expect(pairSourceStageId({ status: "none", pair_source_stage_id: 20 })).toBe(20);
    expect(pairSourceStageId({ status: "draft", pair_source_stage_id: 20 })).toBeNull();
    expect(pairSourceStageId({ status: "none" })).toBeNull();
    expect(pairSourceStageId({ status: "none", pair_source_stage_id: null })).toBeNull();
    expect(pairSourceStageId(undefined)).toBeNull();
  });
});

describe("CV wybrane zamiast generacji (12.10.2026)", () => {
  const CHOSEN_AT = "2026-10-12T10:00:00Z";
  const copy = (extra: Record<string, unknown> = {}) => ({
    status: "draft",
    from_generator: true,
    generated_document_id: null,
    source: "generator",
    origin: { kind: "stage_copy", label: "ZOB-9000", selected_at: CHOSEN_AT },
    ...extra,
  });

  it("starsza generacja nie jest „nowszą wersją” świeżo wybranego CV", () => {
    // Auto-CV z rana i kopia wybrana o 10:00 — karta nie może radzić nadpisania.
    const state = resolveCvToClient({
      branded: copy(),
      rows: [row({ id: 40, origin: "auto", created_at: "2026-10-12T08:00:00Z" })],
    });
    expect(state.kind).toBe("ready");
    expect(state.candidate).toBeNull();
    expect(state.attached).toBeNull();
  });

  it("generacja zlecona PO wyborze jest proponowana jako „Użyj nowej wersji”", () => {
    const state = resolveCvToClient({
      branded: copy(),
      rows: [row({ id: 41, created_at: "2026-10-12T11:30:00Z" })],
    });
    expect(state.candidate?.id).toBe(41);
  });

  it("generacja bez daty nie przykrywa wyboru; szkic sprzed 12.10 działa jak dotąd", () => {
    expect(resolveCvToClient({ branded: copy(), rows: [row({ id: 42 })] }).candidate).toBeNull();
    const before = resolveCvToClient({
      branded: { status: "draft", from_generator: false, source: "document", generated_document_id: null },
      rows: [row({ id: 43, created_at: "2026-10-09T09:00:00Z" })],
    });
    expect(before.candidate?.id).toBe(43);
  });

  it("brak zgody czyta z samej kopii, bo wiersza generatora nie ma", () => {
    const missing = resolveCvToClient({ branded: copy({ consent_missing: true }), rows: [] });
    expect(missing.consentMissing).toBe(true);
    expect(missing.attached).toBeNull();
    expect(resolveCvToClient({ branded: copy(), rows: [] }).consentMissing).toBe(false);
  });

  it("plakietka mówi, skąd CV; ostrzeżenie przy przepięciu schodzi po zatwierdzeniu", () => {
    expect(stageCvOrigin(copy())).toMatchObject({ badge: "z rekrutacji ZOB-9000", tone: "neutral" });
    const carried = copy({ origin: { kind: "reassign", label: "ZOB-9000", selected_at: CHOSEN_AT } });
    expect(stageCvOrigin(carried)).toMatchObject({
      badge: "przeniesione z rekrutacji ZOB-9000 — sprawdź przed wysyłką",
      tone: "warning",
    });
    expect(stageCvOrigin({ ...carried, status: "finalized" })).toMatchObject({
      badge: "przeniesione z rekrutacji ZOB-9000",
      tone: "neutral",
    });
    expect(
      stageCvOrigin(copy({ source: "document", from_generator: false, origin: { kind: "upload", label: "CV_gotowe.docx" } })),
    ).toMatchObject({
      badge: "z pliku Word",
      sentence: "Wczytane z pliku CV_gotowe.docx. Treść przeniesiona bez AI — sprawdź układ w edytorze.",
    });
    // Szkic z pliku sprzed 12.10 nie ma `origin` — zostaje plakietka po źródle.
    expect(stageCvOrigin({ status: "draft", from_generator: false, source: "document" })?.badge).toBe("z pliku Word");
    expect(stageCvOrigin(copy({ origin: { kind: "generated_other_job" } }))?.badge).toBe("z innej rekrutacji");
  });

  it("kopia CV wczytanego z pliku Word nie twierdzi, że nagłówek jest już poprawiony", () => {
    // Serwer podmienia tytuł tylko w treści z generatora — nagłówek z pliku
    // zostaje (bywa w nim numer zapytania innego klienta).
    for (const kind of ["reassign", "stage_copy"]) {
      const word = stageCvOrigin(
        copy({ source: "document", from_generator: false, origin: { kind, label: "ZOB-9000" } }),
      );
      expect(word?.sentence).not.toContain("Nagłówek ma tytuł tej rekrutacji");
      expect(word?.sentence).toContain("Nagłówek pochodzi z pliku Word — sprawdź go przed wysyłką.");
      expect(stageCvOrigin(copy({ origin: { kind, label: "ZOB-9000" } }))?.sentence).toContain(
        "Nagłówek ma tytuł tej rekrutacji.",
      );
    }
  });

  it("CV z generatora tej rekrutacji i brak CV nie mają plakietki pochodzenia", () => {
    expect(stageCvOrigin({ status: "draft", from_generator: true, generated_document_id: 7 })).toBeNull();
    expect(stageCvOrigin({ status: "none" })).toBeNull();
    expect(stageCvOrigin({ status: "draft", from_generator: false })).toBeNull();
  });
});

describe("cvChecksBeforeSending — jedna liczba na karcie (13.10.2026)", () => {
  const check = (partial: Partial<QcCheck> & Pick<QcCheck, "key">): QcCheck => ({
    label: partial.key,
    severity: "warning",
    status: "fail",
    summary: null,
    items: [],
    ...partial,
  });

  it("QC (blokujące pozycje + niewyciszone uwagi), generator i kontrola AI razem", () => {
    const checks = [
      check({
        key: "critical_skills",
        severity: "blocking",
        items: [
          { requirement: "Kafka", role: "Bank — Dev", role_index: 0 },
          { requirement: "Kafka", role: "Sklep — Dev", role_index: 1 },
          { requirement: "Docker" },
        ],
      }),
      check({ key: "must_bolded", items: [{ requirement: "Java", term: "Java", fix: "bold_all" }] }),
      check({ key: "dates", muted: true, items: [{ detail: "Brak dat" }] }),
      check({ key: "spelling", status: "pass" }),
    ];
    expect(
      cvChecksBeforeSending({
        checks,
        warnings: ["WERYFIKUJ: usunięto „OpenTelemetry” z umiejętności", "Wyróżnienia: pogrubiono 4 terminy."],
        findings: [{ text: "Przeglądy kodu.", status: "unsupported" }],
      }),
      // 2 wymagania krytyczne + 1 uwaga QC + 1 uwaga generatora + 1 kontrola AI; wyciszona i informacja nie.
    ).toBe(5);
  });

  it("„MUST-HAVE: X” od generatora nie liczy się drugi raz, gdy QC ma pozycję X", () => {
    const checks = [
      check({ key: "must_in_cv", items: [{ requirement: "Apache Kafka", detail: "Brak w CV" }] }),
    ];
    expect(
      cvChecksBeforeSending({ checks, warnings: ["MUST-HAVE: Kafka", "MUST-HAVE: Kubernetes"], findings: [] }),
    ).toBe(2);
  });

  it("bez uwag to zero", () => {
    expect(cvChecksBeforeSending({ checks: [check({ key: "dates", status: "pass" })], warnings: [], findings: [] })).toBe(0);
  });
});

describe("po „Zapisz i przekaż dalej” (14.10.2026)", () => {
  const none = resolveCvToClient({ branded: { status: "none" }, rows: [] });

  it("21.10.2026: karta w stanie „brak” nie czeka na automat", () => {
    expect(cvToClientShouldPoll(none, null)).toBe(false);
  });

  const LOADING = { status: "loading" as const, count: 0 };
  const base = { origin: null, skipReason: null, checks: LOADING };

  it("brak CV: CV czeka na rekrutera; powód pominięcia tylko w trybie automatu", () => {
    expect(forwardProgress({ ...base, state: none })).toEqual({
      cv: { tone: "pending", text: "CV czeka na Ciebie — potwierdź niżej, z czego je zrobić" },
      qc: { tone: "pending", text: "QC — po CV" },
      waiting: false,
    });
    expect(forwardProgress({ ...base, state: none, skipReason: "reguła klienta wymaga zrzutu zgody RODO" }).cv).toEqual({
      tone: "info",
      text: "CV nie powstało automatycznie: reguła klienta wymaga zrzutu zgody RODO",
    });
  });

  it("gotowe CV: źródło gotowego CV i stan QC", () => {
    const ready = { kind: "ready" as const };
    expect(forwardProgress({ ...base, state: ready, origin: { badge: "z pliku Word" } }).cv.text).toBe(
      "CV firmowe: z pliku Word",
    );
    expect(forwardProgress({ ...base, state: ready }).cv.text).toBe("CV gotowe");
    expect(forwardProgress({ ...base, state: ready }).qc.text).toBe("QC: liczę…");
    expect(forwardProgress({ ...base, state: ready, checks: { status: "ready", count: 3 } }).qc).toEqual({
      tone: "warn",
      text: "QC: 3 do poprawy",
    });
    expect(forwardProgress({ ...base, state: ready, checks: { status: "ready", count: 0 } }).qc.text).toBe("QC: bez uwag");
    expect(forwardProgress({ ...base, state: ready, checks: { status: "failed", count: 0 } }).qc.text).toBe(
      "QC: nie udało się policzyć",
    );
  });

  it("generacja w toku i nieudana", () => {
    expect(forwardProgress({ ...base, state: { kind: "generating" } }).waiting).toBe(true);
    expect(forwardProgress({ ...base, state: { kind: "failed" } }).cv.tone).toBe("warn");
  });

  it("dzwonek obiecuje tylko automat: po pominięciu i przy generacji z karty nie", () => {
    const generating = { kind: "generating" } as const;
    const afterSkip = forwardProgress({ ...base, state: generating, skipReason: "brak pliku CV" });
    expect(afterSkip.cv.tone).toBe("busy");
    expect(afterSkip.waiting).toBe(false);
    expect(forwardProgress({ ...base, state: generating, manual: true }).waiting).toBe(false);
  });
});
