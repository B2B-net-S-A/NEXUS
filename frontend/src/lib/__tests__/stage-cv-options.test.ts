/**
 * Gotowe CV z profilu do wyboru jako CV firmowe rekrutacji (screening,
 * 09.10.2026): CV z generatora tej osoby i pliki Word „…B2B…”.
 */
import { describe, expect, it } from "vitest";

import {
  bestReadyCv,
  buildStageCvOptions,
  CONSENT_AFTER_CHOICE_NOTE,
  CONSENT_CARRIED_NOTE,
  otherReadyCvCount,
} from "../stage-cv-options";

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

const STAGES = [
  { job_id: 300, stage_id: 31, job_title: "DevOps Engineer", reference_number: "ZOB-9000", client_name: "Bank Fikcyjny", status: "finalized", version: 2, language: "pl", updated_at: "2026-10-02T09:00:00Z", updated_by_name: "Anna Wzorcowa", consent_carried: true },
  { job_id: 400, stage_id: 41, job_title: null, reference_number: "REQ-12", client_name: "Firma Testowa", status: "draft", language: "en", updated_at: null },
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

  it("u klienta ze zrzutem zgody kopie da się wybrać — opcja mówi, co ze zgodą", () => {
    // Do 12.10.2026 te opcje były wyszarzone (serwer odmawiał 422).
    const { stages, generated, documents } = buildStageCvOptions({
      stages: STAGES,
      generated: GENERATED,
      documents: DOCUMENTS,
      jobId: 201,
      consentClient: true,
    });
    expect(generated.map((option) => [option.id, option.note])).toEqual([
      [7, null],
      [8, CONSENT_AFTER_CHOICE_NOTE],
    ]);
    expect(documents[0].note).toBe(CONSENT_AFTER_CHOICE_NOTE);
    expect(stages.map((option) => [option.id, option.note])).toEqual([
      [300, CONSENT_CARRIED_NOTE],
      [400, CONSENT_AFTER_CHOICE_NOTE],
    ]);
  });

  it("CV etapu z innych rekrutacji stoją pierwsze, z plakietką statusu", () => {
    const { stages, total } = buildStageCvOptions({ stages: STAGES, generated: [], documents: [], jobId: 201, consentClient: false });
    expect(stages.map((option) => [option.key, option.title, option.origin])).toEqual([
      ["stage:300", "DevOps Engineer", "zatwierdzone · wersja 2"],
      ["stage:400", "REQ-12", "szkic"],
    ]);
    expect(stages[0].detail).toBe("Bank Fikcyjny · ZOB-9000 · PL · 02.10.2026 · Anna Wzorcowa");
    // Bez tytułu numer jest tytułem — nie powtarzamy go w opisie.
    expect(stages[1].detail).toBe("Firma Testowa · EN");
    expect(stages[0].previewStageId).toBe(31);
    expect(stages.every((option) => option.note === null)).toBe(true);
    expect(total).toBe(2);
  });

  it("CV etapu tej rekrutacji nie jest „innym CV”", () => {
    const { stages } = buildStageCvOptions({
      stages: [{ job_id: 201, stage_id: 9, status: "draft" }],
      generated: [],
      documents: [],
      jobId: 201,
      consentClient: false,
    });
    expect(stages).toEqual([]);
  });

  it("generacja z rekrutacji, która ma CV etapu, nie stoi na liście drugi raz", () => {
    const { generated } = buildStageCvOptions({ stages: STAGES, generated: GENERATED, documents: [], jobId: 201, consentClient: false });
    // 5 (rekrutacja 300) znika: jej CV etapu niesie poprawki rekrutera.
    expect(generated.map((option) => option.id)).toEqual([7, 8]);
  });

  it("brak danych to pusta lista, nie błąd", () => {
    expect(buildStageCvOptions({ generated: undefined, documents: undefined, jobId: 1, consentClient: false })).toEqual({
      stages: [],
      generated: [],
      documents: [],
      total: 0,
    });
  });
});

describe("bestReadyCv", () => {
  it("podpowiada CV etapu z innej rekrutacji, potem plik Word, potem generację spoza tej rekrutacji", () => {
    const all = buildStageCvOptions({ stages: STAGES, generated: GENERATED, documents: DOCUMENTS, jobId: 201, consentClient: false });
    expect(bestReadyCv(all)?.key).toBe("stage:300");
    expect(otherReadyCvCount(all)).toBe(4);

    const noStages = buildStageCvOptions({ generated: GENERATED, documents: DOCUMENTS, jobId: 201, consentClient: false });
    expect(bestReadyCv(noStages)?.key).toBe("document:2");

    const onlyGenerated = buildStageCvOptions({ generated: GENERATED, documents: [], jobId: 201, consentClient: false });
    expect(bestReadyCv(onlyGenerated)?.key).toBe("generated:8");
  });

  it("CV z generatora TEJ rekrutacji nie jest podpowiedzią — kartę obsługuje „Użyj tej wersji”", () => {
    const own = buildStageCvOptions({ generated: [{ id: 7, status: "ready", job_id: 201 }], documents: [], jobId: 201, consentClient: false });
    expect(bestReadyCv(own)).toBeNull();
    expect(otherReadyCvCount(own)).toBe(0);
  });
});
