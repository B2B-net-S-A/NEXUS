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
  type PaymentSettings,
  paymentKeys,
  paymentPaths,
  useAssignStatementLine,
  useBatches,
  useCancelBatch,
  useConfirmBatch,
  useCreateBatch,
  useFinanceList,
  useIgnoreStatementLine,
  useImportStatement,
  usePaymentSettings,
  usePreviewBatch,
  useSavePaymentSettings,
  useStatementOverview,
  useSymfoniaPreview,
} from "@/lib/api/hr-payments";

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

function expectInvalidatesPaymentsAndSettlements(invalidate: ReturnType<typeof setup>["invalidate"]) {
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["hr", "payments"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["hr", "settlements"] });
}

describe("paymentPaths", () => {
  it("eksport listy z okresem i bez okresu", () => {
    expect(paymentPaths.financeCsv(2026, 12)).toBe(
      "/api/hr/payments/finance/export.csv?year=2026&month=12",
    );
    expect(paymentPaths.financeCsv(null, null)).toBe("/api/hr/payments/finance/export.csv");
  });

  it("niepełny okres (sam rok albo sam miesiąc) to brak okresu", () => {
    expect(paymentPaths.financeCsv(2026, null)).toBe("/api/hr/payments/finance/export.csv");
    expect(paymentPaths.financeCsv(null, 1)).toBe("/api/hr/payments/finance/export.csv");
  });

  it("lista NIP-ów, plik paczki przelewów i paczka Symfonii", () => {
    expect(paymentPaths.nipList).toBe("/api/hr/payments/nip-list.csv");
    expect(paymentPaths.batchFile("B-2026-12-01")).toBe(
      "/api/hr/payments/batches/B-2026-12-01/file",
    );
    expect(paymentPaths.symfoniaZip(2027, 1)).toBe(
      "/api/hr/payments/symfonia/2027/1/package.zip",
    );
  });

  it("klucze zapytań mieszczą się pod wspólnym prefiksem płatności", () => {
    expect(paymentKeys.finance(null, null)).toEqual(["hr", "payments", "finance", null, null]);
    expect(paymentKeys.symfonia(2026, 12)).toEqual(["hr", "payments", "symfonia", 2026, 12]);
    for (const key of [paymentKeys.statements, paymentKeys.batches, paymentKeys.settings]) {
      expect(key.slice(0, 2)).toEqual(paymentKeys.all);
    }
  });
});

describe("zapytania", () => {
  it("lista dla Finansów z okresem i bez", async () => {
    const { wrapper } = setup();
    const a = renderHook(() => useFinanceList(2026, 12), { wrapper });
    await waitFor(() => expect(a.result.current.isSuccess).toBe(true));
    const b = renderHook(() => useFinanceList(null, null), { wrapper });
    await waitFor(() => expect(b.result.current.isSuccess).toBe(true));
    expect(apiMock.get.mock.calls.map((c) => c[0])).toEqual([
      "/api/hr/payments/finance?year=2026&month=12",
      "/api/hr/payments/finance",
    ]);
  });

  it("wyciągi, paczki, ustawienia i podgląd Symfonii", async () => {
    const { wrapper } = setup();
    for (const hook of [
      () => useStatementOverview(),
      () => useBatches(),
      () => usePaymentSettings(),
      () => useSymfoniaPreview(2026, 12),
    ]) {
      const { result } = renderHook(() => hook(), { wrapper });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
    }
    expect(apiMock.get.mock.calls.map((c) => c[0])).toEqual([
      "/api/hr/payments/statements",
      "/api/hr/payments/batches",
      "/api/hr/payments/settings",
      "/api/hr/payments/symfonia/2026/12/preview",
    ]);
  });

  it("wyłączone zapytania nie idą do serwera", () => {
    const { wrapper } = setup();
    renderHook(() => useFinanceList(2026, 12, false), { wrapper });
    renderHook(() => useStatementOverview(false), { wrapper });
    renderHook(() => useBatches(false), { wrapper });
    renderHook(() => usePaymentSettings(false), { wrapper });
    renderHook(() => useSymfoniaPreview(2026, 12, false), { wrapper });
    expect(apiMock.get).not.toHaveBeenCalled();
  });

  it("awaria listy to błąd, nie pusta lista", async () => {
    const { wrapper } = setup();
    apiMock.get.mockRejectedValueOnce({ response: { status: 503 } });
    const { result } = renderHook(() => useFinanceList(2026, 12), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });
});

describe("mutacje", () => {
  it("import wyciągu: plik w multipart, potem odświeżenie płatności i rozliczeń", async () => {
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useImportStatement(), { wrapper });
    const file = new File(["940"], "wyciag.sta");
    await result.current.mutateAsync(file);
    const [url, form, config] = apiMock.post.mock.calls[0];
    expect(url).toBe("/api/hr/payments/statements");
    expect((form as FormData).get("file")).toBe(file);
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });
    expectInvalidatesPaymentsAndSettlements(invalidate);
  });

  it("przypisanie i pominięcie linii wyciągu", async () => {
    const { wrapper, invalidate } = setup();
    const assign = renderHook(() => useAssignStatementLine(), { wrapper });
    await assign.result.current.mutateAsync({ lineId: 4, settlementId: 11 });
    const ignore = renderHook(() => useIgnoreStatementLine(), { wrapper });
    await ignore.result.current.mutateAsync({ lineId: 5, reason: "Zwrot kaucji" });
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/hr/payments/statement-lines/4/assign", { settlement_id: 11 }],
      ["/api/hr/payments/statement-lines/5/ignore", { reason: "Zwrot kaucji" }],
    ]);
    expectInvalidatesPaymentsAndSettlements(invalidate);
  });

  it("podgląd paczki: null = wszystkie gotowe; podgląd niczego nie odświeża", async () => {
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => usePreviewBatch(), { wrapper });
    await result.current.mutateAsync(null);
    await result.current.mutateAsync([]);
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/hr/payments/batches/preview", { settlement_ids: null }],
      ["/api/hr/payments/batches/preview", { settlement_ids: [] }],
    ]);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("utworzenie, potwierdzenie i anulowanie paczki", async () => {
    const { wrapper, invalidate } = setup();
    const create = renderHook(() => useCreateBatch(), { wrapper });
    await create.result.current.mutateAsync({ settlement_ids: [1, 2], execution_date: null });
    const confirm = renderHook(() => useConfirmBatch(), { wrapper });
    await confirm.result.current.mutateAsync({ key: "B1", paidOn: "2026-12-31" });
    await confirm.result.current.mutateAsync({ key: "B2", paidOn: null });
    const cancel = renderHook(() => useCancelBatch(), { wrapper });
    await cancel.result.current.mutateAsync("B3");
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/hr/payments/batches", { settlement_ids: [1, 2], execution_date: null }],
      ["/api/hr/payments/batches/B1/confirm", { paid_on: "2026-12-31" }],
      ["/api/hr/payments/batches/B2/confirm", { paid_on: null }],
      ["/api/hr/payments/batches/B3/cancel"],
    ]);
    expectInvalidatesPaymentsAndSettlements(invalidate);
  });

  it("nieudane potwierdzenie paczki nie odświeża list", async () => {
    const { wrapper, invalidate } = setup();
    apiMock.post.mockRejectedValueOnce({ response: { status: 409 } });
    const { result } = renderHook(() => useConfirmBatch(), { wrapper });
    await expect(result.current.mutateAsync({ key: "B1", paidOn: null })).rejects.toEqual({
      response: { status: 409 },
    });
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("zapis ustawień wkłada odpowiedź serwera do pamięci i odświeża płatności", async () => {
    const { wrapper, queryClient, invalidate } = setup();
    const settings: PaymentSettings = {
      payout_day: 10,
      transfer_batch: { enabled: true, format: "elixir", sender_name: "Firma Testowa sp. z o.o." },
      symfonia: {
        leave_events: {},
        export_sick_leave: false,
        overtime_event: "NG",
        work_start: "08:00",
        bonus_components: {},
        contract_kind: "UP",
        payment_form: "przelew",
      },
    };
    const fromServer = { ...settings, payout_day: 12 };
    apiMock.put.mockResolvedValueOnce({ data: fromServer });
    const { result } = renderHook(() => useSavePaymentSettings(), { wrapper });
    await result.current.mutateAsync(settings);
    expect(apiMock.put).toHaveBeenCalledWith("/api/hr/payments/settings", settings);
    expect(queryClient.getQueryData(paymentKeys.settings)).toEqual(fromServer);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["hr", "payments"] });
  });
});
