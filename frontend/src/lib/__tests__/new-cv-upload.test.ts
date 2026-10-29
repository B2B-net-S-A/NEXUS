import { describe, expect, it } from "vitest";

import type { StageCvUploadResult } from "@/lib/api";
import { NEW_CV_WAIT_MS, newCvCompanyStep, newCvUploadFrom, type NewCvUpload } from "@/lib/new-cv-upload";

const response = {
  candidate_stage_id: 900,
  candidate_id: 41,
  job_id: 7,
  has_snapshot: true,
  original_cv_filename: "Anna_CV_2026.pdf",
  original_cv_language: "pl",
  original_snapshot_at: "2026-10-29T10:00:00Z",
  original_snapshot_source: "manual_upload",
  download_url: null,
  outcome: "original",
  uploaded_filename: "Anna_CV_2026.pdf",
  uploaded_document_id: 55,
  company_cv: "regenerating",
  company_cv_stage_id: 880,
  company_cv_status: "draft",
  regenerating_document_id: 31,
} satisfies StageCvUploadResult;

function upload(overrides: Partial<NewCvUpload> = {}): NewCvUpload {
  return { ...newCvUploadFrom(response, "x.pdf", 1_000)!, ...overrides };
}

describe("newCvUploadFrom", () => {
  it("bierze z odpowiedzi plik, plan i wiersz CV do klienta pary", () => {
    expect(newCvUploadFrom(response, "x.pdf", 1_000)).toEqual({
      at: 1_000,
      filename: "Anna_CV_2026.pdf",
      documentId: 55,
      plan: "regenerating",
      companyStageId: 880,
      companyStatus: "draft",
      regeneratingId: 31,
      snapshotAt: "2026-10-29T10:00:00Z",
    });
  });

  it("starszy serwer bez company_cv — bloku nie ma", () => {
    expect(newCvUploadFrom({ ...response, company_cv: undefined }, "x.pdf", 1)).toBeNull();
  });
});

describe("newCvCompanyStep", () => {
  it("generuje się, dopóki CV do klienta nie jest z nowej generacji", () => {
    expect(newCvCompanyStep(upload(), 20, 2_000).kind).toBe("generating");
    expect(newCvCompanyStep(upload(), 31, 2_000).kind).toBe("replaced");
  });

  it("po 5 minutach przestaje obiecywać i odsyła do „Użyj nowej wersji”", () => {
    expect(newCvCompanyStep(upload(), 20, 1_000 + NEW_CV_WAIT_MS).kind).toBe("slow");
  });

  it("pyta innym zdaniem o zatwierdzone i o poprawiane CV", () => {
    const finalized = newCvCompanyStep(upload({ plan: "ask", companyStatus: "finalized" }), 20, 2_000);
    const draft = newCvCompanyStep(upload({ plan: "ask", companyStatus: "draft" }), 20, 2_000);
    expect(finalized).toEqual({ kind: "ask", sentence: "CV do klienta jest już zatwierdzone." });
    expect(draft).toEqual({ kind: "ask", sentence: "CV do klienta ktoś już poprawiał albo wybrał." });
  });

  it("brak CV, po „CV wysłane” i formularz klienta — bez generacji", () => {
    expect(newCvCompanyStep(upload({ plan: "confirm" }), null, 2_000).kind).toBe("confirm");
    expect(newCvCompanyStep(upload({ plan: "locked" }), 20, 2_000).kind).toBe("locked");
    expect(newCvCompanyStep(upload({ plan: "none" }), null, 2_000).kind).toBe("none");
  });
});
