import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import {
  addonTechnology,
  frameworkKeys,
  frameworkReportPath,
  importFrameworkTerms,
  recomputeFrameworkCategories,
  useClaimAction,
  useCreateClaim,
  useFrameworkCategory,
  useFrameworkOverview,
  useFrameworkProlongations,
  useFrameworkTerms,
  useJustificationDraft,
  usePremiumSkills,
  useSaveFrameworkCategory,
} from "@/lib/api/framework-rates";

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, invalidate, wrapper };
}

beforeEach(() => {
  for (const fn of Object.values(apiMock)) {
    fn.mockReset();
    fn.mockResolvedValue({ data: { ok: true } });
  }
});

describe("addonTechnology", () => {
  it("odcina procent dopłaty z końca etykiety", () => {
    expect(addonTechnology("Kafka 20%")).toBe("Kafka");
    expect(addonTechnology("Apache Spark 12,5%")).toBe("Apache Spark");
    expect(addonTechnology("Go 7.5%")).toBe("Go");
  });

  it("zostawia etykietę bez procentu albo z procentem w środku", () => {
    expect(addonTechnology("Kafka")).toBe("Kafka");
    expect(addonTechnology("C++ 20% senior")).toBe("C++ 20% senior");
    expect(addonTechnology("Kafka20%")).toBe("Kafka20%");
  });
});

describe("ścieżki i klucze", () => {
  it("raport przeglądu limitów jako xlsx klienta", () => {
    expect(frameworkReportPath(12)).toBe("/api/clients/12/framework-overview/report.xlsx");
    expect(frameworkKeys.terms(3)).toEqual(["framework-terms", 3]);
    expect(frameworkKeys.category(4)).toEqual(["framework-category", 4]);
  });
});

describe("importFrameworkTerms", () => {
  it("podgląd bez daty: apply=false i bez `valid_from`", async () => {
    const file = new File(["x"], "cennik.xlsx");
    await expect(importFrameworkTerms(5, file, false, null)).resolves.toEqual({ ok: true });
    const [url, form, config] = apiMock.post.mock.calls[0];
    expect(url).toBe("/api/clients/5/framework-terms/import");
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });
    const fd = form as FormData;
    expect(fd.get("file")).toBe(file);
    expect(fd.get("apply")).toBe("false");
    expect(fd.has("valid_from")).toBe(false);
  });

  it("zapis od daty: apply=true i `valid_from`", async () => {
    await importFrameworkTerms(5, new File(["x"], "c.xlsx"), true, "2027-01-01");
    const fd = apiMock.post.mock.calls[0][1] as FormData;
    expect(fd.get("apply")).toBe("true");
    expect(fd.get("valid_from")).toBe("2027-01-01");
  });

  it("pusta data traktowana jak brak daty", async () => {
    await importFrameworkTerms(5, new File(["x"], "c.xlsx"), true, "");
    expect((apiMock.post.mock.calls[0][1] as FormData).has("valid_from")).toBe(false);
  });

  it("422 z serwera wraca do ekranu", async () => {
    const error = { response: { status: 422 } };
    apiMock.post.mockRejectedValueOnce(error);
    await expect(importFrameworkTerms(5, new File(["x"], "c.xlsx"), false, null)).rejects.toBe(error);
  });
});

describe("recomputeFrameworkCategories", () => {
  it("porcja od `after_id` z flagą zapisu w parametrach, bez ciała", async () => {
    await recomputeFrameworkCategories(9, 0, false);
    expect(apiMock.post).toHaveBeenCalledWith(
      "/api/clients/9/framework-categories/recompute",
      null,
      { params: { after_id: 0, apply: false } },
    );
  });
});

describe("zapytania", () => {
  it("cennik, kategoria, przegląd, dopłaty i prolongaty czytają swoje trasy", async () => {
    const { wrapper } = setup();
    const hooks = [
      () => useFrameworkTerms(1, true),
      () => useFrameworkCategory(2, true),
      () => useFrameworkOverview(3, true),
      () => usePremiumSkills(4, true),
      () => useFrameworkProlongations(5, true),
    ];
    for (const hook of hooks) {
      const { result } = renderHook(() => hook(), { wrapper });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual({ ok: true });
    }
    expect(apiMock.get.mock.calls.map((c) => c[0])).toEqual([
      "/api/clients/1/framework-terms",
      "/api/contracts/2/framework-category",
      "/api/clients/3/framework-overview",
      "/api/contracts/4/premium-skills",
      "/api/clients/5/framework-prolongations",
    ]);
  });

  it("wyłączone zapytanie nie idzie do serwera", () => {
    const { wrapper } = setup();
    renderHook(() => useFrameworkTerms(1, false), { wrapper });
    renderHook(() => useFrameworkCategory(1, false), { wrapper });
    expect(apiMock.get).not.toHaveBeenCalled();
  });

  it("błąd zapytania to błąd, nie pusty wynik", async () => {
    const { wrapper } = setup();
    apiMock.get.mockRejectedValueOnce({ response: { status: 500 } });
    const { result } = renderHook(() => useFrameworkOverview(3, true), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });
});

describe("mutacje", () => {
  it("zapis kategorii wkłada wynik do pamięci i odświeża kontrakt pod obiema postaciami klucza", async () => {
    const { wrapper, queryClient, invalidate } = setup();
    const saved = { rate_card_id: 2, status: "in" };
    apiMock.put.mockResolvedValueOnce({ data: saved });
    const { result } = renderHook(() => useSaveFrameworkCategory(77), { wrapper });
    const input = {
      rate_card_id: 2,
      addon_technology: null,
      confirmed_by: null,
      confirmed_on: null,
      evidence: null,
      effective_from: "2026-12-01",
    };
    await result.current.mutateAsync(input);
    expect(apiMock.put).toHaveBeenCalledWith("/api/contracts/77/framework-category", input);
    expect(queryClient.getQueryData(frameworkKeys.category(77))).toEqual(saved);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["contract", "77"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["contract", 77] });
  });

  it("nowe zgłoszenie dopłaty odświeża dopłaty, kategorię i kontrakt", async () => {
    const { wrapper, queryClient, invalidate } = setup();
    const skills = { claims: [] };
    apiMock.post.mockResolvedValueOnce({ data: skills });
    const { result } = renderHook(() => useCreateClaim(8), { wrapper });
    const input = { technology: "Kafka", knows: true, uses: false, note: null };
    await result.current.mutateAsync(input);
    expect(apiMock.post).toHaveBeenCalledWith("/api/contracts/8/premium-skills/claims", input);
    expect(queryClient.getQueryData(["premium-skills", 8])).toEqual(skills);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["framework-category", 8] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["contract", 8] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["contract", "8"] });
  });

  it("akcja na zgłoszeniu: id w ścieżce, reszta w ciele bez `claimId`", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useClaimAction(8), { wrapper });
    await result.current.mutateAsync({ claimId: 3, action: "refuse", reason: "Brak dowodu" });
    expect(apiMock.post).toHaveBeenCalledWith(
      "/api/contracts/8/premium-skills/claims/3/action",
      { action: "refuse", reason: "Brak dowodu" },
    );
  });

  it("szkic uzasadnienia nie zmienia pamięci zapytań", async () => {
    const { wrapper, invalidate } = setup();
    apiMock.post.mockResolvedValueOnce({ data: { text: "Szkic" } });
    const { result } = renderHook(() => useJustificationDraft(8), { wrapper });
    await expect(result.current.mutateAsync(3)).resolves.toEqual({ text: "Szkic" });
    expect(apiMock.post).toHaveBeenCalledWith(
      "/api/contracts/8/premium-skills/claims/3/justification-draft",
    );
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("odrzucony zapis nie wkłada niczego do pamięci", async () => {
    const { wrapper, queryClient } = setup();
    apiMock.post.mockRejectedValueOnce({ response: { status: 403 } });
    const { result } = renderHook(() => useCreateClaim(8), { wrapper });
    await expect(
      result.current.mutateAsync({ technology: "Go", knows: false, uses: false, note: "x" }),
    ).rejects.toEqual({ response: { status: 403 } });
    expect(queryClient.getQueryData(["premium-skills", 8])).toBeUndefined();
  });
});
