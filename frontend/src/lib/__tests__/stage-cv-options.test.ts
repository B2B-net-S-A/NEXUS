/**
 * Gotowe CV z profilu do wyboru jako CV firmowe rekrutacji (screening,
 * 09.10.2026): CV z generatora tej osoby i pliki Word „…B2B…”.
 */
import { describe, expect, it } from "vitest";

import { buildStageCvOptions, CONSENT_CLIENT_REASON } from "../stage-cv-options";

const doc = (id: number, filename: string, extra: Record<string, unknown> = {}) => ({
  id,
  filename,
  is_primary: false,
  uploaded_at: "2026-09-10T10:00:00Z",
  created_at: "2026-09-10T10:00:00Z",
  external_source: null,
  ...extra,
});

const GENERATED = [
  { id: 5, status: "ready", job_id: 300, client_name: "Bank Fikcyjny", position: "DevOps", language: "en", created_at: "2026-09-20T10:00:00Z", created_by_name: "Anna Wzorcowa" },
  { id: 6, status: "processing", job_id: 201, position: "Tester" },
  { id: 7, status: "ready", job_id: 201, client_name: "Klient Przykładowy", position: "Tester", language: "pl", created_at: "2026-08-01T10:00:00Z" },
  { id: 8, status: "ready", job_id: null, position: null, filename: "CV_B2B_bez_procesu.docx", language: "pl", created_at: "2026-09-25T10:00:00Z" },
  { id: 9, status: "failed", job_id: 201 },
];

const DOCUMENTS = [
  doc(1, "Jan_Fikcyjny_CV.pdf", { is_primary: true }),
  doc(2, "CV_B2B_Jan_Fikcyjny.docx", { uploaded_by_name: "Piotr Przykładowy" }),
  doc(3, "CV_B2B_Jan_Fikcyjny.pdf"),
  doc(4, "Jan_Fikcyjny_CV_EN.docx"),
];

describe("buildStageCvOptions", () => {
  it("pokazuje tylko gotowe CV z generatora; CV tej rekrutacji stoi pierwsze", () => {
    const { generated } = buildStageCvOptions({ generated: GENERATED, documents: [], jobId: 201, consentClient: false });
    expect(generated.map((option) => [option.id, option.origin])).toEqual([
      [7, "ta rekrutacja"],
      [8, "bez rekrutacji"],
      [5, "inna rekrutacja"],
    ]);
    expect(generated[2].title).toBe("DevOps");
    expect(generated[2].detail).toBe("Bank Fikcyjny · EN · 20.09.2026 · Anna Wzorcowa");
    // Bez stanowiska tytułem jest nazwa pliku.
    expect(generated[1].title).toBe("CV_B2B_bez_procesu.docx");
  });

  it("z plików bierze tylko Word z grupy „CV dla klientów”", () => {
    const { documents, total } = buildStageCvOptions({ generated: [], documents: DOCUMENTS, jobId: 201, consentClient: false });
    expect(documents.map((option) => option.id)).toEqual([2]);
    expect(documents[0].title).toBe("CV_B2B_Jan_Fikcyjny.docx");
    expect(documents[0].detail).toBe("dodano 10.09.2026 · Piotr Przykładowy");
    expect(total).toBe(1);
  });

  it("id generatora i pliku mogą się pokryć — klucze są różne", () => {
    const { generated, documents } = buildStageCvOptions({
      generated: [{ id: 2, status: "ready", job_id: 201 }],
      documents: DOCUMENTS,
      jobId: 201,
      consentClient: false,
    });
    expect(generated[0].key).not.toBe(documents[0].key);
  });

  it("u klienta ze zrzutem zgody zostaje tylko CV z generatora tej rekrutacji", () => {
    const { generated, documents } = buildStageCvOptions({ generated: GENERATED, documents: DOCUMENTS, jobId: 201, consentClient: true });
    expect(generated.map((option) => [option.id, option.disabledReason])).toEqual([
      [7, null],
      [8, CONSENT_CLIENT_REASON],
      [5, CONSENT_CLIENT_REASON],
    ]);
    expect(documents[0].disabledReason).toBe(CONSENT_CLIENT_REASON);
  });

  it("brak danych to pusta lista, nie błąd", () => {
    expect(buildStageCvOptions({ generated: undefined, documents: undefined, jobId: 1, consentClient: false })).toEqual({
      generated: [],
      documents: [],
      total: 0,
    });
  });
});
