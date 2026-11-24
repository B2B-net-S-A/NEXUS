import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
  },
}));

import {
  contractDocsSharePointApi,
  downloadRunReport,
  groupAssignments,
  reasonsText,
  type SharePointRunItem,
} from "@/lib/contract-docs-sharepoint";

const BASE = "/api/contract-docs-sharepoint";

beforeEach(() => {
  get.mockReset().mockImplementation(async (url: string) => ({ data: { url } }));
  post.mockReset().mockImplementation(async (url: string, body?: unknown) => ({
    data: { url, body },
  }));
});

describe("contractDocsSharePointApi — adresy i ciała żądań", () => {
  it("odczyty: status, przebiegi, przebieg, przegląd", async () => {
    expect(await contractDocsSharePointApi.status()).toEqual({ url: `${BASE}/status` });
    expect(await contractDocsSharePointApi.runs()).toEqual({ url: `${BASE}/runs` });
    expect(await contractDocsSharePointApi.run(42)).toEqual({ url: `${BASE}/runs/42` });
    expect(await contractDocsSharePointApi.review()).toEqual({ url: `${BASE}/review` });
  });

  it("podgląd: pusty folder idzie jako null, podany jak jest", async () => {
    expect(await contractDocsSharePointApi.preview("https://sp.test/a", "")).toEqual({
      url: `${BASE}/preview`,
      body: { url: "https://sp.test/a", folder_name: null },
    });
    expect(await contractDocsSharePointApi.preview("https://sp.test/a", null)).toMatchObject({
      body: { folder_name: null },
    });
    expect(await contractDocsSharePointApi.preview("https://sp.test/a", "Umowy")).toMatchObject({
      body: { folder_name: "Umowy" },
    });
  });

  it("zapis z odznaczonymi pozycjami (także pusta lista) i cofnięcie", async () => {
    expect(await contractDocsSharePointApi.apply(5, [])).toEqual({
      url: `${BASE}/runs/5/apply`,
      body: { deselected_item_ids: [] },
    });
    expect(await contractDocsSharePointApi.apply(5, [1, 2])).toMatchObject({
      body: { deselected_item_ids: [1, 2] },
    });
    expect(await contractDocsSharePointApi.rollback(5)).toMatchObject({
      url: `${BASE}/runs/5/rollback`,
    });
  });

  it("decyzja w przeglądzie koduje id pozycji w adresie", async () => {
    expect(await contractDocsSharePointApi.decide("a/b c", "assign", [7])).toEqual({
      url: `${BASE}/review/a%2Fb%20c`,
      body: { action: "assign", contract_ids: [7] },
    });
    expect(await contractDocsSharePointApi.decide("x", "dismiss", [])).toMatchObject({
      body: { action: "dismiss", contract_ids: [] },
    });
  });

  it("synchronizacja teraz", async () => {
    expect(await contractDocsSharePointApi.syncNow()).toMatchObject({ url: `${BASE}/sync-now` });
  });

  it("błąd API przechodzi dalej (bez połykania)", async () => {
    get.mockRejectedValueOnce(new Error("Network Error"));
    await expect(contractDocsSharePointApi.status()).rejects.toThrow("Network Error");
  });
});

describe("downloadRunReport", () => {
  let revoke: ReturnType<typeof vi.fn>;
  let downloads: string[];

  beforeEach(() => {
    vi.useFakeTimers();
    revoke = vi.fn();
    Object.assign(URL, { createObjectURL: vi.fn(() => "blob:raport"), revokeObjectURL: revoke });
    downloads = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      downloads.push(this.download);
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("pobiera XLSX pod nazwą z id przebiegu i zwalnia URL po sekundzie", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: () => Promise.resolve(new Blob(["x"])),
    });
    vi.stubGlobal("fetch", fetchMock);
    await downloadRunReport(9);
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/contract-docs-sharepoint\/runs\/9\/report\.xlsx$/);
    expect(downloads).toEqual(["dokumenty-sharepoint-9.xlsx"]);
    expect(revoke).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(revoke).toHaveBeenCalledWith("blob:raport");
  });

  it("odpowiedź z błędem rzuca „HTTP 403” i niczego nie pobiera", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 403 }));
    await expect(downloadRunReport(9)).rejects.toThrow("HTTP 403");
    expect(downloads).toEqual([]);
  });
});

describe("reasonsText i groupAssignments — brzegi", () => {
  it("pusta lista powodów daje pusty napis", () => {
    expect(reasonsText([])).toBe("");
  });

  it("brak nazwiska w przypisaniu daje pusty napis, nie „null”", () => {
    const item: SharePointRunItem = {
      id: 1,
      kind: "assignment",
      folder_name: null,
      file_name: "umowa.pdf",
      size_bytes: null,
      doc_type: "contract",
      contract_id: 3,
      person_name: null,
      match_kind: "sure",
      reasons: [],
      note: null,
      selected: true,
      status: "pending",
      error: null,
    };
    expect(groupAssignments([item])[0].personName).toBe("");
  });
});
