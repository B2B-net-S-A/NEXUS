import { describe, expect, it } from "vitest";

import {
  fileAddedLabel,
  formatFileDate,
  groupCandidateFiles,
  isClientCvFilename,
  recruitmentCodes,
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

describe("recruitmentCodes (E5, 13.10.2026)", () => {
  it("wyciąga kody „ZOB-2962” i numery Traffita z nawiasu, bez powtórzeń", () => {
    expect(
      recruitmentCodes([
        { job_title: "Java Developer (ZOB-2962)" },
        { job_title: "Analityk biznesowy (42700)" },
        { job_title: "Tester ZOB-2962 — druga tura" },
        { job_title: "PM IT-12345 i PKO-778" },
      ]),
    ).toEqual(["ZOB-2962", "42700", "IT-12345", "PKO-778"]);
  });

  it("pomija rok w nawiasie, krótkie liczby, B2B i brak tytułu", () => {
    expect(
      recruitmentCodes([
        { job_title: "Analityk (2026)" },
        { job_title: "Java (100% zdalnie) (12)" },
        { job_title: "Senior B2B Developer" },
        { job_title: null },
        {},
      ]),
    ).toEqual([]);
    expect(recruitmentCodes(undefined)).toEqual([]);
  });
});

describe("groupCandidateFiles (E5, 13.10.2026)", () => {
  type Doc = CandidateFileListItem & { filename: string; document_kind: string };
  const file = (id: number, filename: string, extra: Partial<Doc> = {}): Doc => ({
    ...doc({ id }),
    filename,
    document_kind: "cv",
    ...extra,
  });

  it("dzieli na CV kandydata, CV dla klientów i załączniki", () => {
    const groups = groupCandidateFiles(
      [
        file(1, "cv.pdf", { is_primary: true }),
        file(2, "Jan_Kowalski_B2B_PKO.docx"),
        file(3, "ZOB-2962_Jan_Kowalski.docx"),
        file(4, "42700_Jan_Kowalski.docx", { document_kind: "other" }),
        file(5, "CV Jan (42700).pdf"),
        file(6, "Załącznik nr 2.docx"),
        file(7, "Zalacznik_3_formularz.pdf"),
        file(8, "Formularz_cenowy.xlsx"),
        file(9, "SWZ_projekt.pdf"),
        file(10, "certyfikat.pdf", { document_kind: "certificate" }),
        file(11, "cv-en.pdf"),
        file(12, "zob_2962_cv.pdf"),
      ],
      ["ZOB-2962", "42700"],
    );
    expect(groups.own.map((d) => d.id)).toEqual([1, 11]);
    expect(groups.client.map((d) => d.id)).toEqual([2, 3, 4, 5, 12]);
    expect(groups.attachments.map((d) => d.id)).toEqual([6, 7, 8, 9, 10]);
  });

  it("główne CV zostaje w „CV kandydata”, nawet z kodem lub „B2B” w nazwie", () => {
    const groups = groupCandidateFiles(
      [
        file(1, "ZOB-2962_CV.pdf", { is_primary: true }),
        file(2, "Formularz_B2B.pdf", { is_primary: false }),
      ],
      ["ZOB-2962"],
    );
    expect(groups.own.map((d) => d.id)).toEqual([1]);
    // Załącznik po nazwie wygrywa z „B2B”.
    expect(groups.attachments.map((d) => d.id)).toEqual([2]);
    expect(groups.client).toEqual([]);
  });

  it("numer rekrutacji pasuje tylko jako osobna liczba, nie fragment dłuższej", () => {
    const groups = groupCandidateFiles(
      [
        file(1, "cv_427001.pdf"),
        file(2, "cv_142700.pdf"),
        file(3, "skan_ZOB-29621.pdf"),
        file(4, "MZOB-2962.pdf"),
      ],
      ["42700", "ZOB-2962"],
    );
    expect(groups.client).toEqual([]);
    expect(groups.own.map((d) => d.id)).toEqual([1, 2, 3, 4]);
  });

  it("bez kodów działa jak dotychczasowa reguła „B2B”, plik nie-CV idzie do załączników", () => {
    const groups = groupCandidateFiles([
      file(1, "cv.pdf"),
      file(2, "A_B2B.docx"),
      file(3, "list.pdf", { document_kind: "cover_letter" }),
    ]);
    expect(groups.own.map((d) => d.id)).toEqual([1]);
    expect(groups.client.map((d) => d.id)).toEqual([2]);
    expect(groups.attachments.map((d) => d.id)).toEqual([3]);
  });
});
