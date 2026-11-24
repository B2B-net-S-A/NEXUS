/**
 * Audyt 13.10.2026: ZIP z CV idzie zwykłym `fetch`, którego `AppVersionGuard`
 * nie widział — przeładowanie po wdrożeniu mogło przerwać pobieranie.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const track = vi.hoisted(() => vi.fn(<T>(work: () => Promise<T>) => work()));
vi.mock("@/lib/transfers-in-flight", () => ({ trackTransfer: track }));

import { BulkCvDownloadError, downloadBulkCvs } from "@/lib/bulk-cv-download";
import { CSRF_HEADER } from "@/lib/session";

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

describe("downloadBulkCvs — odmowy, nagłówki i plik ZIP", () => {
  let clicked: HTMLAnchorElement[];

  beforeEach(() => {
    track.mockClear();
    clicked = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push(this);
    });
    Object.assign(URL, { createObjectURL: vi.fn(() => "blob:zip"), revokeObjectURL: vi.fn() });
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("pusta lista: błąd 400 bez żadnego zapytania", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(downloadBulkCvs([])).rejects.toEqual(
      new BulkCvDownloadError("Nie wybrano kandydatów.", 400),
    );
    expect(fetchMock).not.toHaveBeenCalled();
    expect(track).not.toHaveBeenCalled();
  });

  it.each([
    [401, "Brak uprawnień do pobrania CV."],
    [400, "Za dużo zaznaczonych kandydatów (max 200) lub lista jest pusta."],
    [422, "Za dużo zaznaczonych kandydatów (max 200) lub lista jest pusta."],
    [429, "Zbyt wiele pobrań w krótkim czasie — spróbuj ponownie za chwilę."],
    [500, "Nie udało się pobrać CV. Spróbuj ponownie."],
    [404, "Nie udało się pobrać CV. Spróbuj ponownie."],
  ])("status %i daje polski komunikat i zachowuje kod", async (status, message) => {
    vi.stubGlobal("fetch", vi.fn(async () => response(false, status)));

    const error = await downloadBulkCvs([5]).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(BulkCvDownloadError);
    expect(error).toMatchObject({ name: "BulkCvDownloadError", message, status });
    expect(clicked).toHaveLength(0);
  });

  it("wysyła POST z ciasteczkami, CSRF i listą id pod adres z NEXT_PUBLIC_API_URL", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.test");
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => response(true, 200));
    vi.stubGlobal("fetch", fetchMock);

    await downloadBulkCvs([4, 9]);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example.test/api/candidates/bulk-cv-download");
    expect(init).toMatchObject({ method: "POST", credentials: "include" });
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      [CSRF_HEADER]: "1",
    });
    expect(JSON.parse(init.body as string)).toEqual({ candidate_ids: [4, 9] });
  });

  it("bez liczników w nagłówkach zwraca zera, a ZIP ma datę w nazwie", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-24T10:00:00Z"));
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers(),
        blob: async () => new Blob(["zip"]),
      })),
    );

    await expect(downloadBulkCvs([1])).resolves.toEqual({ includedCount: 0, skippedCount: 0 });
    expect(clicked).toHaveLength(1);
    expect(clicked[0].download).toBe("nexus-cvs-2026-11-24.zip");
    expect(document.body.contains(clicked[0])).toBe(false);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:zip");
  });

  it.todo(
    "nazwa ZIP-a bierze datę z UTC (`toISOString`, bulk-cv-download.ts:63): " +
      "o 23:30 UTC 30.09 w Warszawie jest już 01.10, a plik nazywa się nexus-cvs-2026-09-30.zip",
  );
});
