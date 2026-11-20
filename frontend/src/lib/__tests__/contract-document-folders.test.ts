import { describe, expect, it } from "vitest";

import type { OrderDocumentItem } from "@/lib/api/dlPortal";
import {
  buildDocumentSections,
  complianceRelevantDocs,
  filesLabel,
  folderNameSuggestions,
  isDocumentDuplicate,
  ORDERS_FOLDER_ID,
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

const ORDER_FILE: OrderDocumentItem = {
  order_id: 77,
  client_id: 5,
  contract_id: 1,
  title: "ZAM-1",
  filename: "zam.pdf",
  content_type: "application/pdf",
  size_bytes: 1000,
  created_at: "2026-09-30T10:00:00Z",
  order_status: "active" as OrderDocumentItem["order_status"],
  uploaded_by_email: null,
  uploaded_at: null,
};

describe("buildDocumentSections", () => {
  const folders = [
    { id: 10, name: "Poprzednia umowa – nr 361-2019", created_at: "2026-10-21T08:00:00Z" },
    { id: 11, name: "Pusty", created_at: "2026-10-21T09:00:00Z" },
  ];

  it("puts loose files on top, orders first among folders, user folders by creation", () => {
    const out = buildDocumentSections(
      [doc(1, "contract"), doc(2, "annex", 10), doc(3, "order"), doc(4, "order", 10)],
      folders,
      [ORDER_FILE],
      "Zamówienia",
    );
    expect(out.current.map((r) => r.key)).toEqual(["doc-1"]);
    expect(out.folders.map((f) => f.id)).toEqual([ORDERS_FOLDER_ID, 10, 11]);
    const [orders, previous, empty] = out.folders;
    // Zamówienie leży w „Zamówieniach” nawet ze starym folder_id.
    expect(orders.rows.map((r) => r.key)).toEqual(["doc-4", "doc-3", "order-77"]);
    expect(orders.auto).toBe(true);
    expect(orders.totalBytes).toBe(300 + 400 + 1000);
    expect(previous.rows.map((r) => r.key)).toEqual(["doc-2"]);
    expect(empty.rows).toEqual([]);
  });

  it("hides an empty orders folder and keeps files of a vanished folder visible", () => {
    const out = buildDocumentSections([doc(1, "contract", 999)], [], [], "Zamówienia");
    expect(out.folders).toEqual([]);
    expect(out.current.map((r) => r.key)).toEqual(["doc-1"]);
  });

  it("uses the renamed orders folder name", () => {
    const out = buildDocumentSections([doc(1, "order")], [], [], "Zamówienia BNP");
    expect(out.folders[0].name).toBe("Zamówienia BNP");
  });

  it("shows the line PDF once when the server says the group copy is the same file", () => {
    const out = buildDocumentSections(
      [doc(3, "order"), doc(4, "order")],
      [],
      [{ ...ORDER_FILE, same_file_document_id: 4 }],
      "Zamówienia",
    );
    const [orders] = out.folders;
    expect(orders.rows.map((r) => r.key)).toEqual(["doc-3", "order-77"]);
    expect(orders.totalBytes).toBe(300 + 1000);
  });

  it("keeps both rows without the server's word, even at the same size", () => {
    const sameSize = { ...doc(4, "order"), size_bytes: ORDER_FILE.size_bytes };
    const out = buildDocumentSections(
      [sameSize],
      [],
      [{ ...ORDER_FILE, same_file_document_id: null }],
      "Zamówienia",
    );
    expect(out.folders[0].rows.map((r) => r.key)).toEqual(["doc-4", "order-77"]);
  });
});

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
