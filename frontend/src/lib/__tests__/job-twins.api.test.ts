import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const http = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: http }));

import {
  TWIN_SKIP_REASONS,
  jobTwinsApi,
  jobTwinsKeys,
  ruleChipLabel,
  twinRef,
  twinSkipLabel,
  useDismissTwinSuggestion,
  useJobTwins,
  useLinkTwin,
  useOpenSimilarJobs,
  useSaveTwinRules,
  useTwinRules,
  useTwinSuggestions,
  useUnlinkTwin,
  workModeLabel,
  type TwinRules,
} from "@/lib/job-twins-api";
import { similarJobsKey } from "@/lib/similar-jobs-api";

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children);
  return { qc, wrapper };
}

const RULES: TwinRules = {
  min_similarity: 70,
  critical: { mode: "required", include_title: true },
  must: { mode: "warning", min_share: 0.5 },
  location: { mode: "off" },
  work_mode: { mode: "warning" },
  budget: { mode: "warning", max_diff: 20 },
  client: { mode: "off" },
  category: { mode: "required" },
  different_dl: { mode: "off" },
  max_twins: 3,
  open_similar_limit: 10,
  pair_hint: "default",
};

beforeEach(() => {
  for (const fn of Object.values(http)) fn.mockReset();
});

describe("jobTwinsKeys", () => {
  it("podgląd pary i kandydaci per klient mają rozłączne klucze", () => {
    expect(jobTwinsKeys.preview(4, 9)).toEqual(["job-twin-preview", 4, 9]);
    expect(jobTwinsKeys.preview(9, 4)).not.toEqual(jobTwinsKeys.preview(4, 9));
    expect(jobTwinsKeys.candidates(null)).toEqual(["job-twin-candidates", null]);
    expect(jobTwinsKeys.candidates(12)).toEqual(["job-twin-candidates", 12]);
  });
});

describe("jobTwinsApi — adresy i ciała żądań", () => {
  it("bliźniaki i podgląd pary biorą id rekrutacji z adresu, drugą z parametru", async () => {
    http.get.mockResolvedValueOnce({ data: { job_id: 4, twins: [] } });
    await expect(jobTwinsApi.twins(4)).resolves.toEqual({ job_id: 4, twins: [] });
    expect(http.get).toHaveBeenLastCalledWith("/api/jobs/4/twins");

    http.get.mockResolvedValueOnce({ data: { already_twin: false } });
    await jobTwinsApi.preview(4, 9);
    expect(http.get).toHaveBeenLastCalledWith("/api/jobs/4/twins/preview", { params: { other_job_id: 9 } });
  });

  it("połączenie wysyła same pary pytań — bez podpowiedzi `score` serwera", async () => {
    http.post.mockResolvedValueOnce({ data: { linked_now: true } });
    const out = await jobTwinsApi.link(4, 9, [
      { own: "q1", other: "q2", score: 0.8 },
      { own: "q3", other: "q3" },
    ]);
    expect(out).toEqual({ linked_now: true });
    expect(http.post).toHaveBeenCalledWith("/api/jobs/4/twins", {
      other_job_id: 9,
      question_pairs: [
        { own: "q1", other: "q2" },
        { own: "q3", other: "q3" },
      ],
    });
  });

  it("połączenie bez par wysyła pustą listę, nie brak pola", async () => {
    http.post.mockResolvedValueOnce({ data: {} });
    await jobTwinsApi.link(4, 9, []);
    expect(http.post.mock.calls[0][1]).toEqual({ other_job_id: 9, question_pairs: [] });
  });

  it("rozłączenie, podobne otwarte i lista HoR mają własne adresy", async () => {
    http.delete.mockResolvedValueOnce({ data: { unlinked_now: true } });
    await expect(jobTwinsApi.unlink(4, 9)).resolves.toEqual({ unlinked_now: true });
    expect(http.delete).toHaveBeenCalledWith("/api/jobs/4/twins/9");

    http.get.mockResolvedValueOnce({ data: { job_id: 4, items: [] } });
    await jobTwinsApi.openSimilar(4);
    expect(http.get).toHaveBeenLastCalledWith("/api/jobs/4/open-similar");

    http.get.mockResolvedValueOnce({ data: { min_similarity: 70, items: [] } });
    await expect(jobTwinsApi.suggestions()).resolves.toEqual({ min_similarity: 70, items: [] });
    expect(http.get).toHaveBeenLastCalledWith("/api/job-twins/suggestions");
  });

  it("kandydaci na bliźniaka: klient zawęża listę, brak klienta (null lub 0) — bez parametru", async () => {
    http.get.mockResolvedValue({ data: { items: [] } });
    await jobTwinsApi.candidates(12);
    expect(http.get).toHaveBeenLastCalledWith("/api/job-twins/candidates", { params: { client_id: 12 } });
    await jobTwinsApi.candidates(null);
    expect(http.get).toHaveBeenLastCalledWith("/api/job-twins/candidates", { params: {} });
    await jobTwinsApi.candidates(0);
    expect(http.get).toHaveBeenLastCalledWith("/api/job-twins/candidates", { params: {} });
  });

  it("zasady: odczyt, zapis PUT-em i podgląd z sygnałem przerwania", async () => {
    http.get.mockResolvedValueOnce({ data: { rules: RULES } });
    await jobTwinsApi.rules();
    expect(http.get).toHaveBeenLastCalledWith("/api/job-twins/rules");

    http.put.mockResolvedValueOnce({ data: { rules: RULES } });
    await jobTwinsApi.saveRules(RULES);
    expect(http.put).toHaveBeenCalledWith("/api/job-twins/rules", RULES);

    const ctrl = new AbortController();
    http.post.mockResolvedValueOnce({ data: { suggestions: 3 } });
    await expect(jobTwinsApi.previewRules(RULES, ctrl.signal)).resolves.toEqual({ suggestions: 3 });
    expect(http.post).toHaveBeenCalledWith("/api/job-twins/rules/preview", RULES, { signal: ctrl.signal });
  });

  it("odrzucenie podpowiedzi wysyła parę id w kolejności", async () => {
    http.post.mockResolvedValueOnce({ data: { ok: true } });
    await expect(jobTwinsApi.dismiss(4, 9)).resolves.toEqual({ ok: true });
    expect(http.post).toHaveBeenCalledWith("/api/job-twins/dismiss", { job_ids: [4, 9] });
  });

  it("błąd serwera przechodzi do wołającego, nie zamienia się w pustą listę", async () => {
    http.get.mockRejectedValueOnce(new Error("503"));
    await expect(jobTwinsApi.twins(4)).rejects.toThrow("503");
  });
});

describe("useJobTwins / useOpenSimilarJobs / useTwinSuggestions", () => {
  it("pobiera bliźniaki dla poprawnego id", async () => {
    const { wrapper } = setup();
    http.get.mockResolvedValueOnce({ data: { job_id: 4, can_manage: true, max_twins: 3, twins: [] } });
    const { result } = renderHook(() => useJobTwins(4), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.can_manage).toBe(true);
  });

  it("nie pyta serwera o id 0, NaN, ujemne ani przy wyłączeniu", () => {
    const { wrapper } = setup();
    renderHook(() => useJobTwins(0), { wrapper });
    renderHook(() => useJobTwins(Number.NaN), { wrapper });
    renderHook(() => useOpenSimilarJobs(-3), { wrapper });
    renderHook(() => useOpenSimilarJobs(4, false), { wrapper });
    renderHook(() => useTwinSuggestions(false), { wrapper });
    expect(http.get).not.toHaveBeenCalled();
  });

  it("podobne otwarte i lista HoR pobierają się, gdy włączone", async () => {
    const { wrapper } = setup();
    http.get.mockImplementation(async (url: string) =>
      url === "/api/job-twins/suggestions"
        ? { data: { min_similarity: 70, items: [] } }
        : { data: { job_id: 4, items: [] } },
    );
    const a = renderHook(() => useOpenSimilarJobs(4), { wrapper });
    const b = renderHook(() => useTwinSuggestions(true), { wrapper });
    await waitFor(() => expect(a.result.current.isSuccess).toBe(true));
    await waitFor(() => expect(b.result.current.isSuccess).toBe(true));
    expect(b.result.current.data?.min_similarity).toBe(70);
  });

  it("lista HoR nie ponawia po błędzie (403 dla zwykłego rekrutera)", async () => {
    const { qc } = setup();
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: qc }, children);
    qc.setDefaultOptions({ queries: { retry: 3, retryDelay: 0 } });
    http.get.mockRejectedValue(new Error("403"));
    const { result } = renderHook(() => useTwinSuggestions(true), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(http.get).toHaveBeenCalledTimes(1);
  });
});

describe("połączenie i rozłączenie unieważniają obie strony", () => {
  function seed(qc: QueryClient) {
    const keys = [
      jobTwinsKeys.twins(4),
      jobTwinsKeys.twins(9),
      jobTwinsKeys.openSimilar(4),
      jobTwinsKeys.openSimilar(9),
      similarJobsKey(4),
      similarJobsKey(9),
      jobTwinsKeys.suggestions(),
      ["screening-question-groups", 4],
      ["screening-form", 1, 2, "joint-context"],
      ["screening-form", 1, 2, "answers"],
      ["job-twins", 77],
    ] as const;
    for (const k of keys) qc.setQueryData(k, { seeded: true });
    return (k: readonly unknown[]) => qc.getQueryState(k)?.isInvalidated;
  }

  it("useLinkTwin: po sukcesie odświeża obie rekrutacje, HoR, grupy pytań i „Screening dla”", async () => {
    const { qc, wrapper } = setup();
    const invalidated = seed(qc);
    http.post.mockResolvedValueOnce({ data: { linked_now: true } });
    const { result } = renderHook(() => useLinkTwin(4), { wrapper });
    await act(() => result.current.mutateAsync({ otherId: 9, pairs: [{ own: "q1", other: "q1" }] }));

    expect(http.post).toHaveBeenCalledWith("/api/jobs/4/twins", {
      other_job_id: 9,
      question_pairs: [{ own: "q1", other: "q1" }],
    });
    for (const id of [4, 9]) {
      expect(invalidated(jobTwinsKeys.twins(id))).toBe(true);
      expect(invalidated(jobTwinsKeys.openSimilar(id))).toBe(true);
      expect(invalidated(similarJobsKey(id))).toBe(true);
    }
    expect(invalidated(jobTwinsKeys.suggestions())).toBe(true);
    expect(invalidated(["screening-question-groups", 4])).toBe(true);
    expect(invalidated(["screening-form", 1, 2, "joint-context"])).toBe(true);
    // Sam formularz screeningu i cudze rekrutacje zostają w spokoju.
    expect(invalidated(["screening-form", 1, 2, "answers"])).toBe(false);
    expect(invalidated(["job-twins", 77])).toBe(false);
  });

  it("useLinkTwin: błąd serwera niczego nie unieważnia", async () => {
    const { qc, wrapper } = setup();
    const invalidated = seed(qc);
    http.post.mockRejectedValueOnce(new Error("409"));
    const { result } = renderHook(() => useLinkTwin(4), { wrapper });
    await act(async () => {
      await expect(result.current.mutateAsync({ otherId: 9, pairs: [] })).rejects.toThrow("409");
    });
    expect(invalidated(jobTwinsKeys.twins(4))).toBe(false);
    expect(invalidated(jobTwinsKeys.suggestions())).toBe(false);
  });

  it("useUnlinkTwin: rozłącza i odświeża obie strony", async () => {
    const { qc, wrapper } = setup();
    const invalidated = seed(qc);
    http.delete.mockResolvedValueOnce({ data: { unlinked_now: true } });
    const { result } = renderHook(() => useUnlinkTwin(4), { wrapper });
    await act(() => result.current.mutateAsync(9));
    expect(http.delete).toHaveBeenCalledWith("/api/jobs/4/twins/9");
    expect(invalidated(jobTwinsKeys.twins(9))).toBe(true);
    expect(invalidated(similarJobsKey(4))).toBe(true);
  });

  it("useDismissTwinSuggestion: odświeża tylko listę HoR", async () => {
    const { qc, wrapper } = setup();
    const invalidated = seed(qc);
    http.post.mockResolvedValueOnce({ data: {} });
    const { result } = renderHook(() => useDismissTwinSuggestion(), { wrapper });
    await act(() => result.current.mutateAsync({ jobId: 4, otherId: 9 }));
    expect(http.post).toHaveBeenCalledWith("/api/job-twins/dismiss", { job_ids: [4, 9] });
    expect(invalidated(jobTwinsKeys.suggestions())).toBe(true);
    expect(invalidated(jobTwinsKeys.twins(4))).toBe(false);
  });
});

describe("zasady bliźniaków — hooki", () => {
  it("useTwinRules pobiera zasady", async () => {
    const { wrapper } = setup();
    http.get.mockResolvedValueOnce({ data: { rules: RULES, defaults: RULES, labels: {}, can_edit: false } });
    const { result } = renderHook(() => useTwinRules(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.can_edit).toBe(false);
  });

  it("useSaveTwinRules zapisuje odpowiedź w cache i odświeża listę HoR oraz wszystkie podobne otwarte", async () => {
    const { qc, wrapper } = setup();
    qc.setQueryData(jobTwinsKeys.suggestions(), { items: [] });
    qc.setQueryData(jobTwinsKeys.openSimilar(4), { items: [] });
    qc.setQueryData(jobTwinsKeys.openSimilar(9), { items: [] });
    const saved = { rules: { ...RULES, min_similarity: 80 }, defaults: RULES, labels: {}, can_edit: true };
    http.put.mockResolvedValueOnce({ data: saved });
    const { result } = renderHook(() => useSaveTwinRules(), { wrapper });
    await act(() => result.current.mutateAsync({ ...RULES, min_similarity: 80 }));
    expect(qc.getQueryData(jobTwinsKeys.rules())).toEqual(saved);
    expect(qc.getQueryState(jobTwinsKeys.suggestions())?.isInvalidated).toBe(true);
    expect(qc.getQueryState(jobTwinsKeys.openSimilar(4))?.isInvalidated).toBe(true);
    expect(qc.getQueryState(jobTwinsKeys.openSimilar(9))?.isInvalidated).toBe(true);
  });
});

describe("etykiety bliźniaków", () => {
  it("powód pominięcia: znany kod ma etykietę, nieznany wraca jako kod", () => {
    expect(twinSkipLabel("client_conflict")).toBe("Konflikt u klienta bliźniaka");
    expect(twinSkipLabel("nowy_kod_serwera")).toBe("nowy_kod_serwera");
    expect(TWIN_SKIP_REASONS.map((r) => r.code)).toContain("other");
  });

  it("tryb pracy: biuro, hybryda z dniami w miesiącu, hybryda bez dni i zera", () => {
    const base = { onsite_days_per_week: null, onsite_days_per_month: null };
    expect(workModeLabel({ ...base, remote_policy: "onsite" })).toBe("w biurze");
    expect(workModeLabel({ ...base, remote_policy: "hybrid", onsite_days_per_month: 4 })).toBe(
      "4 dni z biura w miesiącu",
    );
    expect(workModeLabel({ ...base, remote_policy: "hybrid" })).toBe("hybrydowo");
    // Zero dni w tygodniu nie wygrywa z dniami w miesiącu.
    expect(
      workModeLabel({ remote_policy: "hybrid", onsite_days_per_week: 0, onsite_days_per_month: 2 }),
    ).toBe("2 dni z biura w miesiącu");
    expect(workModeLabel({ remote_policy: "hybrid", onsite_days_per_week: 0, onsite_days_per_month: 0 })).toBe(
      "hybrydowo",
    );
    expect(workModeLabel({ ...base, remote_policy: "flexible" })).toBe("tryb pracy nie podany");
  });

  it("numer w nagłówku: pusty numer u klienta ustępuje naszemu, a ten — id", () => {
    expect(twinRef({ client_reference: "", reference_number: "ACME/001/2026", id: 7 })).toBe("ACME/001/2026");
    expect(twinRef({ client_reference: null, reference_number: null, id: 7 })).toBe("#7");
  });

  it("plakietka zasady to etykieta małymi literami", () => {
    expect(
      ruleChipLabel({ key: "location", label: "Lokalizacja", mode: "warning", ok: false, detail: "Kraków ≠ Gdańsk" }),
    ).toBe("lokalizacja");
  });
});
