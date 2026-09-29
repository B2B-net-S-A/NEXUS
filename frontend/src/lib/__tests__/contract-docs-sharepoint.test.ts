import { describe, expect, it } from "vitest";

import {
  contractsWithoutDocuments,
  deselectedItemIds,
  filesLabel,
  groupAssignments,
  reasonsText,
  sharePointBadge,
  uncertainGroups,
  type SharePointRunItem,
} from "@/lib/contract-docs-sharepoint";

function item(partial: Partial<SharePointRunItem>): SharePointRunItem {
  return {
    id: 0,
    kind: "assignment",
    folder_name: null,
    file_name: null,
    size_bytes: null,
    doc_type: null,
    contract_id: null,
    person_name: null,
    match_kind: null,
    reasons: [],
    note: null,
    selected: true,
    status: "pending",
    error: null,
    ...partial,
  };
}

const ITEMS: SharePointRunItem[] = [
  item({
    id: 1,
    contract_id: 10,
    person_name: "Jan Kowalski",
    match_kind: "sure",
    file_name: "a.pdf",
  }),
  item({
    id: 2,
    contract_id: 10,
    person_name: "Jan Kowalski",
    match_kind: "sure",
    file_name: "b.pdf",
  }),
  item({
    id: 3,
    contract_id: 11,
    person_name: "Łukasz Nowak",
    match_kind: "uncertain",
    reasons: ["diacritics"],
    file_name: "c.pdf",
  }),
  item({
    id: 4,
    kind: "contract",
    contract_id: 12,
    match_kind: "none",
    note: "brak",
  }),
  item({ id: 5, kind: "contract", contract_id: 13, match_kind: "ambiguous" }),
  item({ id: 6, kind: "contract", contract_id: 14, match_kind: "excluded" }),
  item({
    id: 7,
    kind: "contract",
    contract_id: 15,
    match_kind: "sure",
    note: "pusty folder",
  }),
];

describe("contract docs from SharePoint", () => {
  it("groups files per contract", () => {
    const groups = groupAssignments(ITEMS);
    expect(groups.map((g) => [g.contractId, g.files.length])).toEqual([
      [10, 2],
      [11, 1],
    ]);
  });

  it("lists contracts without a folder or documents, not the ambiguous or excluded ones", () => {
    expect(contractsWithoutDocuments(ITEMS).map((i) => i.contract_id)).toEqual([
      12, 15,
    ]);
  });

  it("separates uncertain assignments from contracts with several folders", () => {
    const { uncertain, ambiguous } = uncertainGroups(ITEMS);
    expect(uncertain.map((g) => g.contractId)).toEqual([11]);
    expect(ambiguous.map((i) => i.contract_id)).toEqual([13]);
  });

  it("turns unchecked contracts into skipped file rows", () => {
    expect(deselectedItemIds(groupAssignments(ITEMS), new Set([10]))).toEqual([
      1, 2,
    ]);
    expect(deselectedItemIds(groupAssignments(ITEMS), new Set())).toEqual([]);
  });

  it("explains the match in Polish", () => {
    expect(reasonsText(["diacritics", "typo"])).toBe(
      "różnica w polskich znakach; możliwa literówka w nazwisku",
    );
  });

  it("shows where the document lives", () => {
    expect(sharePointBadge({ source: "sharepoint_import" })?.label).toBe(
      "z SharePointa",
    );
    expect(
      sharePointBadge({ source: "upload", sharepoint_item_id: "x" })?.label,
    ).toBe("w SharePoincie");
    expect(
      sharePointBadge({ source: "upload", sharepoint_push_status: "skipped" })
        ?.tone,
    ).toBe("warning");
    expect(sharePointBadge({ source: "upload" })).toBeNull();
  });

  it("uses Polish plural forms for the file count", () => {
    expect([1, 2, 4, 5, 12, 22, 25].map(filesLabel)).toEqual([
      "1 plik",
      "2 pliki",
      "4 pliki",
      "5 plików",
      "12 plików",
      "22 pliki",
      "25 plików",
    ]);
  });
});
