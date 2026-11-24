import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
}));
const filesMock = vi.hoisted(() => ({
  fetchAuthenticatedDownload: vi.fn(),
  downloadBlob: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));
vi.mock("@/lib/authenticated-files", () => filesMock);

import {
  type DecreeInput,
  type PostingBatch,
  downloadBatchFile,
  postingKeys,
  useAccountSave,
  useAccounts,
  useBatchAction,
  useBatchCreate,
  useChoiceLists,
  useCounterpartyOptions,
  useDecreeRecalculate,
  useDecreeSave,
  useDescriptionSave,
  useExportPreview,
  useRuleSave,
  useRules,
} from "@/lib/api/finance-posting";

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
    fn.mockResolvedValue({ data: { items: [] } });
  }
  filesMock.fetchAuthenticatedDownload.mockReset();
  filesMock.downloadBlob.mockReset();
});

describe("zapytania", () => {
  it("konta i reguły zwracają samą listę `items`", async () => {
    const { wrapper } = setup();
    apiMock.get.mockResolvedValueOnce({ data: { items: [{ number: "402-01" }] } });
    const accounts = renderHook(() => useAccounts(), { wrapper });
    await waitFor(() => expect(accounts.result.current.isSuccess).toBe(true));
    expect(accounts.result.current.data).toEqual([{ number: "402-01" }]);

    apiMock.get.mockResolvedValueOnce({ data: { items: [] } });
    const rules = renderHook(() => useRules(), { wrapper });
    await waitFor(() => expect(rules.result.current.isSuccess).toBe(true));
    expect(rules.result.current.data).toEqual([]);
    expect(apiMock.get.mock.calls.map((c) => c[0])).toEqual([
      "/api/finance/posting/accounts",
      "/api/finance/posting/rules",
    ]);
  });

  it("podpowiedzi kontrahentów dopiero od 2 znaków bez spacji", async () => {
    const { wrapper } = setup();
    renderHook(() => useCounterpartyOptions(""), { wrapper });
    renderHook(() => useCounterpartyOptions("F"), { wrapper });
    renderHook(() => useCounterpartyOptions(" F "), { wrapper });
    expect(apiMock.get).not.toHaveBeenCalled();

    const { result } = renderHook(() => useCounterpartyOptions("Fi"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMock.get).toHaveBeenCalledWith("/api/finance/posting/counterparty-options", {
      params: { q: "Fi" },
    });
  });

  it("listy wyboru: wyłączone nie pytają, włączone czytają", async () => {
    const { wrapper } = setup();
    renderHook(() => useChoiceLists(false), { wrapper });
    expect(apiMock.get).not.toHaveBeenCalled();
    apiMock.get.mockResolvedValueOnce({ data: { registers: [] } });
    const { result } = renderHook(() => useChoiceLists(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ registers: [] });
    expect(apiMock.get).toHaveBeenCalledWith("/api/finance/posting/choice-lists");
  });

  it("podgląd eksportu przy zmianie miesiąca (12 → 01) trzyma poprzedni wynik do odpowiedzi", async () => {
    const { wrapper } = setup();
    apiMock.get.mockResolvedValueOnce({ data: { month: "2026-12" } });
    let resolveJanuary: (value: unknown) => void = () => {};
    apiMock.get.mockReturnValueOnce(new Promise((resolve) => (resolveJanuary = resolve)));

    const { result, rerender } = renderHook(({ month }) => useExportPreview(month), {
      wrapper,
      initialProps: { month: "2026-12" },
    });
    await waitFor(() => expect(result.current.data).toEqual({ month: "2026-12" }));

    rerender({ month: "2027-01" });
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(2));
    expect(result.current.data).toEqual({ month: "2026-12" });
    expect(result.current.isPlaceholderData).toBe(true);
    expect(apiMock.get).toHaveBeenLastCalledWith("/api/finance/posting/export", {
      params: { month: "2027-01" },
    });

    resolveJanuary({ data: { month: "2027-01" } });
    await waitFor(() => expect(result.current.data).toEqual({ month: "2027-01" }));
  });
});

describe("konta i reguły — zapis", () => {
  it("nowe konto POST-em, poprawka PATCH-em bez id w ciele", async () => {
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useAccountSave(), { wrapper });
    await result.current.mutateAsync({ number: "402-01", name: "Usługi obce", kind: "cost" });
    await result.current.mutateAsync({ id: 5, active: false });
    expect(apiMock.post).toHaveBeenCalledWith("/api/finance/posting/accounts", {
      number: "402-01",
      name: "Usługi obce",
      kind: "cost",
    });
    expect(apiMock.patch).toHaveBeenCalledWith("/api/finance/posting/accounts/5", { active: false });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: postingKeys.accounts });
  });

  it("reguła: zapis odświeża reguły i konta (nowe konto z reguły)", async () => {
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useRuleSave(), { wrapper });
    await result.current.mutateAsync({ cost_account: "402-02", counterparty_id: null });
    await result.current.mutateAsync({ id: 9, active: true });
    expect(apiMock.post).toHaveBeenCalledWith("/api/finance/posting/rules", {
      cost_account: "402-02",
      counterparty_id: null,
    });
    expect(apiMock.patch).toHaveBeenCalledWith("/api/finance/posting/rules/9", { active: true });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: postingKeys.rules });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: postingKeys.accounts });
  });
});

describe("dekret na karcie kosztu", () => {
  const decree: DecreeInput = {
    register: "purchase",
    doc_type: "FZ",
    description: "Usługa IT",
    positions: [
      { kind: "cost", account: "402-01", side: "debit", amount: "0.00" },
      { kind: "counterparty", account: "202-1", side: "credit", amount: "-100.00", vat_rate: null },
    ],
  };

  it("przeliczenie, zapis dekretu i opisu odświeżają kartę, kolejkę i eksport", async () => {
    const { wrapper, queryClient, invalidate } = setup();
    const card = { id: 21, decree: { ok: true } };
    apiMock.post.mockResolvedValueOnce({ data: card });
    apiMock.put.mockResolvedValue({ data: card });

    const recalc = renderHook(() => useDecreeRecalculate(21), { wrapper });
    await recalc.result.current.mutateAsync();
    const save = renderHook(() => useDecreeSave(21), { wrapper });
    await save.result.current.mutateAsync(decree);
    const desc = renderHook(() => useDescriptionSave(21), { wrapper });
    await desc.result.current.mutateAsync({ description: null, eu: false, import_rate: 0 });

    expect(apiMock.post).toHaveBeenCalledWith("/api/finance/posting/entries/21/recalculate");
    expect(apiMock.put.mock.calls).toEqual([
      ["/api/finance/posting/entries/21/decree", decree],
      ["/api/finance/posting/entries/21/description", { description: null, eu: false, import_rate: 0 }],
    ]);
    expect(queryClient.getQueryData(["finance-ledger", "costs", "card", 21])).toEqual(card);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["finance-ledger", "costs", "queue"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: postingKeys.exports });
  });

  it("odrzucony dekret (np. 422 niezbilansowany) nie podmienia karty", async () => {
    const { wrapper, queryClient } = setup();
    queryClient.setQueryData(["finance-ledger", "costs", "card", 21], { id: 21, old: true });
    apiMock.put.mockRejectedValueOnce({ response: { status: 422 } });
    const { result } = renderHook(() => useDecreeSave(21), { wrapper });
    await expect(result.current.mutateAsync(decree)).rejects.toEqual({ response: { status: 422 } });
    expect(queryClient.getQueryData(["finance-ledger", "costs", "card", 21])).toEqual({
      id: 21,
      old: true,
    });
  });
});

describe("paczki eksportu", () => {
  const batch = { id: 3, file_name: "dekrety-2026-12.xml" } as PostingBatch;

  it("pobranie pliku: nazwa z nagłówka serwera ma pierwszeństwo", async () => {
    const blob = new Blob(["<xml/>"]);
    filesMock.fetchAuthenticatedDownload.mockResolvedValueOnce({ blob, filename: "z-serwera.xml" });
    await downloadBatchFile(batch);
    expect(filesMock.fetchAuthenticatedDownload).toHaveBeenCalledWith(
      "/api/finance/posting/batches/3/file",
    );
    expect(filesMock.downloadBlob).toHaveBeenCalledWith(blob, "z-serwera.xml");
  });

  it("pobranie pliku: bez nazwy z serwera bierze nazwę z paczki", async () => {
    const blob = new Blob(["<xml/>"]);
    filesMock.fetchAuthenticatedDownload.mockResolvedValueOnce({ blob, filename: null });
    await downloadBatchFile(batch);
    expect(filesMock.downloadBlob).toHaveBeenCalledWith(blob, "dekrety-2026-12.xml");
  });

  it("nieudane pobranie nie zapisuje pliku", async () => {
    filesMock.fetchAuthenticatedDownload.mockRejectedValueOnce(new Error("Brak uprawnień"));
    await expect(downloadBatchFile(batch)).rejects.toThrow("Brak uprawnień");
    expect(filesMock.downloadBlob).not.toHaveBeenCalled();
  });

  it("utworzenie paczki i akcje zaksięguj/anuluj odświeżają eksport i koszty także po błędzie", async () => {
    const { wrapper, invalidate } = setup();
    const create = renderHook(() => useBatchCreate(), { wrapper });
    await create.result.current.mutateAsync({ month: "2026-12", format: "symfonia", journal: null });
    const action = renderHook(() => useBatchAction(), { wrapper });
    await action.result.current.mutateAsync({ id: 3, action: "book" });
    apiMock.post.mockRejectedValueOnce({ response: { status: 409 } });
    await expect(action.result.current.mutateAsync({ id: 3, action: "cancel" })).rejects.toBeTruthy();

    expect(apiMock.post.mock.calls).toEqual([
      ["/api/finance/posting/batches", { month: "2026-12", format: "symfonia", journal: null }],
      ["/api/finance/posting/batches/3/book"],
      ["/api/finance/posting/batches/3/cancel"],
    ]);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: postingKeys.exports });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["finance-ledger", "costs"] });
    expect(invalidate.mock.calls.length).toBeGreaterThanOrEqual(6);
  });
});
