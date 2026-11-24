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
  type GarnishmentInput,
  batchFilePath,
  paymentKeys,
  useAssignDebit,
  useBatchDetail,
  useBatches,
  useCancelBatch,
  useCreateBatch,
  useEntryAccount,
  useEntryPaid,
  useEntryPayment,
  useGarnishments,
  useHolds,
  useIgnoreDebit,
  useLiftGarnishment,
  usePaymentPlan,
  usePaymentSettings,
  useReleaseHold,
  useReleaseItem,
  useSaveGarnishment,
  useSavePaymentSettings,
  useSetHold,
  useStatementOverview,
  useUploadStatement,
} from "@/lib/api/finance-payments";

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

function expectRefreshesPaymentsAndCosts(invalidate: ReturnType<typeof setup>["invalidate"]) {
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["finance-payments"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["finance-ledger", "costs"] });
}

const garnishment: GarnishmentInput = {
  authority_kind: "bailiff",
  authority_name: "Komornik Testowy",
  case_number: "KM 1/26",
  served_on: "2026-12-31",
  principal_amount: "1000.00",
  costs_amount: "0.00",
  interest_mode: "none",
  interest_amount: null,
  interest_rate: null,
  interest_from: null,
  authority_account: null,
  note: null,
};

beforeEach(() => {
  for (const fn of Object.values(apiMock)) {
    fn.mockReset();
    fn.mockResolvedValue({ data: { ok: true } });
  }
});

describe("batchFilePath i klucze", () => {
  it("plik paczki pod id, klucze pod wspólnym prefiksem", () => {
    expect(batchFilePath(17)).toBe("/api/finance/payments/batches/17/file");
    expect(paymentKeys.plan("2027-01-05")).toEqual(["finance-payments", "plan", "2027-01-05"]);
    expect(paymentKeys.entry(3)).toEqual(["finance-payments", "entry", 3]);
  });
});

describe("zapytania", () => {
  it("plan płatności idzie POST-em z datą „do”", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => usePaymentPlan("2026-12-31"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMock.post).toHaveBeenCalledWith("/api/finance/payments/plan", {
      until: "2026-12-31",
    });
  });

  it("paczki, wyciągi, ustawienia, zajęcia i wstrzymania czytają swoje trasy", async () => {
    const { wrapper } = setup();
    for (const hook of [
      () => useBatches(),
      () => useStatementOverview(),
      () => usePaymentSettings(),
      () => useGarnishments(),
      () => useHolds(),
      () => useBatchDetail(4),
      () => useEntryPayment(9),
    ]) {
      const { result } = renderHook(() => hook(), { wrapper });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
    }
    expect(apiMock.get.mock.calls.map((c) => c[0])).toEqual([
      "/api/finance/payments/batches",
      "/api/finance/payments/statements",
      "/api/finance/payments/settings",
      "/api/finance/payments/garnishments",
      "/api/finance/payments/holds",
      "/api/finance/payments/batches/4",
      "/api/finance/payments/entries/9",
    ]);
  });

  it("szczegóły paczki bez wybranej paczki nie pytają serwera, także przy id 0", async () => {
    const { wrapper } = setup();
    renderHook(() => useBatchDetail(null), { wrapper });
    expect(apiMock.get).not.toHaveBeenCalled();
    const { result } = renderHook(() => useBatchDetail(0), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMock.get).toHaveBeenCalledWith("/api/finance/payments/batches/0");
  });

  it("płatność pozycji tylko dla dodatniego, skończonego id", () => {
    const { wrapper } = setup();
    renderHook(() => useEntryPayment(0), { wrapper });
    renderHook(() => useEntryPayment(-1), { wrapper });
    renderHook(() => useEntryPayment(Number.NaN), { wrapper });
    renderHook(() => useEntryPayment(Number.POSITIVE_INFINITY), { wrapper });
    expect(apiMock.get).not.toHaveBeenCalled();
  });
});

describe("mutacje paczek i wyciągów", () => {
  it("utworzenie, zwolnienie pozycji i anulowanie paczki odświeżają płatności i koszty", async () => {
    const { wrapper, invalidate } = setup();
    const create = renderHook(() => useCreateBatch(), { wrapper });
    const body = { entry_ids: [1], acknowledged: [], execution_date: "2027-01-04", format: "csv" as const };
    await create.result.current.mutateAsync(body);
    const release = renderHook(() => useReleaseItem(), { wrapper });
    await release.result.current.mutateAsync({ batchId: 2, entryId: 3 });
    const cancel = renderHook(() => useCancelBatch(), { wrapper });
    await cancel.result.current.mutateAsync(2);
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/finance/payments/batches", body],
      ["/api/finance/payments/batches/2/items/3/release"],
      ["/api/finance/payments/batches/2/cancel"],
    ]);
    expectRefreshesPaymentsAndCosts(invalidate);
  });

  it("odrzucone utworzenie paczki też odświeża listy (onSettled)", async () => {
    const { wrapper, invalidate } = setup();
    apiMock.post.mockRejectedValueOnce({ response: { status: 409 } });
    const { result } = renderHook(() => useCreateBatch(), { wrapper });
    await expect(
      result.current.mutateAsync({ entry_ids: [], acknowledged: [], execution_date: "2026-12-01", format: "elixir" }),
    ).rejects.toEqual({ response: { status: 409 } });
    expectRefreshesPaymentsAndCosts(invalidate);
  });

  it("wgranie wyciągu, przypisanie i pominięcie obciążenia", async () => {
    const { wrapper, invalidate } = setup();
    const upload = renderHook(() => useUploadStatement(), { wrapper });
    const file = new File(["x"], "camt.xml");
    await upload.result.current.mutateAsync(file);
    const [url, form, config] = apiMock.post.mock.calls[0];
    expect(url).toBe("/api/finance/payments/statements");
    expect((form as FormData).get("file")).toBe(file);
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });

    const assign = renderHook(() => useAssignDebit(), { wrapper });
    await assign.result.current.mutateAsync({ id: 5, entryId: 6 });
    const ignore = renderHook(() => useIgnoreDebit(), { wrapper });
    await ignore.result.current.mutateAsync({ id: 7, reason: "Opłata bankowa" });
    expect(apiMock.post.mock.calls.slice(1)).toEqual([
      ["/api/finance/payments/records/5/assign", { entry_id: 6 }],
      ["/api/finance/payments/records/7/ignore", { reason: "Opłata bankowa" }],
    ]);
    expectRefreshesPaymentsAndCosts(invalidate);
  });
});

describe("ustawienia i pozycje", () => {
  it("zapis ustawień wkłada odpowiedź do pamięci bez odświeżania listy", async () => {
    const { wrapper, queryClient, invalidate } = setup();
    const saved = { sender_name: "Firma Testowa sp. z o.o.", sender_account_last4: "0000" };
    apiMock.put.mockResolvedValueOnce({ data: saved });
    const { result } = renderHook(() => useSavePaymentSettings(), { wrapper });
    const body = { sender_name: "Firma Testowa sp. z o.o.", sender_account: "PL00" };
    await result.current.mutateAsync(body);
    expect(apiMock.put).toHaveBeenCalledWith("/api/finance/payments/settings", body);
    expect(queryClient.getQueryData(paymentKeys.settings)).toEqual(saved);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("rachunek pozycji: null kasuje ręczny rachunek; wynik do pamięci pozycji", async () => {
    const { wrapper, queryClient, invalidate } = setup();
    apiMock.put.mockResolvedValueOnce({ data: { id: 11, state: "unpaid" } });
    const { result } = renderHook(() => useEntryAccount(11), { wrapper });
    await result.current.mutateAsync({ account: null, remember: false });
    expect(apiMock.put).toHaveBeenCalledWith("/api/finance/payments/entries/11", {
      account: null,
      remember: false,
    });
    expect(queryClient.getQueryData(paymentKeys.entry(11))).toEqual({ id: 11, state: "unpaid" });
    expectRefreshesPaymentsAndCosts(invalidate);
  });

  it("ręczne oznaczenie zapłaty z kwotą częściową", async () => {
    const { wrapper, queryClient } = setup();
    apiMock.post.mockResolvedValueOnce({ data: { id: 11, state: "partially_paid" } });
    const { result } = renderHook(() => useEntryPaid(11), { wrapper });
    const body = { amount: "0.01", paid_on: "2027-01-01", reason: "Przelew poza paczką" };
    await result.current.mutateAsync(body);
    expect(apiMock.post).toHaveBeenCalledWith("/api/finance/payments/entries/11/paid", body);
    expect(queryClient.getQueryData(paymentKeys.entry(11))).toEqual({
      id: 11,
      state: "partially_paid",
    });
  });
});

describe("zajęcia i wstrzymania", () => {
  it("nowe zajęcie: POST z `contract_id` dołożonym do ciała", async () => {
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useSaveGarnishment(), { wrapper });
    await result.current.mutateAsync({ id: null, contractId: 31, body: garnishment });
    expect(apiMock.post).toHaveBeenCalledWith("/api/finance/payments/garnishments", {
      ...garnishment,
      contract_id: 31,
    });
    expect(apiMock.put).not.toHaveBeenCalled();
    expectRefreshesPaymentsAndCosts(invalidate);
  });

  it("poprawka zajęcia: PUT pod id, bez `contract_id`; id 0 to też poprawka", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useSaveGarnishment(), { wrapper });
    await result.current.mutateAsync({ id: 0, contractId: 31, body: garnishment });
    expect(apiMock.put).toHaveBeenCalledWith("/api/finance/payments/garnishments/0", garnishment);
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it("zdjęcie zajęcia, wstrzymanie i zwolnienie płatności", async () => {
    const { wrapper, invalidate } = setup();
    const lift = renderHook(() => useLiftGarnishment(), { wrapper });
    await lift.result.current.mutateAsync({ id: 3, lifted_on: "2026-12-31", note: null });
    const hold = renderHook(() => useSetHold(), { wrapper });
    await hold.result.current.mutateAsync({ entry_id: 8, reason: "Spór o fakturę" });
    const release = renderHook(() => useReleaseHold(), { wrapper });
    await release.result.current.mutateAsync({ id: 4, note: null });
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/finance/payments/garnishments/3/lift", { lifted_on: "2026-12-31", note: null }],
      ["/api/finance/payments/holds", { entry_id: 8, reason: "Spór o fakturę" }],
      ["/api/finance/payments/holds/4/release", { note: null }],
    ]);
    expectRefreshesPaymentsAndCosts(invalidate);
  });
});
