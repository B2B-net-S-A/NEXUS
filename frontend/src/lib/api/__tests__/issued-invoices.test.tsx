import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));
const filesMock = vi.hoisted(() => ({
  fetchAuthenticatedDownload: vi.fn(),
  downloadBlob: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));
vi.mock("@/lib/authenticated-files", () => filesMock);

import {
  downloadIssuedFile,
  issuedKeys,
  issuedPaths,
  sendIssued,
  useCheckIssued,
  useCreateAdvance,
  useCreateCorrection,
  useCreateDrafts,
  useCreateManual,
  useDeleteIssued,
  useDeleteTemplate,
  useImportTemplates,
  useInvalidateIssued,
  useIssueRebateCorrection,
  useIssueSettings,
  useIssuedCard,
  useIssuedList,
  useRebateCorrection,
  useRunTemplates,
  useSaveAsTemplate,
  useSaveIssueSettings,
  useSaveTemplate,
  useSendIssued,
  useSetSeriesNext,
  useTemplateSuggestions,
  useTemplates,
  useToIssue,
  useUpdateIssued,
} from "@/lib/api/issued-invoices";

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

function expectRefreshesIssuedAndInvoicing(invalidate: ReturnType<typeof setup>["invalidate"]) {
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["issued-invoices"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["client-invoicing"] });
}

async function settle(hook: () => { isSuccess: boolean }, wrapper: ReturnType<typeof setup>["wrapper"]) {
  const { result } = renderHook(hook, { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
}

const correction = { clientId: 4, year: 2026, month: 12, currency: "EUR" };

beforeEach(() => {
  for (const fn of Object.values(apiMock)) {
    fn.mockReset();
    fn.mockResolvedValue({ data: { ok: true } });
  }
  filesMock.fetchAuthenticatedDownload.mockReset();
  filesMock.downloadBlob.mockReset();
});

describe("ścieżki plików", () => {
  it("PDF, UPO i XML faktury", () => {
    expect(issuedPaths.pdf(3)).toBe("/api/finance/issued-invoices/3/pdf");
    expect(issuedPaths.upo(3)).toBe("/api/finance/issued-invoices/3/upo");
    expect(issuedPaths.xml(3)).toBe("/api/finance/issued-invoices/3/xml");
  });

  it("XML korekty rabatu ma klienta, miesiąc i walutę w zapytaniu", () => {
    expect(issuedPaths.rebateCorrectionXml(correction)).toBe(
      "/api/finance/issued-invoices/rebate-correction/xml?client_id=4&year=2026&month=12&currency=EUR",
    );
    expect(issuedKeys.rebateCorrection(correction)).toEqual([
      "issued-invoices",
      "rebate-correction",
      4,
      2026,
      12,
      "EUR",
    ]);
  });
});

describe("downloadIssuedFile", () => {
  it("nazwa z serwera, a bez niej zapasowa", async () => {
    const blob = new Blob(["%PDF"]);
    filesMock.fetchAuthenticatedDownload.mockResolvedValueOnce({ blob, filename: "FV 1/12/2026.pdf" });
    await downloadIssuedFile("/p", "faktura.pdf");
    expect(filesMock.downloadBlob).toHaveBeenLastCalledWith(blob, "FV 1/12/2026.pdf");

    filesMock.fetchAuthenticatedDownload.mockResolvedValueOnce({ blob, filename: undefined });
    await downloadIssuedFile("/p", "faktura.pdf");
    expect(filesMock.downloadBlob).toHaveBeenLastCalledWith(blob, "faktura.pdf");
    expect(filesMock.fetchAuthenticatedDownload).toHaveBeenCalledWith("/p");
  });
});

describe("zapytania", () => {
  it("ustawienia: okres „RRRR-MM” rozbity na rok i miesiąc, bez okresu brak parametrów", async () => {
    const { wrapper } = setup();
    await settle(() => useIssueSettings("2027-01"), wrapper);
    await settle(() => useIssueSettings(), wrapper);
    expect(apiMock.get.mock.calls).toEqual([
      ["/api/finance/issued-invoices/settings", { params: { year: 2027, month: 1 } }],
      ["/api/finance/issued-invoices/settings", { params: {} }],
    ]);
  });

  it("„Do wystawienia” i listy szkiców/wysłanych z okresem i bez", async () => {
    const { wrapper } = setup();
    await settle(() => useToIssue(2026, 12), wrapper);
    await settle(() => useIssuedList("drafts", "2026-12"), wrapper);
    await settle(() => useIssuedList("sent", null), wrapper);
    expect(apiMock.get.mock.calls).toEqual([
      ["/api/finance/issued-invoices/to-issue", { params: { year: 2026, month: 12 } }],
      ["/api/finance/issued-invoices", { params: { view: "drafts", year: 2026, month: 12 } }],
      ["/api/finance/issued-invoices", { params: { view: "sent" } }],
    ]);
  });

  it("karta faktury tylko dla dodatniego id", async () => {
    const { wrapper } = setup();
    renderHook(() => useIssuedCard(0), { wrapper });
    renderHook(() => useIssuedCard(Number.NaN), { wrapper });
    expect(apiMock.get).not.toHaveBeenCalled();
    await settle(() => useIssuedCard(8), wrapper);
    expect(apiMock.get).toHaveBeenCalledWith("/api/finance/issued-invoices/8");
  });

  it("szkic korekty rabatu z parametrami w adresie", async () => {
    const { wrapper } = setup();
    await settle(() => useRebateCorrection(correction), wrapper);
    expect(apiMock.get).toHaveBeenCalledWith(
      "/api/finance/issued-invoices/rebate-correction?client_id=4&year=2026&month=12&currency=EUR",
    );
  });

  it("409 przy szkicu korekty to błąd zapytania, nie pusty szkic", async () => {
    const { wrapper } = setup();
    apiMock.get.mockRejectedValueOnce({ response: { status: 409 } });
    const { result } = renderHook(() => useRebateCorrection(correction), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });

  it("szablony: rodzaj tylko gdy wybrany; podpowiedzi z okresu", async () => {
    const { wrapper } = setup();
    await settle(() => useTemplates("benefit", "2026-12"), wrapper);
    await settle(() => useTemplates(null, "2026-11"), wrapper);
    await settle(() => useTemplateSuggestions("2027-01"), wrapper);
    expect(apiMock.get.mock.calls).toEqual([
      ["/api/finance/issued-invoices/templates", { params: { year: 2026, month: 12, kind: "benefit" } }],
      ["/api/finance/issued-invoices/templates", { params: { year: 2026, month: 11 } }],
      ["/api/finance/issued-invoices/templates/suggestions", { params: { year: 2027, month: 1 } }],
    ]);
  });

  it("wyłączone zapytania nie idą do serwera", () => {
    const { wrapper } = setup();
    renderHook(() => useIssueSettings("2026-12", false), { wrapper });
    renderHook(() => useToIssue(2026, 12, false), { wrapper });
    renderHook(() => useIssuedList("sent", null, false), { wrapper });
    renderHook(() => useTemplateSuggestions("2026-12", false), { wrapper });
    expect(apiMock.get).not.toHaveBeenCalled();
  });
});

describe("mutacje", () => {
  it("wystawienie korekty rabatu: ciało w snake_case", async () => {
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useIssueRebateCorrection(), { wrapper });
    await result.current.mutateAsync(correction);
    expect(apiMock.post).toHaveBeenCalledWith("/api/finance/issued-invoices/rebate-correction", {
      client_id: 4,
      year: 2026,
      month: 12,
      currency: "EUR",
    });
    expectRefreshesIssuedAndInvoicing(invalidate);
  });

  it("numeracja serii: kod w ścieżce, nie w ciele", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useSetSeriesNext(), { wrapper });
    await result.current.mutateAsync({ code: "KORUE", year: 2027, month: 1, next_number: 1 });
    expect(apiMock.put).toHaveBeenCalledWith("/api/finance/issued-invoices/series/KORUE", {
      year: 2027,
      month: 1,
      next_number: 1,
    });
  });

  it("ustawienia, szkice, zaliczka, faktura z ręki i poprawka", async () => {
    const { wrapper, invalidate } = setup();
    const settings = renderHook(() => useSaveIssueSettings(), { wrapper });
    await settings.result.current.mutateAsync({ clients: {} } as never);
    const drafts = renderHook(() => useCreateDrafts(), { wrapper });
    await drafts.result.current.mutateAsync({ year: 2026, month: 12, keys: ["c4"], split: "person" });
    const advance = renderHook(() => useCreateAdvance(), { wrapper });
    await advance.result.current.mutateAsync({ client_id: 4, currency: "PLN", received_on: "2026-12-31" });
    const manual = renderHook(() => useCreateManual(), { wrapper });
    await manual.result.current.mutateAsync({ buyer: { name: "Firma Testowa sp. z o.o." }, currency: "USD" });
    const update = renderHook(() => useUpdateIssued(9), { wrapper });
    await update.result.current.mutateAsync({ notes: "" } as never);

    expect(apiMock.put.mock.calls).toEqual([
      ["/api/finance/issued-invoices/settings", { clients: {} }],
      ["/api/finance/issued-invoices/9", { notes: "" }],
    ]);
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/finance/issued-invoices/drafts", { year: 2026, month: 12, keys: ["c4"], split: "person" }],
      ["/api/finance/issued-invoices/advance", { client_id: 4, currency: "PLN", received_on: "2026-12-31" }],
      ["/api/finance/issued-invoices/manual", { buyer: { name: "Firma Testowa sp. z o.o." }, currency: "USD" }],
    ]);
    expectRefreshesIssuedAndInvoicing(invalidate);
  });

  it("usunięcie, wysyłka, sprawdzenie i korekta faktury", async () => {
    const { wrapper } = setup();
    const del = renderHook(() => useDeleteIssued(), { wrapper });
    await del.result.current.mutateAsync(5);
    const send = renderHook(() => useSendIssued(), { wrapper });
    await send.result.current.mutateAsync(5);
    const check = renderHook(() => useCheckIssued(), { wrapper });
    await check.result.current.mutateAsync(5);
    const corr = renderHook(() => useCreateCorrection(), { wrapper });
    await corr.result.current.mutateAsync({ id: 5, reason: "Zła cena" });
    expect(apiMock.delete).toHaveBeenCalledWith("/api/finance/issued-invoices/5");
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/finance/issued-invoices/5/send"],
      ["/api/finance/issued-invoices/5/check"],
      ["/api/finance/issued-invoices/5/correction", { reason: "Zła cena" }],
    ]);
  });

  it("odrzucona wysyłka (KSeF 5xx) nie odświeża list", async () => {
    const { wrapper, invalidate } = setup();
    apiMock.post.mockRejectedValueOnce({ response: { status: 502 } });
    const { result } = renderHook(() => useSendIssued(), { wrapper });
    await expect(result.current.mutateAsync(5)).rejects.toEqual({ response: { status: 502 } });
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("sendIssued poza hookiem i ręczne odświeżenie po serii wysyłek", async () => {
    const { wrapper, invalidate } = setup();
    apiMock.post.mockResolvedValueOnce({ data: { id: 5, status: "sent" } });
    await expect(sendIssued(5)).resolves.toEqual({ id: 5, status: "sent" });
    expect(apiMock.post).toHaveBeenCalledWith("/api/finance/issued-invoices/5/send");
    const { result } = renderHook(() => useInvalidateIssued(), { wrapper });
    result.current();
    expectRefreshesIssuedAndInvoicing(invalidate);
  });

  it("szablon: nowy POST-em, istniejący PUT-em (także id 0)", async () => {
    const { wrapper } = setup();
    const create = renderHook(() => useSaveTemplate(null), { wrapper });
    await create.result.current.mutateAsync({ name: "Abonament" } as never);
    const edit = renderHook(() => useSaveTemplate(0), { wrapper });
    await edit.result.current.mutateAsync({ active: false } as never);
    expect(apiMock.post).toHaveBeenCalledWith("/api/finance/issued-invoices/templates", { name: "Abonament" });
    expect(apiMock.put).toHaveBeenCalledWith("/api/finance/issued-invoices/templates/0", { active: false });
  });

  it("usunięcie, import, uruchomienie szablonów i zapis faktury jako szablonu", async () => {
    const { wrapper, invalidate } = setup();
    const del = renderHook(() => useDeleteTemplate(), { wrapper });
    await del.result.current.mutateAsync(2);
    const imp = renderHook(() => useImportTemplates(), { wrapper });
    await imp.result.current.mutateAsync({ year: 2026, month: 12, ksef_numbers: [] });
    const run = renderHook(() => useRunTemplates(), { wrapper });
    await run.result.current.mutateAsync({ year: 2027, month: 1, template_ids: [2, 3] });
    const asTpl = renderHook(() => useSaveAsTemplate(), { wrapper });
    await asTpl.result.current.mutateAsync(11);
    expect(apiMock.delete).toHaveBeenCalledWith("/api/finance/issued-invoices/templates/2");
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/finance/issued-invoices/templates/import", { year: 2026, month: 12, ksef_numbers: [] }],
      ["/api/finance/issued-invoices/templates/run", { year: 2027, month: 1, template_ids: [2, 3] }],
      ["/api/finance/issued-invoices/11/template"],
    ]);
    expectRefreshesIssuedAndInvoicing(invalidate);
  });
});
