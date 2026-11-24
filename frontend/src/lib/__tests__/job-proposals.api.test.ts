import { beforeEach, describe, expect, it, vi } from "vitest";

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: http }));

import { PROPOSAL_INBOX_PAGE, jobProposalsApi, jobProposalsKeys } from "@/lib/job-proposals-api";

beforeEach(() => {
  http.get.mockReset().mockResolvedValue({ data: { ok: true } });
  http.post.mockReset().mockResolvedValue({ data: { ok: true } });
});

describe("jobProposalsApi.inbox — parametry skrzynki", () => {
  it("domyślnie: propozycje bez decyzji, pierwsza strona po 20, bez filtra listy", async () => {
    await expect(jobProposalsApi.inbox(4)).resolves.toEqual({ ok: true });
    expect(http.get).toHaveBeenCalledWith("/api/jobs/4/proposal-inbox", {
      params: { status: "proposed", limit: PROPOSAL_INBOX_PAGE, offset: 0 },
      signal: undefined,
    });
  });

  it("status, strona i filtr listy jadą do serwera; sygnał przerwania też", async () => {
    const ctrl = new AbortController();
    await jobProposalsApi.inbox(4, { status: "dismissed", limit: 50, offset: 100, list: "portal" }, ctrl.signal);
    expect(http.get).toHaveBeenCalledWith("/api/jobs/4/proposal-inbox", {
      params: { status: "dismissed", limit: 50, offset: 100, list: "portal" },
      signal: ctrl.signal,
    });
  });

  it("filtr „all” nie jest wysyłany — serwer zna tylko plakietki", async () => {
    await jobProposalsApi.inbox(4, { list: "all" });
    expect(http.get.mock.calls[0][1].params).not.toHaveProperty("list");
  });

  it("offset 0 i limit 0 nie są zastępowane domyślnymi (??, nie ||)", async () => {
    await jobProposalsApi.inbox(4, { limit: 0, offset: 0 });
    expect(http.get.mock.calls[0][1].params).toMatchObject({ limit: 0, offset: 0 });
  });

  it("błąd serwera przechodzi do wołającego", async () => {
    http.get.mockRejectedValueOnce(new Error("500"));
    await expect(jobProposalsApi.inbox(4)).rejects.toThrow("500");
  });
});

describe("jobProposalsApi — „Pomiń”, „Cofnij”, telemetria", () => {
  it("„Pomiń” wysyła źródło i powód; pusty opis nie jedzie wcale", async () => {
    await jobProposalsApi.dismiss(4, 31, "full_base", { reason: "too_expensive", note: "   " });
    expect(http.post).toHaveBeenCalledWith("/api/jobs/4/proposal-inbox/31/dismiss", {
      source: "full_base",
      reason: "too_expensive",
    });
  });

  it("„Pomiń” z opisem przycina spacje", async () => {
    await jobProposalsApi.dismiss(4, 31, "new_cv", { reason: "other", note: "  nie ten stos  " });
    expect(http.post.mock.calls[0][1]).toEqual({ source: "new_cv", reason: "other", note: "nie ten stos" });
  });

  it("„Pomiń zaznaczone” wysyła kopię listy id i jeden powód", async () => {
    const ids = [31, 32] as const;
    await jobProposalsApi.dismissBulk(4, ids, { reason: "outdated_cv", note: null });
    expect(http.post).toHaveBeenCalledWith("/api/jobs/4/proposal-inbox/dismiss-bulk", {
      candidate_ids: [31, 32],
      reason: "outdated_cv",
    });
  });

  it("otwarcie skrzynki i „Cofnij” idą POST-em bez ciała", async () => {
    http.post.mockResolvedValueOnce({ data: { job_id: 4, recorded: true } });
    await expect(jobProposalsApi.opened(4)).resolves.toEqual({ job_id: 4, recorded: true });
    expect(http.post).toHaveBeenLastCalledWith("/api/jobs/4/proposal-inbox/opened");

    await jobProposalsApi.restore(4, 31);
    expect(http.post).toHaveBeenLastCalledWith("/api/jobs/4/proposal-inbox/31/restore");
  });

  it("odmowa telemetrii (podgląd jako) zostaje odrzuconą obietnicą — wołający ją ignoruje", async () => {
    http.post.mockRejectedValueOnce(new Error("403"));
    await expect(jobProposalsApi.opened(4)).rejects.toThrow("403");
  });
});

describe("jobProposalsApi — fakty, liczniki, ukryci, ostatni przegląd", () => {
  it("fakty: lista id bez indeksów, z sygnałem", async () => {
    const ctrl = new AbortController();
    await jobProposalsApi.facts(4, [31, 32], ctrl.signal);
    expect(http.get).toHaveBeenCalledWith("/api/jobs/4/proposal-facts", {
      params: { candidate_ids: [31, 32] },
      paramsSerializer: { indexes: null },
      signal: ctrl.signal,
    });
  });

  it("liczniki, ukryci przez krytyczne i ostatni przegląd mają własne adresy", async () => {
    await jobProposalsApi.counts(4);
    expect(http.get).toHaveBeenLastCalledWith("/api/jobs/4/proposal-counts", { signal: undefined });
    await jobProposalsApi.hiddenByCritical(4);
    expect(http.get).toHaveBeenLastCalledWith("/api/jobs/4/proposal-inbox/hidden-by-critical", {
      signal: undefined,
    });
    await jobProposalsApi.latestRun(4);
    expect(http.get).toHaveBeenLastCalledWith("/api/candidate-search/jobs/4/latest-run", { signal: undefined });
  });
});

describe("jobProposalsKeys", () => {
  it("skrzynka bez filtra i z filtrem „all” dzieli klucz; plakietka dokłada piąty element", () => {
    expect(jobProposalsKeys.inbox(4, 20)).toEqual(["job-proposals", 4, "inbox", 20]);
    expect(jobProposalsKeys.inbox(4, 20, "all")).toEqual(["job-proposals", 4, "inbox", 20]);
    expect(jobProposalsKeys.inbox(4, 20, "known")).toEqual(["job-proposals", 4, "inbox", 20, "known"]);
  });

  it("fakty: ta sama lista w innej kolejności trafia w ten sam klucz, wejście nie jest sortowane w miejscu", () => {
    const ids = [32, 4, 117];
    expect(jobProposalsKeys.facts(4, ids)).toEqual(jobProposalsKeys.facts(4, [117, 32, 4]));
    expect(jobProposalsKeys.facts(4, ids)[3]).toBe("4,32,117");
    expect(ids).toEqual([32, 4, 117]);
  });
});
