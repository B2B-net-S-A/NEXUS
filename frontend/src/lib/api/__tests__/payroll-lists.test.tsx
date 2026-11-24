import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
}));
const filesMock = vi.hoisted(() => ({
  fetchAuthenticatedDownload: vi.fn(),
  downloadBlob: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));
vi.mock("@/lib/authenticated-files", () => filesMock);

import {
  type CompanyInput,
  type ParametersOverview,
  type PayrollCompany,
  downloadPayrollFile,
  payrollListKeys,
  payrollPaths,
  subjectKey,
  useApproveList,
  useCancelList,
  useComputeList,
  useConfirmParameters,
  useMarkPaid,
  usePayrollMonth,
  usePayrollParameters,
  usePayrollPeople,
  usePersonData,
  usePit11,
  useRegistrations,
  useSaveCompany,
  useSaveParameters,
  useSavePersonData,
  useSetGrossInput,
  useTransfersFile,
  useTransfersPlan,
  useWithdrawParameters,
} from "@/lib/api/payroll-lists";

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

const company = { name: "Firma Testowa sp. z o.o." } as unknown as PayrollCompany;

beforeEach(() => {
  for (const fn of Object.values(apiMock)) {
    fn.mockReset();
    fn.mockResolvedValue({ data: { year: 2026, month: 12 } });
  }
  filesMock.fetchAuthenticatedDownload.mockReset();
  filesMock.downloadBlob.mockReset();
});

describe("subjectKey i ścieżki", () => {
  it("konto to „u<id>”, kandydat „c<id>”", () => {
    expect(subjectKey({ userId: 7 })).toBe("u7");
    expect(subjectKey({ candidateId: 9 })).toBe("c9");
    expect(subjectKey({ userId: 0 })).toBe("u0");
  });

  it("paski: cała lista albo jedna pozycja (także id 0)", () => {
    expect(payrollPaths.payslips(5)).toBe("/api/hr/payroll-lists/lists/5/payslips.pdf");
    expect(payrollPaths.payslips(5, 0)).toBe("/api/hr/payroll-lists/lists/5/payslips.pdf?line_id=0");
    expect(payrollPaths.payslips(5, 12)).toBe("/api/hr/payroll-lists/lists/5/payslips.pdf?line_id=12");
  });

  it("KEDU z „RRRR-MM”: miesiąc bez zera wiodącego, grudzień i styczeń", () => {
    expect(payrollPaths.kedu("2026-12")).toBe("/api/hr/payroll-lists/declarations/2026/12/kedu.xml");
    expect(payrollPaths.kedu("2027-01")).toBe("/api/hr/payroll-lists/declarations/2027/1/kedu.xml");
  });

  it("pliki roczne, plik przelewów i zgłoszenia w zakresie dat", () => {
    expect(payrollPaths.year(2026, "pit-11.zip")).toBe("/api/hr/payroll-lists/years/2026/pit-11.zip");
    expect(payrollPaths.transfersFile(3)).toBe("/api/hr/payroll-lists/lists/3/transfers/file");
    expect(payrollPaths.registrations("2026-12-01", "2027-01-31")).toBe(
      "/api/hr/payroll-lists/registrations.xml?date_from=2026-12-01&date_to=2027-01-31",
    );
  });
});

describe("downloadPayrollFile", () => {
  it("GET bez opcji, nazwa z serwera", async () => {
    const blob = new Blob(["pdf"]);
    filesMock.fetchAuthenticatedDownload.mockResolvedValueOnce({ blob, filename: "paski.pdf" });
    await downloadPayrollFile("/x", "zapas.pdf");
    expect(filesMock.fetchAuthenticatedDownload).toHaveBeenCalledWith("/x", undefined);
    expect(filesMock.downloadBlob).toHaveBeenCalledWith(blob, "paski.pdf");
  });

  it("POST z pustym ciałem; bez nazwy z serwera nazwa zapasowa", async () => {
    const blob = new Blob(["csv"]);
    filesMock.fetchAuthenticatedDownload.mockResolvedValueOnce({ blob, filename: null });
    await downloadPayrollFile("/y", "przelewy.csv", "POST");
    expect(filesMock.fetchAuthenticatedDownload).toHaveBeenCalledWith("/y", { method: "POST", body: {} });
    expect(filesMock.downloadBlob).toHaveBeenCalledWith(blob, "przelewy.csv");
  });
});

describe("zapytania", () => {
  it("miesiąc, parametry, zgłoszenia, PIT-11 i osoby czytają swoje trasy", async () => {
    const { wrapper } = setup();
    for (const hook of [
      () => usePayrollMonth(2027, 1),
      () => usePayrollParameters(),
      () => useRegistrations("2026-12-01", "2026-12-31"),
      () => usePit11(2026),
      () => useTransfersPlan(4),
    ]) {
      const { result } = renderHook(() => hook(), { wrapper });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
    }
    expect(apiMock.get.mock.calls).toEqual([
      ["/api/hr/payroll-lists/months/2027/1"],
      ["/api/hr/payroll-lists/parameters"],
      ["/api/hr/payroll-lists/registrations", { params: { date_from: "2026-12-01", date_to: "2026-12-31" } }],
      ["/api/hr/payroll-lists/years/2026/pit-11"],
      ["/api/hr/payroll-lists/lists/4/transfers"],
    ]);
  });

  it("lista osób zwraca samo `people`", async () => {
    const { wrapper } = setup();
    apiMock.get.mockResolvedValueOnce({ data: { people: [{ subject: "u1" }] } });
    const { result } = renderHook(() => usePayrollPeople(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([{ subject: "u1" }]);
    expect(apiMock.get).toHaveBeenCalledWith("/api/hr/payroll-lists/people");
  });

  it("dane osoby: konto i kandydat mają osobne trasy", async () => {
    const { wrapper } = setup();
    const u = renderHook(() => usePersonData({ userId: 3 }), { wrapper });
    await waitFor(() => expect(u.result.current.isSuccess).toBe(true));
    const c = renderHook(() => usePersonData({ candidateId: 8 }), { wrapper });
    await waitFor(() => expect(c.result.current.isSuccess).toBe(true));
    expect(apiMock.get.mock.calls.map((x) => x[0])).toEqual([
      "/api/hr/payroll-lists/people/users/3",
      "/api/hr/payroll-lists/people/candidates/8",
    ]);
  });

  it("bez osoby, bez listy albo wyłączone — nie pyta serwera", () => {
    const { wrapper } = setup();
    renderHook(() => usePersonData(null), { wrapper });
    renderHook(() => usePersonData({ userId: 3 }, false), { wrapper });
    renderHook(() => useTransfersPlan(null), { wrapper });
    renderHook(() => useTransfersPlan(4, false), { wrapper });
    renderHook(() => usePayrollMonth(2026, 12, false), { wrapper });
    renderHook(() => usePayrollParameters(false), { wrapper });
    renderHook(() => useRegistrations("a", "b", false), { wrapper });
    renderHook(() => usePit11(2026, false), { wrapper });
    renderHook(() => usePayrollPeople(false), { wrapper });
    expect(apiMock.get).not.toHaveBeenCalled();
  });
});

describe("akcje listy miesiąca", () => {
  it("przeliczenie: pusta data wypłaty nie idzie do serwera", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useComputeList(), { wrapper });
    await result.current.mutateAsync({ year: 2026, month: 12, payDate: "" });
    await result.current.mutateAsync({ year: 2026, month: 12, payDate: null });
    await result.current.mutateAsync({ year: 2026, month: 12, payDate: "2027-01-10" });
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/hr/payroll-lists/months/2026/12/compute", { pay_date: undefined }],
      ["/api/hr/payroll-lists/months/2026/12/compute", { pay_date: undefined }],
      ["/api/hr/payroll-lists/months/2026/12/compute", { pay_date: "2027-01-10" }],
    ]);
  });

  it("odpowiedź wpisuje się pod miesiącem z odpowiedzi, nie z zapytania", async () => {
    const { wrapper, queryClient, invalidate } = setup();
    // Lista z grudnia zatwierdzona — serwer odpowiada stanem grudnia.
    apiMock.post.mockResolvedValueOnce({ data: { year: 2026, month: 12, status: "approved" } });
    const { result } = renderHook(() => useApproveList(), { wrapper });
    await result.current.mutateAsync(15);
    expect(apiMock.post).toHaveBeenCalledWith("/api/hr/payroll-lists/lists/15/approve");
    expect(queryClient.getQueryData(payrollListKeys.month(2026, 12))).toEqual({
      year: 2026,
      month: 12,
      status: "approved",
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["payroll-lists", "transfers"] });
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: payrollListKeys.months });
  });

  it("wpis brutto, anulowanie i wypłata", async () => {
    const { wrapper } = setup();
    const gross = renderHook(() => useSetGrossInput(), { wrapper });
    const body = { user_id: 1, amount: null } as never;
    await gross.result.current.mutateAsync({ year: 2027, month: 1, body });
    const cancel = renderHook(() => useCancelList(), { wrapper });
    await cancel.result.current.mutateAsync({ listId: 2, reason: "Błędna stawka" });
    const paid = renderHook(() => useMarkPaid(), { wrapper });
    await paid.result.current.mutateAsync(2);
    expect(apiMock.put).toHaveBeenCalledWith("/api/hr/payroll-lists/months/2027/1/inputs", body);
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/hr/payroll-lists/lists/2/cancel", { reason: "Błędna stawka" }],
      ["/api/hr/payroll-lists/lists/2/paid"],
    ]);
  });

  it("odmowa serwera odświeża miesiąc, żeby ekran pokazał powód", async () => {
    const { wrapper, invalidate } = setup();
    apiMock.post.mockRejectedValueOnce({ response: { status: 409 } });
    const { result } = renderHook(() => useApproveList(), { wrapper });
    await expect(result.current.mutateAsync(15)).rejects.toEqual({ response: { status: 409 } });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: payrollListKeys.months });
  });

  it("plik przelewów: POST, a potem odświeżenie miesiąca i planu także po błędzie", async () => {
    const { wrapper, invalidate } = setup();
    filesMock.fetchAuthenticatedDownload.mockResolvedValueOnce({ blob: new Blob([""]), filename: null });
    const { result } = renderHook(() => useTransfersFile(), { wrapper });
    await result.current.mutateAsync({ listId: 6, fallbackName: "przelewy-2026-12.csv" });
    expect(filesMock.fetchAuthenticatedDownload).toHaveBeenCalledWith(
      "/api/hr/payroll-lists/lists/6/transfers/file",
      { method: "POST", body: {} },
    );
    expect(filesMock.downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "przelewy-2026-12.csv");

    invalidate.mockClear();
    filesMock.fetchAuthenticatedDownload.mockRejectedValueOnce(new Error("Plik niedostępny"));
    await expect(result.current.mutateAsync({ listId: 6, fallbackName: "x" })).rejects.toThrow();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: payrollListKeys.months });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["payroll-lists", "transfers"] });
  });
});

describe("parametry i płatnik", () => {
  it("historia bez płatnika zachowuje płatnika z poprzedniego odczytu", async () => {
    const { wrapper, queryClient, invalidate } = setup();
    queryClient.setQueryData(payrollListKeys.parameters, { versions: ["v1"], company });
    apiMock.post.mockResolvedValueOnce({ data: { versions: ["v1", "v2"], company: null } });
    const { result } = renderHook(() => useSaveParameters(), { wrapper });
    const body = { effective_from: "2027-01-01", params: { min_wage: "0.00" }, note: null };
    await result.current.mutateAsync(body);
    expect(apiMock.post).toHaveBeenCalledWith("/api/hr/payroll-lists/parameters", body);
    expect(queryClient.getQueryData(payrollListKeys.parameters)).toEqual({
      versions: ["v1", "v2"],
      company,
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: payrollListKeys.months });
  });

  it("płatnik w odpowiedzi wygrywa z zapamiętanym", async () => {
    const { wrapper, queryClient } = setup();
    const fresh = { name: "Inna Firma Testowa" };
    queryClient.setQueryData(payrollListKeys.parameters, { company });
    apiMock.post.mockResolvedValueOnce({ data: { versions: [], company: fresh } });
    const { result } = renderHook(() => useConfirmParameters(), { wrapper });
    await result.current.mutateAsync(4);
    expect(apiMock.post).toHaveBeenCalledWith("/api/hr/payroll-lists/parameters/4/confirm");
    expect(queryClient.getQueryData<ParametersOverview>(payrollListKeys.parameters)?.company).toEqual(fresh);
  });

  it("wycofanie bez wcześniejszego odczytu: płatnik zostaje pusty", async () => {
    const { wrapper, queryClient } = setup();
    apiMock.post.mockResolvedValueOnce({ data: { versions: [] } });
    const { result } = renderHook(() => useWithdrawParameters(), { wrapper });
    await result.current.mutateAsync(4);
    expect(apiMock.post).toHaveBeenCalledWith("/api/hr/payroll-lists/parameters/4/withdraw");
    expect(queryClient.getQueryData(payrollListKeys.parameters)).toEqual({
      versions: [],
      company: undefined,
    });
  });

  it("zapis płatnika podmienia go w parametrach; bez parametrów w pamięci nic nie tworzy", async () => {
    const { wrapper, queryClient } = setup();
    apiMock.put.mockResolvedValue({ data: company });
    const { result } = renderHook(() => useSaveCompany(), { wrapper });
    const input = { name: "Firma Testowa sp. z o.o." } as unknown as CompanyInput;
    await result.current.mutateAsync(input);
    expect(apiMock.put).toHaveBeenCalledWith("/api/hr/payroll-lists/company", input);
    expect(queryClient.getQueryData(payrollListKeys.parameters)).toBeUndefined();

    queryClient.setQueryData(payrollListKeys.parameters, { versions: ["v1"], company: null });
    await result.current.mutateAsync(input);
    expect(queryClient.getQueryData(payrollListKeys.parameters)).toEqual({ versions: ["v1"], company });
  });
});

describe("dane osoby — zapis", () => {
  it("zapis kandydata trafia w jego trasę i pamięć pod „c<id>”", async () => {
    const { wrapper, queryClient, invalidate } = setup();
    apiMock.put.mockResolvedValueOnce({ data: { full_name: "Anna Przykładowa" } });
    const { result } = renderHook(() => useSavePersonData({ candidateId: 8 }), { wrapper });
    await result.current.mutateAsync({ expected_version: 1, pit2: 0 });
    expect(apiMock.put).toHaveBeenCalledWith("/api/hr/payroll-lists/people/candidates/8", { expected_version: 1, pit2: 0 });
    expect(queryClient.getQueryData(payrollListKeys.person("c8"))).toEqual({ full_name: "Anna Przykładowa" });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: payrollListKeys.people });
  });

  it("zapis konta trafia pod „u<id>”", async () => {
    const { wrapper, queryClient } = setup();
    apiMock.put.mockResolvedValueOnce({ data: { full_name: "Jan Testowy" } });
    const { result } = renderHook(() => useSavePersonData({ userId: 3 }), { wrapper });
    await result.current.mutateAsync({ expected_version: 2, pit2: 12 });
    expect(apiMock.put).toHaveBeenCalledWith("/api/hr/payroll-lists/people/users/3", { expected_version: 2, pit2: 12 });
    expect(queryClient.getQueryData(payrollListKeys.person("u3"))).toEqual({ full_name: "Jan Testowy" });
  });
});
