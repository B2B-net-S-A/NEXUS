/**
 * Audyt 13.10.2026: ZIP z CV idzie zwykłym `fetch`, którego `AppVersionGuard`
 * nie widział — przeładowanie po wdrożeniu mogło przerwać pobieranie.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const track = vi.hoisted(() => vi.fn(<T>(work: () => Promise<T>) => work()));
vi.mock("@/lib/transfers-in-flight", () => ({ trackTransfer: track }));

import { BulkCvDownloadError, downloadBulkCvs } from "@/lib/bulk-cv-download";

function response(ok: boolean, status: number) {
  return {
    ok,
    status,
    headers: new Headers({ "X-Included-Count": "2", "X-Skipped-Count": "1" }),
    blob: async () => new Blob(["zip"]),
  };
}

describe("downloadBulkCvs — pobieranie liczy się jako transfer w toku", () => {
  beforeEach(() => {
    track.mockClear();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    Object.assign(URL, { createObjectURL: vi.fn(() => "blob:zip"), revokeObjectURL: vi.fn() });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("żądanie i odczyt pliku idą przez `trackTransfer`", async () => {
    const fetchMock = vi.fn(async () => response(true, 200));
    vi.stubGlobal("fetch", fetchMock);

    await expect(downloadBulkCvs([1, 2, 3])).resolves.toEqual({ includedCount: 2, skippedCount: 1 });
    expect(track).toHaveBeenCalledTimes(1);
    expect(track.mock.invocationCallOrder[0]).toBeLessThan(fetchMock.mock.invocationCallOrder[0]);
  });

  it("odmowa serwera też przechodzi przez `trackTransfer` i daje polski komunikat", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(false, 403)));

    await expect(downloadBulkCvs([1])).rejects.toEqual(
      new BulkCvDownloadError("Brak uprawnień do pobrania CV.", 403),
    );
    expect(track).toHaveBeenCalledTimes(1);
  });
});
