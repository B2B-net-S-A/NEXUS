import { beforeEach, describe, expect, it, vi } from "vitest";

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: http }));

import {
  candidateSearchApi,
  proposalsBulkApi,
  savedSearchesApi,
  shortlistApi,
  type CandidateSearchRequest,
} from "@/lib/candidate-search-api";

const BODY = { q: "kotlin" } as CandidateSearchRequest;

beforeEach(() => {
  for (const fn of Object.values(http)) fn.mockReset().mockResolvedValue({ data: { ok: true } });
});

describe("candidateSearchApi.search", () => {
  it("bez sygnału nie wysyła konfiguracji", async () => {
    await expect(candidateSearchApi.search(BODY)).resolves.toEqual({ ok: true });
    expect(http.post).toHaveBeenCalledWith("/api/search/candidates", BODY, undefined);
  });

  it("z sygnałem przekazuje go, żeby nowsze pisanie przerwało starsze zapytanie", async () => {
    const ctrl = new AbortController();
    await candidateSearchApi.search(BODY, ctrl.signal);
    expect(http.post).toHaveBeenCalledWith("/api/search/candidates", BODY, { signal: ctrl.signal });
  });

  it("przerwane zapytanie odrzuca obietnicę", async () => {
    http.post.mockRejectedValueOnce(Object.assign(new Error("canceled"), { name: "CanceledError" }));
    await expect(candidateSearchApi.search(BODY)).rejects.toThrow("canceled");
  });

  it("diagnostyka idzie na osobny adres z tym samym ciałem", async () => {
    http.post.mockResolvedValueOnce({ data: { base_count: 10, stages: [], total: 0 } });
    await expect(candidateSearchApi.diagnostics(BODY)).resolves.toEqual({ base_count: 10, stages: [], total: 0 });
    expect(http.post).toHaveBeenCalledWith("/api/search/candidates/diagnostics", BODY);
  });
});

describe("candidateSearchApi.matchScores", () => {
  it("bez opcji: same id rekrutacji i osób, sygnał pusty", async () => {
    await candidateSearchApi.matchScores(4, [31, 32]);
    expect(http.post).toHaveBeenCalledWith(
      "/api/search/candidates/scores",
      { job_id: 4, candidate_ids: [31, 32] },
      { signal: undefined },
    );
  });

  it("wyświetlenia „Szukaj ręcznie” jadą jako pola `impression_*`", async () => {
    const ctrl = new AbortController();
    await candidateSearchApi.matchScores(4, [31, 32], {
      signal: ctrl.signal,
      impression: { surface: "manual_search", ranks: [1, 2] },
    });
    expect(http.post).toHaveBeenCalledWith(
      "/api/search/candidates/scores",
      { job_id: 4, candidate_ids: [31, 32], impression_surface: "manual_search", impression_ranks: [1, 2] },
      { signal: ctrl.signal },
    );
  });

  it("sam sygnał bez wyświetleń nie dokłada pól `impression_*`", async () => {
    const ctrl = new AbortController();
    await candidateSearchApi.matchScores(4, [31], { signal: ctrl.signal });
    expect(http.post.mock.calls[0][1]).toEqual({ job_id: 4, candidate_ids: [31] });
  });

  it("dowody wymagań: rekrutacja, osoba i etykiety w ciele", async () => {
    const ctrl = new AbortController();
    http.post.mockResolvedValueOnce({ data: { items: {} } });
    await expect(candidateSearchApi.requirementEvidence(4, 31, ["SQL"], ctrl.signal)).resolves.toEqual({
      items: {},
    });
    expect(http.post).toHaveBeenCalledWith(
      "/api/search/candidates/requirement-evidence",
      { job_id: 4, candidate_id: 31, labels: ["SQL"] },
      { signal: ctrl.signal },
    );
  });
});

describe("proposalsBulkApi.assignableStages", () => {
  it("pobiera etapy rekrutacji", async () => {
    http.get.mockResolvedValueOnce({ data: [{ id: 1, name: "Nowi", order: 0 }] });
    await expect(proposalsBulkApi.assignableStages(4)).resolves.toEqual([{ id: 1, name: "Nowi", order: 0 }]);
    expect(http.get).toHaveBeenCalledWith("/api/jobs/4/assignable-stages");
  });
});

describe("savedSearchesApi", () => {
  it("lista przekazuje filtry jako parametry", async () => {
    await savedSearchesApi.list({ entity: "candidate", pinned_to_job_id: 4, only_mine: true });
    expect(http.get).toHaveBeenCalledWith("/api/saved-searches", {
      params: { entity: "candidate", pinned_to_job_id: 4, only_mine: true },
    });
  });

  it("zapis, zatwierdzenie migracji semantyki i usunięcie", async () => {
    const body = { name: "Kotlin Kraków", entity: "candidate", filters: { q: "kotlin" } };
    await savedSearchesApi.create(body);
    expect(http.post).toHaveBeenCalledWith("/api/saved-searches", body);

    await savedSearchesApi.update(7, { reapproval_choice: "keep_legacy" });
    expect(http.patch).toHaveBeenCalledWith("/api/saved-searches/7", { reapproval_choice: "keep_legacy" });

    await expect(savedSearchesApi.remove(7)).resolves.toBeUndefined();
    expect(http.delete).toHaveBeenCalledWith("/api/saved-searches/7");
  });
});

describe("shortlistApi", () => {
  it("lista i dodanie bez notatki — pole `note` nie jedzie", async () => {
    await shortlistApi.list(4);
    expect(http.get).toHaveBeenCalledWith("/api/jobs/4/shortlist");

    await shortlistApi.add(4, [31]);
    expect(http.post).toHaveBeenLastCalledWith("/api/jobs/4/shortlist", { candidate_ids: [31] });
    await shortlistApi.add(4, [31], "");
    expect(http.post).toHaveBeenLastCalledWith("/api/jobs/4/shortlist", { candidate_ids: [31] });
  });

  it("dodanie z notatką", async () => {
    await shortlistApi.add(4, [31, 32], "pilne");
    expect(http.post).toHaveBeenCalledWith("/api/jobs/4/shortlist", { candidate_ids: [31, 32], note: "pilne" });
  });

  it("zmiana, usunięcie i awans na Tablicę", async () => {
    await shortlistApi.update(12, { version: 3, evaluation_status: "potencjalny" });
    expect(http.patch).toHaveBeenCalledWith("/api/shortlist/12", { version: 3, evaluation_status: "potencjalny" });

    await expect(shortlistApi.remove(12)).resolves.toBeUndefined();
    expect(http.delete).toHaveBeenCalledWith("/api/shortlist/12");

    http.post.mockResolvedValueOnce({ data: { entry_id: 12, already_promoted: true } });
    await expect(shortlistApi.promote(12)).resolves.toEqual({ entry_id: 12, already_promoted: true });
    expect(http.post).toHaveBeenCalledWith("/api/shortlist/12/promote");
  });

  it("konflikt wersji (409) przy zmianie przechodzi do wołającego", async () => {
    http.patch.mockRejectedValueOnce(new Error("409"));
    await expect(shortlistApi.update(12, { version: 1 })).rejects.toThrow("409");
  });
});
