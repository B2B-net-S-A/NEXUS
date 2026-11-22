import { describe, expect, it } from "vitest";

import type { PairStartDocs } from "@/lib/api/start-documents";
import type { ContractDocument } from "@/lib/contract-document-folders";

import {
  agreementDocument,
  entryProgress,
  legacyProgress,
  ofSteps,
  percentOf,
  relativeDayPl,
  startDocsCheck,
  startListSource,
  startSubtitle,
} from "../start-progress";

const TODAY = "2026-11-20";

describe("startListSource", () => {
  it("wyłączony moduł (404) albo `module_on: false` to stara lista", () => {
    expect(startListSource({ notFound: true, view: undefined })).toBe("legacy");
    expect(startListSource({ notFound: false, view: { module_on: false } })).toBe("legacy");
    expect(startListSource({ notFound: false, view: { module_on: true } })).toBe("entry");
  });

  it("bez odpowiedzi nie zgadujemy", () => {
    expect(startListSource({ notFound: false, view: undefined })).toBeNull();
    expect(startListSource({ notFound: false, view: null })).toBeNull();
  });
});

describe("postęp listy", () => {
  it("lista wejścia: zrobione i pominięte zamykają pozycję", () => {
    const progress = entryProgress(
      [{ status: "done" }, { status: "skipped" }, { status: "open" }, { status: "open" }],
      "2026-11-09T23:30:00Z",
    );
    expect(progress).toEqual({ done: 2, total: 4, createdOn: "2026-11-10" });
  });

  it("stara lista: „nie dotyczy” wypada z kroków, data założenia z pierwszej pozycji", () => {
    const progress = legacyProgress([
      { status: "done", created_at: "2026-11-02T10:00:00Z" },
      { status: "na", created_at: "2026-11-01T10:00:00Z" },
      { status: "pending", created_at: "2026-11-03T10:00:00Z" },
    ]);
    expect(progress).toEqual({ done: 1, total: 2, createdOn: "2026-11-01" });
    expect(legacyProgress([])).toEqual({ done: 0, total: 0, createdOn: null });
  });

  it("kroki z dopełniaczem i procent bez dzielenia przez zero", () => {
    expect(ofSteps(0, 8)).toBe("0 z 8 kroków");
    expect(ofSteps(1, 1)).toBe("1 z 1 kroku");
    expect(percentOf({ done: 1, total: 3 })).toBe(33);
    expect(percentOf({ done: 0, total: 0 })).toBe(0);
  });
});

describe("relativeDayPl", () => {
  it("liczy dni kalendarza, nie godziny", () => {
    expect(relativeDayPl("2026-11-20", TODAY)).toBe("dziś");
    expect(relativeDayPl("2026-11-21", TODAY)).toBe("jutro");
    expect(relativeDayPl("2026-11-19", TODAY)).toBe("wczoraj");
    expect(relativeDayPl("2026-12-01", TODAY)).toBe("za 11 dni");
    expect(relativeDayPl("2026-11-15", TODAY)).toBe("5 dni temu");
  });
});

describe("startSubtitle", () => {
  it("przed startem: kiedy i że listy jeszcze nie ma", () => {
    expect(startSubtitle({ startDate: "2026-12-01", today: TODAY, progress: null })).toBe(
      "Start 01.12.2026 (za 11 dni) · listy startowej jeszcze nie ma",
    );
  });

  it("po starcie bez listy to normalne — tylko informacja", () => {
    expect(startSubtitle({ startDate: "2018-03-19", today: TODAY, progress: { done: 0, total: 0, createdOn: null } })).toBe(
      "Współpraca od 19.03.2018 · listy startowej nie założono",
    );
  });

  it("z listą: dzień założenia i stan odhaczenia", () => {
    expect(
      startSubtitle({ startDate: "2023-05-11", today: TODAY, progress: { done: 0, total: 8, createdOn: "2026-06-26" } }),
    ).toBe("Współpraca od 11.05.2023 · lista założona 26.06.2026 · nic jeszcze nie odhaczono");
    expect(startSubtitle({ startDate: null, today: TODAY, progress: { done: 3, total: 3, createdOn: null } })).toBe(
      "Kontrakt bez daty startu · wszystko odhaczone",
    );
  });
});

function doc(id: number, docType: string, createdAt: string): ContractDocument {
  return {
    id,
    contract_id: 1,
    filename: `plik-${id}.pdf`,
    doc_type: docType,
    content_type: "application/pdf",
    size_bytes: 1,
    expiry_date: null,
    uploaded_by: null,
    uploaded_by_email: null,
    created_at: createdAt,
  };
}

describe("agreementDocument", () => {
  it("najnowsza umowa, aneks i zamówienie się nie liczą", () => {
    const docs = [doc(1, "contract", "2026-01-01T10:00:00Z"), doc(2, "annex", "2026-06-01T10:00:00Z"), doc(3, "contract", "2026-03-01T10:00:00Z")];
    expect(agreementDocument(docs)?.id).toBe(3);
    expect(agreementDocument([doc(4, "order", "2026-01-01T10:00:00Z")])).toBeNull();
    expect(agreementDocument(undefined)).toBeNull();
  });
});

function pair(overrides: Partial<PairStartDocs> = {}): PairStartDocs {
  const item = (id: number, name: string, state: PairStartDocs["items"][number]["state"]) => ({
    id,
    name,
    note: null,
    kind: "file" as const,
    required: true,
    offset_days: 0,
    link_url: null,
    fill_from_agreement: false,
    template_name: null,
    state,
    deadline: null,
    file_name: null,
    has_value: false,
    delivered_at: null,
    delivered_by_name: null,
    checked_at: null,
    checked_by_name: null,
    reason: null,
    reason_by_name: null,
  });
  return {
    candidate_id: 1,
    job_id: 2,
    client_id: 3,
    client_name: "Bank Przykładowy",
    start_date: "2026-12-01",
    deadline: "2026-11-28",
    tone: "calm",
    working: false,
    done: 1,
    total: 3,
    recruiter_name: null,
    delivery_lead_name: null,
    agreement_number: null,
    list_sent_at: null,
    items: [item(1, "NDA", "delivered"), item(2, "Oświadczenie o niekaralności", "missing"), item(3, "Wyciąg z KRK", "returned")],
    permissions: { can_work: false, can_review: false, can_download: false, can_view_pesel: false },
    ...overrides,
  };
}

describe("startDocsCheck", () => {
  it("braki z nazwy, liczba i termin; po terminie to brak, nie „do sprawdzenia”", () => {
    expect(startDocsCheck({ hasJob: true, pair: pair(), clientList: null, today: TODAY })).toEqual({
      state: "check",
      detail: "Brakuje: Oświadczenie o niekaralności, Wyciąg z KRK · 1 z 3 gotowe · termin 28.11.2026.",
      target: "documents",
    });
    expect(startDocsCheck({ hasJob: true, pair: pair({ deadline: "2026-11-18" }), clientList: null, today: TODAY }).state).toBe(
      "missing",
    );
  });

  it("komplet i lista bez pozycji dla tej osoby to „jest”", () => {
    expect(startDocsCheck({ hasJob: true, pair: pair({ done: 3, total: 3 }), clientList: null, today: TODAY }).state).toBe("ok");
    expect(startDocsCheck({ hasJob: true, pair: pair({ done: 0, total: 0, items: [] }), clientList: null, today: TODAY }).detail).toBe(
      "Nic z listy klienta nie dotyczy tej osoby.",
    );
  });

  it("bez listy u klienta: jawna decyzja klienta albo „nie wiadomo”", () => {
    const decided = startDocsCheck({
      hasJob: true,
      pair: null,
      clientList: { items: [], not_required: { at: "2026-11-19T12:00:00Z", by_name: "Kamil Testowy" } },
      today: TODAY,
    });
    expect(decided).toEqual({
      state: "ok",
      detail: "Klient nie wymaga dokumentów do startu (zaznaczono 19.11.2026).",
      target: "client",
    });
    expect(startDocsCheck({ hasJob: true, pair: null, clientList: undefined, today: TODAY }).state).toBe("check");
  });

  it("kontrakt bez rekrutacji nie ma pary — mówimy to wprost", () => {
    expect(startDocsCheck({ hasJob: false, pair: undefined, clientList: undefined, today: TODAY }).detail).toMatch(
      /Kontrakt bez rekrutacji/,
    );
  });
});
