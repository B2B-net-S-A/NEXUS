import { describe, expect, it } from "vitest";

import {
  fileAddedLabel,
  formatFileDate,
  isClientCvFilename,
  sortCandidateFiles,
  splitClientCvFiles,
  type CandidateFileListItem,
} from "@/lib/candidate-files";

function doc(partial: Partial<CandidateFileListItem> & { id: number }): CandidateFileListItem {
  return {
    is_primary: false,
    uploaded_at: null,
    created_at: "2026-01-01T10:00:00Z",
    external_source: "manual",
    uploaded_by_name: null,
    ...partial,
  };
}

describe("candidate-files", () => {
  it("główne CV pierwsze, potem najnowsze — data wgrania, a bez niej utworzenia", () => {
    const sorted = sortCandidateFiles([
      doc({ id: 1, uploaded_at: "2026-03-01T10:00:00Z" }),
      doc({ id: 2, is_primary: true, uploaded_at: "2025-01-01T10:00:00Z" }),
      doc({ id: 3, uploaded_at: null, created_at: "2026-05-01T10:00:00Z" }),
      doc({ id: 4, uploaded_at: "2026-04-01T10:00:00Z" }),
    ]);
    expect(sorted.map((d) => d.id)).toEqual([2, 3, 4, 1]);
  });

  it("podpis: data i osoba, „z Traffita” albo sama data", () => {
    expect(
      fileAddedLabel(
        doc({ id: 1, uploaded_at: "2026-09-29T08:00:00Z", uploaded_by_name: "Anna Nowak" }),
      ),
    ).toBe("dodano 29.09.2026 · Anna Nowak");
    expect(
      fileAddedLabel(doc({ id: 2, external_source: "traffit", created_at: "2026-05-05T08:00:00Z" })),
    ).toBe("dodano 05.05.2026 · z Traffita");
    expect(fileAddedLabel(doc({ id: 3, created_at: "2026-02-03T08:00:00Z" }))).toBe(
      "dodano 03.02.2026",
    );
  });

  it("dzień liczony w strefie firmy (Europe/Warsaw)", () => {
    expect(formatFileDate("2026-09-29T22:30:00Z")).toBe("30.09.2026");
    expect(formatFileDate("nie-data")).toBeNull();
  });
});

describe("isClientCvFilename / splitClientCvFiles (D4, 04.10.2026)", () => {
  it("rozpoznaje „B2B” jako osobny człon nazwy", () => {
    expect(isClientCvFilename("Jan_Kowalski_B2B_PKO.docx")).toBe(true);
    expect(isClientCvFilename("CV B2B.pdf")).toBe(true);
    expect(isClientCvFilename("b2b-cv.docx")).toBe(true);
    expect(isClientCvFilename("cv.pdf")).toBe(false);
    expect(isClientCvFilename("b2bnetwork_logo.png")).toBe(false);
    expect(isClientCvFilename(null)).toBe(false);
  });

  it("dzieli listę bez zmiany kolejności", () => {
    const docs = [
      { ...doc({ id: 1 }), filename: "cv.pdf" },
      { ...doc({ id: 2 }), filename: "A_B2B.docx" },
      { ...doc({ id: 3 }), filename: "list.pdf" },
    ];
    const { own, client } = splitClientCvFiles(docs);
    expect(own.map((d) => d.id)).toEqual([1, 3]);
    expect(client.map((d) => d.id)).toEqual([2]);
  });
});
