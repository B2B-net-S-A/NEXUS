import { describe, expect, it } from "vitest";

import {
  complianceRelevantDocs,
  filesLabel,
  folderNameSuggestions,
  isDocumentDuplicate,
  type ContractDocument,
} from "@/lib/contract-document-folders";

function doc(
  id: number,
  doc_type: string,
  folder_id: number | null = null,
  created_at = `2026-10-${String(id).padStart(2, "0")}T10:00:00Z`,
): ContractDocument {
  return {
    id,
    contract_id: 1,
    filename: `plik-${id}.pdf`,
    doc_type,
    content_type: "application/pdf",
    size_bytes: 100 * id,
    expiry_date: null,
    uploaded_by: null,
    uploaded_by_email: null,
    created_at,
    folder_id,
  };
}

describe("isDocumentDuplicate", () => {
  const refusal = (status: number, code: string) => ({
    response: { status, data: { detail: { code, message: "Ten plik jest już…" } } },
  });

  it("recognises only the 409 document_duplicate refusal", () => {
    expect(isDocumentDuplicate(refusal(409, "document_duplicate"))).toBe(true);
    expect(isDocumentDuplicate(refusal(409, "duplicate_contractor"))).toBe(false);
    expect(isDocumentDuplicate(refusal(413, "document_duplicate"))).toBe(false);
    expect(isDocumentDuplicate({ response: { status: 409, data: { detail: "x" } } })).toBe(
      false,
    );
    expect(isDocumentDuplicate(new Error("network"))).toBe(false);
    expect(isDocumentDuplicate(null)).toBe(false);
  });
});

describe("filesLabel", () => {
  it.each([
    [1, "1 plik"],
    [2, "2 pliki"],
    [4, "4 pliki"],
    [5, "5 plików"],
    [12, "12 plików"],
    [14, "14 plików"],
    [22, "22 pliki"],
    [0, "0 plików"],
  ])("%i → %s", (n, label) => {
    expect(filesLabel(n)).toBe(label);
  });
});

describe("folderNameSuggestions", () => {
  it("puts detected contract names first and skips names already used", () => {
    const names = folderNameSuggestions(
      [
        {
          number: "361-2019",
          folder_name: "Poprzednia umowa – nr 361-2019",
          folder_id: null,
          document_ids: [1],
        },
      ],
      ["archiwum"],
    );
    expect(names).toEqual([
      "Poprzednia umowa – nr 361-2019",
      "Poprzednia umowa",
      "Dokumenty firmy (NIP, ZUS, OC)",
    ]);
  });
});

describe("complianceRelevantDocs", () => {
  it("ignores archived files in folders", () => {
    expect(
      complianceRelevantDocs([doc(1, "oc_policy"), doc(2, "oc_policy", 10)]).map((d) => d.id),
    ).toEqual([1]);
  });
});
