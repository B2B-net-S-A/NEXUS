/**
 * Wariant A zakładki „Dokumenty” (19.11.2026): data z nazwy pliku, grupy po
 * rodzaju, foldery jako archiwum, karty „Obowiązuje teraz” i opis importu
 * z SharePointa raz nad tabelą.
 */
import { describe, expect, it } from "vitest";

import type { OrderDocumentItem } from "@/lib/api/dlPortal";
import type { ContractDocument, DocumentFolder } from "@/lib/contract-document-folders";

import {
  batchSentence,
  buildDocumentsView,
  byDocDateDesc,
  dateFromName,
  daysFromToday,
  docDateLabel,
  fmtSize,
  groupLabel,
  kindFromFileName,
  kindNote,
  matchesQuery,
  nameHasContractNumber,
  sharePointBatch,
} from "../document-groups";

function doc(
  id: number,
  filename: string,
  doc_type: string,
  extra: Partial<ContractDocument> = {},
): ContractDocument {
  return {
    id,
    contract_id: 3,
    filename,
    doc_type,
    content_type: "application/pdf",
    size_bytes: 1000 + id,
    expiry_date: null,
    uploaded_by: 1,
    uploaded_by_email: "anna.przykladowa@example.com",
    created_at: "2026-10-01T10:00:00Z",
    folder_id: null,
    ...extra,
  };
}

function orderFile(id: number, extra: Partial<OrderDocumentItem> = {}): OrderDocumentItem {
  return {
    order_id: id,
    client_id: 9,
    contract_id: 3,
    title: `ZAM-2026-${id}`,
    filename: `zam-${id}.pdf`,
    content_type: "application/pdf",
    size_bytes: 2048,
    created_at: "2026-09-30T10:00:00Z",
    order_status: "active",
    uploaded_by_email: null,
    uploaded_at: null,
    ...extra,
  };
}

const ARCHIVE: DocumentFolder = { id: 20, name: "Poprzednia umowa", created_at: "2026-10-20T10:00:00Z" };

const names = (rows: { name: string }[]) => rows.map((r) => r.name);

describe("dateFromName", () => {
  it("reads a deadline written as „do 31.10.2019”", () => {
    expect(dateFromName("Zamówienie nr 4 do 31.10.2019.pdf")).toEqual({ iso: "2019-10-31", until: true });
    expect(dateFromName("Zamówienie 17_Firma_do 30.06.2025_sign.pdf")).toEqual({
      iso: "2025-06-30",
      until: true,
    });
  });

  it("reads underscored and ISO dates, and the date after a contract number", () => {
    expect(dateFromName("aneks_2024_05_01.pdf")).toEqual({ iso: "2024-05-01", until: false });
    expect(dateFromName("aneks 2024-05-01.pdf")).toEqual({ iso: "2024-05-01", until: false });
    expect(dateFromName("aneks nr 340_2019_01.05.2024_podpis.pdf")).toEqual({
      iso: "2024-05-01",
      until: false,
    });
    expect(dateFromName("1277-2025 B2B 31.10.2025.pdf")).toEqual({ iso: "2025-10-31", until: false });
  });

  it("returns null without a date or with an impossible one", () => {
    expect(dateFromName("umowa o współpracę.pdf")).toBeNull();
    expect(dateFromName("Porozumienie o rozwiązaniu umowy nr 361-2019.pdf")).toBeNull();
    expect(dateFromName("aneks 31.02.2020.pdf")).toBeNull();
    expect(dateFromName("skan 01.01.1890.pdf")).toBeNull();
  });

  it("labels the date for the table", () => {
    expect(docDateLabel({ docDate: "2019-10-31", docDateUntil: true })).toBe("do 31.10.2019");
    expect(docDateLabel({ docDate: "2024-05-01", docDateUntil: false })).toBe("01.05.2024");
    expect(docDateLabel({ docDate: null, docDateUntil: false })).toBeNull();
  });
});

describe("kindFromFileName", () => {
  it("checks annex, notice and agreement before the word „umowa”", () => {
    expect(kindFromFileName("Aneks do umowy 361-2019.pdf")?.group).toBe("aneksy");
    expect(kindFromFileName("Porozumienie o rozwiązaniu umowy.pdf")).toEqual({
      group: "umowy",
      label: "Porozumienie",
    });
    expect(kindFromFileName("Zamówienie.pdf")?.group).toBe("zamowienia");
    expect(kindFromFileName("PO0087020757.PDF")?.group).toBe("zamowienia");
    expect(kindFromFileName("umowa o współpracę.pdf")?.label).toBe("Umowa");
    expect(kindFromFileName("Protokół sprzętu.pdf")).toBeNull();
  });
});

describe("buildDocumentsView", () => {
  it("groups loose files by type — „Inne” from SharePoint by file name — and keeps empty groups out", () => {
    const view = buildDocumentsView(
      [
        doc(1, "Umowa B2B 518-2026 01.10.2026.pdf", "contract"),
        doc(2, "Zamówienie nr 3 do 30.09.2019.pdf", "other", { source: "sharepoint_import" }),
        doc(3, "Aneks stawka 31.10.2022.pdf", "annex"),
        doc(4, "Protokół sprzętu.pdf", "other"),
        doc(5, "Polisa OC.pdf", "oc_policy"),
      ],
      [],
      [],
    );
    expect(view.sections.map((s) => s.key)).toEqual([
      "group:umowy",
      "group:aneksy",
      "group:zamowienia",
      "group:inne",
    ]);
    const orders = view.sections.find((s) => s.key === "group:zamowienia")!;
    expect(orders.items[0].kindFromName).toBe(true);
    // Typ w bazie „Inne” — można go przenieść do folderu.
    expect(orders.items[0].movable).toBe(true);
    expect(orders.namedCount).toBe(1);
    const other = view.sections.find((s) => s.key === "group:inne")!;
    expect(other.items.map(kindNote)).toEqual(["Polisa OC", null]);

    const onlyContract = buildDocumentsView([doc(1, "umowa.pdf", "contract")], [], []);
    expect(onlyContract.sections.map((s) => s.key)).toEqual(["group:umowy"]);
  });

  it("keeps folder files out of the type groups and the current cards; orders never sit in a folder", () => {
    const view = buildDocumentsView(
      [
        doc(1, "Umowa 1531-2026 30.09.2026.pdf", "contract"),
        doc(2, "Umowa 361-2019 06.06.2019.pdf", "contract", { folder_id: 20 }),
        doc(3, "Aneks stawka 16.12.2025.pdf", "annex", { folder_id: 20 }),
        doc(4, "Zamówienie nr 9 do 31.12.2025.pdf", "order", { folder_id: 20 }),
        doc(5, "Polisa OC.pdf", "oc_policy", { folder_id: 99 }),
      ],
      [ARCHIVE, { id: 21, name: "Pusty", created_at: "2026-10-21T10:00:00Z" }],
      [],
    );
    expect(view.sections.map((s) => s.key)).toEqual([
      "group:umowy",
      "group:zamowienia",
      "group:inne",
      "folder:20",
      "folder:21",
    ]);
    expect(names(view.sections.find((s) => s.key === "folder:20")!.items)).toEqual([
      "Aneks stawka 16.12.2025.pdf",
      "Umowa 361-2019 06.06.2019.pdf",
    ]);
    // Folder, którego już nie ma, oddaje plik grupom po rodzaju.
    expect(names(view.sections.find((s) => s.key === "group:inne")!.items)).toEqual(["Polisa OC.pdf"]);
    expect(view.sections.find((s) => s.key === "folder:21")!.items).toEqual([]);
    expect(view.current.contract?.name).toBe("Umowa 1531-2026 30.09.2026.pdf");
    expect(view.current.annex).toBeNull();
    expect(view.current.order?.name).toBe("Zamówienie nr 9 do 31.12.2025.pdf");
    expect(view.current.order?.movable).toBe(false);
  });

  it("puts undated files from a SharePoint sync after dated ones — the sync day is not the document date", () => {
    const synced = (id: number, filename: string, doc_type: string) =>
      doc(id, filename, doc_type, { source: "sharepoint", created_at: "2026-09-30T12:31:00Z", folder_id: 20 });
    const view = buildDocumentsView(
      [
        synced(1, "wypowiedzenie b2b.pdf", "termination_notice"),
        synced(2, "Aneks stawka 16.12.2025.pdf", "annex"),
        synced(3, "Aneks stawka 10.05.2024.pdf", "annex"),
      ],
      [ARCHIVE],
      [],
    );
    expect(names(view.sections[0].items)).toEqual([
      "Aneks stawka 16.12.2025.pdf",
      "Aneks stawka 10.05.2024.pdf",
      "wypowiedzenie b2b.pdf",
    ]);
  });

  it("sorts by the date in the name, falls back to the upload day and puts undated imports last", () => {
    const view = buildDocumentsView(
      [
        doc(1, "Zamówienie.pdf", "other", { source: "sharepoint_import", created_at: "2026-09-29T16:00:00Z" }),
        doc(2, "Zamówienie nr 16 do 30.06.2024.pdf", "other", { source: "sharepoint_import" }),
        doc(3, "Zamówienie nr 17 do 30.06.2025.pdf", "other", { source: "sharepoint_import" }),
        doc(4, "87020188.pdf", "order", { created_at: "2026-10-06T17:05:00Z" }),
        doc(5, "PO0087020757.PDF", "order", { created_at: "2026-10-06T10:33:00Z" }),
      ],
      [],
      [orderFile(77, { uploaded_at: "2026-11-02T10:45:00Z" })],
    );
    expect(names(view.sections[0].items)).toEqual([
      "zam-77.pdf",
      "87020188.pdf",
      "PO0087020757.PDF",
      "Zamówienie nr 17 do 30.06.2025.pdf",
      "Zamówienie nr 16 do 30.06.2024.pdf",
      "Zamówienie.pdf",
    ]);
    expect(view.current.order?.name).toBe("zam-77.pdf");
    expect(view.current.order?.active).toBe(true);
    expect(view.current.order?.orderStatus).toBe("aktywne");
  });

  it("prefers the contract file with the current contract number for the „Umowa” card", () => {
    const docs = [
      doc(1, "Umowa B2B nr 518-2026.pdf", "contract", { created_at: "2026-10-01T10:00:00Z" }),
      // Starsza umowa dodana później, jeszcze nie w folderze „Poprzednia umowa”.
      doc(2, "Umowa nr 361-2019.pdf", "contract", { created_at: "2026-10-02T10:00:00Z" }),
    ];
    expect(buildDocumentsView(docs, [], [], "518-2026").current.contract?.name).toBe("Umowa B2B nr 518-2026.pdf");
    expect(buildDocumentsView(docs, [], [], null).current.contract?.name).toBe("Umowa nr 361-2019.pdf");
    expect(buildDocumentsView(docs, [], [], "999-2026").current.contract?.name).toBe("Umowa nr 361-2019.pdf");
  });

  it("matches a contract number written with other separators, not inside a longer number", () => {
    expect(nameHasContractNumber("aneks B2B nr 340_2019_01.05.2024.pdf", "340-2019")).toBe(true);
    expect(nameHasContractNumber("1277-2025 B2B 31.10.2025.pdf", "1277/2025")).toBe(true);
    expect(nameHasContractNumber("Umowa 1340-2019.pdf", "340-2019")).toBe(false);
    expect(nameHasContractNumber("Umowa 340-2019.pdf", null)).toBe(false);
  });

  it("picks the newest contract file, not a termination notice, for the „Umowa” card", () => {
    const view = buildDocumentsView(
      [
        doc(1, "Umowa B2B 01.02.2026.pdf", "contract"),
        doc(2, "Wypowiedzenie 01.10.2026.pdf", "termination_notice"),
        doc(3, "Umowa B2B 01.02.2019.pdf", "contract"),
      ],
      [],
      [],
    );
    expect(view.current.contract?.name).toBe("Umowa B2B 01.02.2026.pdf");
    expect(kindNote(view.sections[0].items[0])).toBe("Wypowiedzenie");
  });

  it("flags a probable duplicate (same size, same number) and the expiry column", () => {
    const view = buildDocumentsView(
      [
        doc(1, "0087020757.pdf", "order", { size_bytes: 46909 }),
        doc(2, "PO0087020757.PDF", "order", { size_bytes: 46909, expiry_date: "2026-12-31" }),
        doc(3, "87020188.pdf", "order", { size_bytes: 44381 }),
      ],
      [],
      [],
    );
    expect(view.duplicates.get("doc-1")?.name).toBe("PO0087020757.PDF");
    expect(view.duplicates.get("doc-2")?.name).toBe("0087020757.pdf");
    expect(view.duplicates.has("doc-3")).toBe(false);
    expect(view.hasExpiry).toBe(true);
    expect(buildDocumentsView([doc(1, "a.pdf", "contract")], [], []).hasExpiry).toBe(false);
  });

  it("shows the order-line PDF once when the server says the group copy is the same file", () => {
    // 19.11.2026: PDF linii i kopia PDF-u grupy jako dwa wiersze (14 par na produkcji).
    const view = buildDocumentsView(
      [doc(1, "Umowa.pdf", "contract"), doc(2, "445.pdf", "order", { size_bytes: 2048 })],
      [],
      [orderFile(7, { same_file_document_id: 2 })],
    );
    expect(view.items.map((i) => i.key)).toEqual(["doc-1", "order-7"]);
    expect(view.current.order?.key).toBe("order-7");
    expect(view.duplicates.size).toBe(0);
    const orders = view.sections.find((s) => s.group === "zamowienia");
    expect(orders?.items.map((i) => i.key)).toEqual(["order-7"]);
    expect(orders?.totalBytes).toBe(2048);
  });

  it("keeps both rows without the server's word, and never hides a non-order file", () => {
    const sameSize = buildDocumentsView(
      [doc(2, "445.pdf", "order", { size_bytes: 2048 })],
      [],
      [orderFile(7, { same_file_document_id: null })],
    );
    expect(sameSize.items.map((i) => i.key).sort()).toEqual(["doc-2", "order-7"]);
    const contract = buildDocumentsView(
      [doc(2, "Umowa.pdf", "contract")],
      [],
      [orderFile(7, { same_file_document_id: 2 })],
    );
    expect(contract.items.map((i) => i.key).sort()).toEqual(["doc-2", "order-7"]);
  });
});

describe("SharePoint import described once", () => {
  const imported = (id: number, name: string) =>
    doc(id, name, "other", { source: "sharepoint_import", created_at: "2026-09-29T16:50:00Z" });

  it("folds three or more files from one import run into one sentence", () => {
    const all = buildDocumentsView(
      [imported(1, "a.pdf"), imported(2, "b.pdf"), imported(3, "c.pdf")],
      [],
      [],
    );
    expect(all.batch).toMatchObject({ count: 3, total: 3, origin: "import", person: "Anna Przykladowa" });
    expect(batchSentence(all.batch!)).toBe(
      "Wszystkie pliki (3) z importu z SharePointa 29.09.2026 · Anna Przykladowa",
    );

    const some = buildDocumentsView(
      [imported(1, "a.pdf"), imported(2, "b.pdf"), imported(3, "c.pdf"), doc(4, "d.pdf", "contract")],
      [],
      [],
    );
    expect(batchSentence(some.batch!)).toBe(
      "3 z 4 plików z importu z SharePointa 29.09.2026 · Anna Przykladowa",
    );
  });

  it("describes a sync without a person and skips small runs", () => {
    const synced = (id: number) =>
      doc(id, `s${id}.pdf`, "annex", {
        source: "sharepoint",
        uploaded_by_email: null,
        created_at: "2026-09-30T12:31:00Z",
      });
    const view = buildDocumentsView([synced(1), synced(2), synced(3)], [], []);
    expect(batchSentence(view.batch!)).toBe("Wszystkie pliki (3) z SharePointa (synchronizacja 30.09.2026)");

    expect(sharePointBatch(buildDocumentsView([imported(1, "a.pdf"), imported(2, "b.pdf")], [], []).items)).toBeNull();
  });
});

describe("helpers", () => {
  it("formats sizes the Polish way", () => {
    expect(fmtSize(5034193)).toBe("4,8 MB");
    expect(fmtSize(249030)).toBe("243 KB");
    expect(fmtSize(128)).toBe("1 KB");
    expect(fmtSize(null)).toBe("—");
  });

  it("names the orders group after a renamed orders folder", () => {
    expect(groupLabel("zamowienia", "Zamówienia")).toBe("Zamówienia klienta");
    expect(groupLabel("zamowienia", "Zamówienia banku")).toBe("Zamówienia banku");
    expect(groupLabel("umowy", "Zamówienia banku")).toBe("Umowy");
  });

  it("searches names without case and Polish letters, plus the order number", () => {
    const view = buildDocumentsView(
      [doc(1, "Aneks zmiana stawki 08.06.2021.pdf", "annex")],
      [],
      [orderFile(5, { title: "ZAM-2026-0930" })],
    );
    const [order, annex] = [view.items.find((i) => i.key === "order-5")!, view.items.find((i) => i.key === "doc-1")!];
    expect(matchesQuery(annex, "ZMIANA stawki")).toBe(true);
    expect(matchesQuery(annex, "zmiána")).toBe(true);
    expect(matchesQuery(order, "0930")).toBe(true);
    expect(matchesQuery(annex, "0930")).toBe(false);
    expect(matchesQuery(annex, "  ")).toBe(true);
  });

  it("counts days in the company calendar", () => {
    expect(daysFromToday("2026-12-31", "2026-11-20")).toBe(41);
    expect(daysFromToday("2026-11-19", "2026-11-20")).toBe(-1);
    expect(daysFromToday(null, "2026-11-20")).toBeNull();
  });

  it("keeps ties stable: same day → later upload first, then name", () => {
    const view = buildDocumentsView(
      [
        doc(1, "b.pdf", "contract", { created_at: "2026-10-01T08:00:00Z" }),
        doc(2, "a.pdf", "contract", { created_at: "2026-10-01T09:00:00Z" }),
      ],
      [],
      [],
    );
    expect(names([...view.items].sort(byDocDateDesc))).toEqual(["a.pdf", "b.pdf"]);
  });
});
