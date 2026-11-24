import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import {
  type BonusInput,
  closeConflict,
  payrollKeys,
  payrollPaths,
  useApplySettlementImport,
  useApproveBonus,
  useApproveBonuses,
  useBonusClawbacks,
  useBonusDecisions,
  useBonusMode,
  useBonusRules,
  useCancelBonus,
  useCancelClawback,
  useCloseMonth,
  useConfirmVoucher,
  useContractAdminDetails,
  useContractBonuses,
  useCorrectSignedOn,
  useCreateBonus,
  useDeleteRate,
  useDoubleBonusMonth,
  useMinimumRates,
  useMyDoubleBonus,
  useMyPayroll,
  useMySettlement,
  usePayrollMonth,
  usePayrollMonths,
  usePersonPayroll,
  usePlacementOptions,
  useRefreshProposals,
  useRegisterClawback,
  useReopenMonth,
  useReportBonus,
  useSaveBonusRules,
  useSaveContractAdminDetails,
  useSaveMinimumRates,
  useSetRate,
  useSettleDoubleBonus,
  useSettlementImportPreview,
  useUpdateBonus,
} from "@/lib/api/hr-payroll";

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

type Wrapper = ReturnType<typeof setup>["wrapper"];

async function settle<T>(hook: () => { isSuccess: boolean; data?: T }, wrapper: Wrapper) {
  const { result } = renderHook(hook, { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  return result.current.data;
}

beforeEach(() => {
  for (const fn of Object.values(apiMock)) {
    fn.mockReset();
    fn.mockResolvedValue({ data: { items: [] } });
  }
});

describe("closeConflict", () => {
  it("409 z kodem: komplet pól", () => {
    const warnings = [{ code: "no_timesheet", name: "Jan Testowy" }];
    expect(
      closeConflict({
        response: {
          status: 409,
          data: { detail: { code: "WARNINGS", message: "Są ostrzeżenia", warnings, count: 2 } },
        },
      }),
    ).toEqual({ code: "WARNINGS", message: "Są ostrzeżenia", warnings, count: 2 });
  });

  it("409 z samym kodem: puste wartości domyślne", () => {
    expect(
      closeConflict({
        response: { status: 409, data: { detail: { code: "X", message: 5, warnings: "nie lista", count: "3" } } },
      }),
    ).toEqual({ code: "X", message: "", warnings: [], count: 0 });
  });

  it("count 0 zostaje zerem", () => {
    expect(
      closeConflict({ response: { status: 409, data: { detail: { code: "X", count: 0 } } } })?.count,
    ).toBe(0);
  });

  it("inne statusy, brak odpowiedzi i zwykłe błędy to nie konflikt", () => {
    expect(closeConflict({ response: { status: 422, data: { detail: { code: "X" } } } })).toBeNull();
    expect(closeConflict({ response: { status: 500 } })).toBeNull();
    expect(closeConflict(new Error("Network Error"))).toBeNull();
    expect(closeConflict(null)).toBeNull();
    expect(closeConflict(undefined)).toBeNull();
  });

  it("409 bez szczegółu w postaci obiektu z kodem to nie konflikt zamknięcia", () => {
    expect(closeConflict({ response: { status: 409 } })).toBeNull();
    expect(closeConflict({ response: { status: 409, data: { detail: "Miesiąc zamknięty" } } })).toBeNull();
    expect(closeConflict({ response: { status: 409, data: { detail: [{ code: "X" }] } } })).toBeNull();
    expect(closeConflict({ response: { status: 409, data: { detail: null } } })).toBeNull();
    expect(closeConflict({ response: { status: 409, data: { detail: { code: 1 } } } })).toBeNull();
  });
});

describe("ścieżki i klucze", () => {
  it("eksport miesiąca i klucze pod wspólnym prefiksem", () => {
    expect(payrollPaths.export(2027, 1)).toBe("/api/hr/payroll/months/2027/1/export.xlsx");
    expect(payrollKeys.settlement(2026)).toEqual(["hr", "payroll", "me", "settlement", 2026]);
    expect(payrollKeys.doubleBonus(2026, 12)).toEqual(["hr", "payroll", "double-bonus", 2026, 12]);
  });
});

describe("zapytania", () => {
  it("„Mój czas”: wypłaty, rozliczenie roku i premia 200%", async () => {
    const { wrapper } = setup();
    await settle(() => useMyPayroll(), wrapper);
    await settle(() => useMySettlement(2026), wrapper);
    await settle(() => useMyDoubleBonus(), wrapper);
    expect(apiMock.get.mock.calls).toEqual([
      ["/api/hr/payroll/me"],
      ["/api/hr/payroll/me/settlement", { params: { year: 2026 } }],
      ["/api/hr/payroll/me/double-bonus"],
    ]);
  });

  it("miesiące zwracają samo `items`, pozostałe listy też", async () => {
    const { wrapper } = setup();
    apiMock.get.mockResolvedValueOnce({ data: { items: [{ year: 2026, month: 12 }] } });
    expect(await settle(() => usePayrollMonths(), wrapper)).toEqual([{ year: 2026, month: 12 }]);
    apiMock.get.mockResolvedValueOnce({ data: { items: [{ id: 1 }] } });
    expect(await settle(() => useBonusClawbacks(), wrapper)).toEqual([{ id: 1 }]);
    apiMock.get.mockResolvedValueOnce({ data: { items: [{ id: 2 }] } });
    expect(await settle(() => useContractBonuses(5, true), wrapper)).toEqual([{ id: 2 }]);
    apiMock.get.mockResolvedValueOnce({ data: { items: [{ id: 3 }] } });
    expect(await settle(() => usePlacementOptions(true), wrapper)).toEqual([{ id: 3 }]);
    expect(apiMock.get.mock.calls.map((c) => c[0])).toEqual([
      "/api/hr/payroll/months",
      "/api/hr/payroll/clawbacks",
      "/api/hr/payroll/contracts/5/bonuses",
      "/api/hr/payroll/placement-options",
    ]);
  });

  it("miesiąc, osoba, reguły, decyzje, kontrakt, tryb premii i minima", async () => {
    const { wrapper } = setup();
    await settle(() => usePayrollMonth(2026, 12), wrapper);
    await settle(() => useDoubleBonusMonth(2027, 1), wrapper);
    await settle(() => usePersonPayroll(7), wrapper);
    await settle(() => useBonusRules(), wrapper);
    await settle(() => useBonusDecisions(true), wrapper);
    await settle(() => useContractAdminDetails(5, true), wrapper);
    await settle(() => useBonusMode(), wrapper);
    await settle(() => useMinimumRates(), wrapper);
    expect(apiMock.get.mock.calls.map((c) => c[0])).toEqual([
      "/api/hr/payroll/months/2026/12",
      "/api/hr/payroll/double-bonus/2027/1",
      "/api/hr/payroll/people/7",
      "/api/hr/payroll/rules",
      "/api/hr/payroll/decisions",
      "/api/hr/payroll/contracts/5/admin-details",
      "/api/hr/payroll/bonus-mode",
      "/api/hr/payroll/settings/minimum-rates",
    ]);
  });

  it("bez poprawnego roku, miesiąca albo osoby nie pyta serwera", () => {
    const { wrapper } = setup();
    renderHook(() => usePayrollMonth(Number.NaN, 12), { wrapper });
    renderHook(() => usePayrollMonth(2026, Number.NaN), { wrapper });
    renderHook(() => useDoubleBonusMonth(2026, Number.NaN), { wrapper });
    renderHook(() => useDoubleBonusMonth(2026, 12, false), { wrapper });
    renderHook(() => usePersonPayroll(0), { wrapper });
    renderHook(() => usePersonPayroll(-3), { wrapper });
    renderHook(() => usePersonPayroll(7, false), { wrapper });
    renderHook(() => useMyPayroll(false), { wrapper });
    renderHook(() => useMySettlement(2026, false), { wrapper });
    renderHook(() => useMyDoubleBonus(false), { wrapper });
    renderHook(() => useBonusRules(false), { wrapper });
    renderHook(() => useBonusDecisions(false), { wrapper });
    renderHook(() => useContractBonuses(5, false), { wrapper });
    renderHook(() => useContractAdminDetails(5, false), { wrapper });
    renderHook(() => usePlacementOptions(false), { wrapper });
    renderHook(() => useBonusClawbacks(false), { wrapper });
    renderHook(() => useMinimumRates(false), { wrapper });
    expect(apiMock.get).not.toHaveBeenCalled();
  });
});

describe("mutacje premii i stawek", () => {
  const bonus: BonusInput = {
    recipient_user_id: 3,
    amount: "0.00",
    currency: "EUR",
    category: "custom",
    period_year: 2026,
    period_month: 12,
    description: null,
    contract_id: null,
  };

  it("stawka i jej usunięcie", async () => {
    const { wrapper, invalidate } = setup();
    const set = renderHook(() => useSetRate(7), { wrapper });
    const rate = { hourly_rate: "100.00", currency: "PLN" as const, effective_from: "2027-01-01" };
    await set.result.current.mutateAsync(rate);
    const del = renderHook(() => useDeleteRate(), { wrapper });
    await expect(del.result.current.mutateAsync(4)).resolves.toBeUndefined();
    expect(apiMock.post).toHaveBeenCalledWith("/api/hr/payroll/people/7/rates", rate);
    expect(apiMock.delete).toHaveBeenCalledWith("/api/hr/payroll/rates/4");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: payrollKeys.all });
  });

  it("premia: nowa, poprawka, zatwierdzenie pojedyncze i zbiorcze", async () => {
    const { wrapper } = setup();
    const create = renderHook(() => useCreateBonus(), { wrapper });
    await create.result.current.mutateAsync(bonus);
    const update = renderHook(() => useUpdateBonus(), { wrapper });
    await update.result.current.mutateAsync({ id: 9, patch: { amount: "-50.00", change_reason: "Korekta" } });
    const approve = renderHook(() => useApproveBonus(), { wrapper });
    await approve.result.current.mutateAsync(9);
    const batch = renderHook(() => useApproveBonuses(), { wrapper });
    await batch.result.current.mutateAsync([9, 10]);
    expect(apiMock.patch).toHaveBeenCalledWith("/api/hr/payroll/bonuses/9", {
      amount: "-50.00",
      change_reason: "Korekta",
    });
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/hr/payroll/bonuses", bonus],
      ["/api/hr/payroll/bonuses/9/approve"],
      ["/api/hr/payroll/bonuses/approve-batch", { ids: [9, 10] }],
    ]);
  });

  it("zatwierdzenie zbiorcze „wszystko albo nic”: odmowa nie odświeża list", async () => {
    const { wrapper, invalidate } = setup();
    apiMock.post.mockRejectedValueOnce({ response: { status: 409 } });
    const { result } = renderHook(() => useApproveBonuses(), { wrapper });
    await expect(result.current.mutateAsync([1, 2])).rejects.toEqual({ response: { status: 409 } });
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("anulowanie premii: brak notatki to null", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useCancelBonus(), { wrapper });
    await result.current.mutateAsync({ id: 9 });
    await result.current.mutateAsync({ id: 9, note: "Dubel" });
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/hr/payroll/bonuses/9/cancel", { note: null }],
      ["/api/hr/payroll/bonuses/9/cancel", { note: "Dubel" }],
    ]);
  });

  it("zgłoszenie premii nie odświeża niczego i nie zwraca treści", async () => {
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useReportBonus(), { wrapper });
    await expect(result.current.mutateAsync({ id: 9, note: "Zła kwota" })).resolves.toBeUndefined();
    expect(apiMock.post).toHaveBeenCalledWith("/api/hr/payroll/bonuses/9/report", { note: "Zła kwota" });
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("zwrot z gwarancji: zapis i anulowanie, voucher, odświeżenie propozycji", async () => {
    const { wrapper } = setup();
    const reg = renderHook(() => useRegisterClawback(), { wrapper });
    await reg.result.current.mutateAsync({ bonusId: 9, note: "Koniec kontraktu" });
    const cancel = renderHook(() => useCancelClawback(), { wrapper });
    await cancel.result.current.mutateAsync({ id: 2, note: "Cofnięty koniec" });
    const voucher = renderHook(() => useConfirmVoucher(), { wrapper });
    await voucher.result.current.mutateAsync(6);
    const refresh = renderHook(() => useRefreshProposals(), { wrapper });
    await refresh.result.current.mutateAsync();
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/hr/payroll/bonuses/9/clawback", { note: "Koniec kontraktu" }],
      ["/api/hr/payroll/clawbacks/2/cancel", { note: "Cofnięty koniec" }],
      ["/api/hr/payroll/vouchers/6/confirm"],
      ["/api/hr/payroll/proposals/refresh"],
    ]);
  });

  it("premia 200%: rozliczenie miesiąca i poprawka dnia podpisu", async () => {
    const { wrapper } = setup();
    const settleMonth = renderHook(() => useSettleDoubleBonus(2026, 12), { wrapper });
    await settleMonth.result.current.mutateAsync();
    const signed = renderHook(() => useCorrectSignedOn(), { wrapper });
    await signed.result.current.mutateAsync({
      generatedContractId: 15,
      signedOn: "2026-12-31",
      reason: "Podpis odręczny",
    });
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/hr/payroll/double-bonus/2026/12/settle"],
      [
        "/api/hr/payroll/double-bonus/agreements/15/signed-on",
        { signed_on: "2026-12-31", reason: "Podpis odręczny" },
      ],
    ]);
  });

  it("szczegóły administracyjne kontraktu, reguły i minima stawek", async () => {
    const { wrapper } = setup();
    const admin = renderHook(() => useSaveContractAdminDetails(5), { wrapper });
    await admin.result.current.mutateAsync({ replacement: false } as never);
    const rules = renderHook(() => useSaveBonusRules(), { wrapper });
    await rules.result.current.mutateAsync({ client_ids: [] } as never);
    const minima = renderHook(() => useSaveMinimumRates(), { wrapper });
    await minima.result.current.mutateAsync({ "2027": "0.00" });
    expect(apiMock.put.mock.calls).toEqual([
      ["/api/hr/payroll/contracts/5/admin-details", { replacement: false }],
      ["/api/hr/payroll/rules", { client_ids: [] }],
      ["/api/hr/payroll/settings/minimum-rates", { rates: { "2027": "0.00" } }],
    ]);
  });
});

describe("import arkusza rozliczeń", () => {
  it("podgląd wysyła plik bez odświeżania, zapis wierszy odświeża płace", async () => {
    const { wrapper, invalidate } = setup();
    const preview = renderHook(() => useSettlementImportPreview(2026, 12), { wrapper });
    const file = new File(["x"], "delivery.xlsx");
    await preview.result.current.mutateAsync(file);
    const [url, form, config] = apiMock.post.mock.calls[0];
    expect(url).toBe("/api/hr/payroll/months/2026/12/settlement-import/preview");
    expect((form as FormData).get("file")).toBe(file);
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });
    expect(invalidate).not.toHaveBeenCalled();

    const apply = renderHook(() => useApplySettlementImport(2026, 12), { wrapper });
    await apply.result.current.mutateAsync([]);
    expect(apiMock.post).toHaveBeenLastCalledWith("/api/hr/payroll/months/2026/12/settlement-import", {
      rows: [],
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: payrollKeys.all });
  });
});

describe("zamknięcie i otwarcie miesiąca", () => {
  it("zamknięcie odświeża płace, rozliczenia i przelewy", async () => {
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useCloseMonth(2026, 12), { wrapper });
    await result.current.mutateAsync(false);
    expect(apiMock.post).toHaveBeenCalledWith("/api/hr/payroll/months/2026/12/close", {
      acknowledge_warnings: false,
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["hr", "payroll"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["hr", "settlements"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["hr", "payments"] });
  });

  it("409 z ostrzeżeniami przy zamknięciu da się odczytać przez closeConflict", async () => {
    const { wrapper, invalidate } = setup();
    const error = {
      response: { status: 409, data: { detail: { code: "WARNINGS", message: "Brak czasu pracy", count: 1 } } },
    };
    apiMock.post.mockRejectedValueOnce(error);
    const { result } = renderHook(() => useCloseMonth(2026, 12), { wrapper });
    const caught = await result.current.mutateAsync(false).catch((e: unknown) => e);
    expect(closeConflict(caught)).toEqual({ code: "WARNINGS", message: "Brak czasu pracy", warnings: [], count: 1 });
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("ponowne otwarcie z powodem", async () => {
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useReopenMonth(2027, 1), { wrapper });
    await result.current.mutateAsync("Brakująca premia");
    expect(apiMock.post).toHaveBeenCalledWith("/api/hr/payroll/months/2027/1/reopen", {
      reason: "Brakująca premia",
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["hr", "payments"] });
  });
});
