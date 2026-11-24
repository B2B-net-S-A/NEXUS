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
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import {
  fetchAcceptancePackage,
  fetchAttachmentsZip,
  fetchClientDocument,
  fetchClientDocumentFile,
  fetchContractKcp,
  fetchExtraDocument,
  fetchKesuPackage,
  fetchSettlementDocument,
  settlementKeys,
  useAcceptBatch,
  useAcceptByClient,
  useAcceptSettlement,
  useAddIntegrationCost,
  useAddSettlementExtra,
  useClientAcceptance,
  useClientDocuments,
  useClientInvoiceMonth,
  useClientRules,
  useCopyClientRules,
  useDecideIntegrationCost,
  useDecideSettlementExtra,
  useDeliverySettlements,
  useEstimates,
  useIntegrationCosts,
  useMarkAcceptanceSent,
  useMonthCloseOverview,
  useNeedsFixSettlement,
  useNipDecision,
  usePanelPreview,
  usePayOnMail,
  useSaveClientRules,
  useSetSettlementMd,
  useSetSettlementsModule,
  useSettlementClients,
  useSettlementDetail,
  useSettlementMonth,
  useSettlementsModule,
  useSettlementsStart,
  useTeamMonth,
  useUploadAcceptanceReply,
  useUploadExtraDocument,
  useUploadSignedDocument,
  useWithdrawIntegrationCost,
} from "@/lib/api/client-settlements";

const BASE = "/api/finance/settlements";

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

async function settle(hook: () => { isSuccess: boolean }, wrapper: Wrapper) {
  const { result } = renderHook(hook, { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
}

const refreshAll = { queryKey: ["client-settlements"] };

beforeEach(() => {
  for (const fn of Object.values(apiMock)) {
    fn.mockReset();
    fn.mockResolvedValue({ data: { ok: true } });
  }
});

describe("settlementKeys", () => {
  it("karta osoby domyślnie dla RCP faktycznego; plan ma osobny klucz", () => {
    expect(settlementKeys.detail(5, "2026-12")).toEqual(["client-settlements", "detail", 5, "2026-12", "actual"]);
    expect(settlementKeys.detail(5, "2026-12", "estimate")).toEqual([
      "client-settlements",
      "detail",
      5,
      "2026-12",
      "estimate",
    ]);
  });

  it("wszystkie klucze siedzą pod „client-settlements” (jedno odświeżenie łapie każdy)", () => {
    const keys = [
      settlementKeys.module,
      settlementKeys.start,
      settlementKeys.preview(1),
      settlementKeys.clients,
      settlementKeys.overview("2027-01"),
      settlementKeys.month(1, "2027-01"),
      settlementKeys.clientInvoice(1, "2027-01"),
      settlementKeys.estimates(1, "2027-01"),
      settlementKeys.clientDocuments(1, "2027-01"),
      settlementKeys.clientAcceptance(1, "2027-01"),
      settlementKeys.rules(1, "2027-01"),
      settlementKeys.integration(1, "2027-01"),
      settlementKeys.delivery(1, "2027-01"),
    ];
    for (const key of keys) expect(key[0]).toBe("client-settlements");
  });
});

describe("zapytania", () => {
  it("moduł, start, klienci, przegląd miesiąca i biuro", async () => {
    const { wrapper } = setup();
    await settle(() => useSettlementsModule(), wrapper);
    await settle(() => useSettlementsStart(true), wrapper);
    await settle(() => useSettlementClients(), wrapper);
    await settle(() => useMonthCloseOverview("2026-12"), wrapper);
    await settle(() => useTeamMonth("2027-01"), wrapper);
    expect(apiMock.get.mock.calls).toEqual([
      [`${BASE}/module`],
      [`${BASE}/start`],
      [`${BASE}/clients`],
      [`${BASE}/overview`, { params: { month: "2026-12" } }],
      [`${BASE}/team`, { params: { month: "2027-01" } }],
    ]);
  });

  it("widoki klienta w miesiącu przekazują klienta i miesiąc", async () => {
    const { wrapper } = setup();
    await settle(() => useSettlementMonth(3, "2026-12"), wrapper);
    await settle(() => useClientInvoiceMonth(3, "2026-12"), wrapper);
    await settle(() => useEstimates(3, "2026-12"), wrapper);
    await settle(() => useClientDocuments(3, "2026-12"), wrapper);
    await settle(() => useClientAcceptance(3, "2026-12"), wrapper);
    await settle(() => useClientRules(3, "2027-01"), wrapper);
    const params = { params: { client_id: 3, month: "2026-12" } };
    expect(apiMock.get.mock.calls).toEqual([
      [BASE, params],
      [`${BASE}/client-invoice`, params],
      [`${BASE}/estimates`, params],
      [`${BASE}/client-documents`, params],
      [`${BASE}/client-acceptance`, params],
      [`${BASE}/rules/3`, { params: { month: "2027-01" } }],
    ]);
  });

  it("karta osoby: domyślnie RCP faktyczne, na żądanie plan", async () => {
    const { wrapper } = setup();
    await settle(() => useSettlementDetail(8, "2026-12"), wrapper);
    await settle(() => useSettlementDetail(8, "2026-12", "estimate"), wrapper);
    expect(apiMock.get.mock.calls).toEqual([
      [`${BASE}/contract/8`, { params: { month: "2026-12", kind: "actual" } }],
      [`${BASE}/contract/8`, { params: { month: "2026-12", kind: "estimate" } }],
    ]);
  });

  it("podgląd panelu, koszty integracji i rozliczenia Delivery Leada", async () => {
    const { wrapper } = setup();
    await settle(() => usePanelPreview(8), wrapper);
    await settle(() => useIntegrationCosts(8, "2026-12"), wrapper);
    await settle(() => useDeliverySettlements(3, "2026-12"), wrapper);
    expect(apiMock.get.mock.calls).toEqual([
      [`${BASE}/contract/8/panel-preview`],
      [`${BASE}/contract/8/integration-costs`, { params: { month: "2026-12" } }],
      ["/api/my-clients/3/settlements", { params: { month: "2026-12" } }],
    ]);
  });

  it("bez klienta albo kontraktu (null) i wyłączone — nie pyta serwera", () => {
    const { wrapper } = setup();
    renderHook(() => useSettlementsModule(false), { wrapper });
    renderHook(() => useSettlementsStart(false), { wrapper });
    renderHook(() => usePanelPreview(null), { wrapper });
    renderHook(() => useSettlementMonth(null, "2026-12"), { wrapper });
    renderHook(() => useSettlementDetail(null, "2026-12"), { wrapper });
    renderHook(() => useClientInvoiceMonth(null, "2026-12"), { wrapper });
    renderHook(() => useEstimates(null, "2026-12"), { wrapper });
    renderHook(() => useClientDocuments(null, "2026-12"), { wrapper });
    renderHook(() => useClientAcceptance(null, "2026-12"), { wrapper });
    renderHook(() => useClientRules(null, "2026-12"), { wrapper });
    renderHook(() => useIntegrationCosts(null, "2026-12"), { wrapper });
    renderHook(() => useDeliverySettlements(3, "2026-12", false), { wrapper });
    expect(apiMock.get).not.toHaveBeenCalled();
  });

  it("klient o id 0 to wciąż klient (warunek `!= null`, nie prawdziwość)", async () => {
    const { wrapper } = setup();
    await settle(() => useSettlementMonth(0, "2026-12"), wrapper);
    expect(apiMock.get).toHaveBeenCalledWith(BASE, { params: { client_id: 0, month: "2026-12" } });
  });

  it("403 przy biurze to błąd od razu, bez ponawiania", async () => {
    const queryClient = new QueryClient(); // domyślnie zapytania ponawiają — hook to wyłącza
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    apiMock.get.mockRejectedValue({ response: { status: 403 } });
    const { result } = renderHook(() => useTeamMonth("2026-12"), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(apiMock.get).toHaveBeenCalledTimes(1);
    expect(result.current.data).toBeUndefined();
  });
});

describe("pobieranie plików (blob)", () => {
  const blob = new Blob(["zip"]);
  beforeEach(() => apiMock.get.mockResolvedValue({ data: blob }));

  it("załączniki faktury: domyślnie wszystkie, `issued_only` tylko gdy prawda", async () => {
    await expect(fetchAttachmentsZip(3, "2026-12")).resolves.toBe(blob);
    await fetchAttachmentsZip(3, "2026-12", { contractId: 8, issuedOnly: false });
    await fetchAttachmentsZip(3, "2026-12", { issuedOnly: true });
    expect(apiMock.get.mock.calls.map((c) => c[1])).toEqual([
      { params: { client_id: 3, month: "2026-12", contract_id: undefined, issued_only: undefined }, responseType: "blob" },
      { params: { client_id: 3, month: "2026-12", contract_id: 8, issued_only: undefined }, responseType: "blob" },
      { params: { client_id: 3, month: "2026-12", contract_id: undefined, issued_only: true }, responseType: "blob" },
    ]);
    expect(apiMock.get.mock.calls[0][0]).toBe(`${BASE}/client-invoice/attachments`);
  });

  it("dokument klienta po projekcie albo po rodzaju z podpisującym", async () => {
    await fetchClientDocument(3, "2026-12", "Projekt Testowy");
    await fetchClientDocumentFile(3, "2026-12", "protocol");
    await fetchClientDocumentFile(3, "2026-12", "sheet", "Anna Przykładowa");
    expect(apiMock.get.mock.calls).toEqual([
      [`${BASE}/client-documents/file`, { params: { client_id: 3, month: "2026-12", project: "Projekt Testowy" }, responseType: "blob" }],
      [`${BASE}/client-documents/file`, { params: { client_id: 3, month: "2026-12", kind: "protocol", signer: undefined }, responseType: "blob" }],
      [`${BASE}/client-documents/file`, { params: { client_id: 3, month: "2026-12", kind: "sheet", signer: "Anna Przykładowa" }, responseType: "blob" }],
    ]);
  });

  it("dokumenty kontraktu: plik, paczka KEŚU, KCP, dokument dodatku i paczka akceptacji", async () => {
    await fetchSettlementDocument(8, 40);
    await fetchKesuPackage(8, "2026-12");
    await fetchContractKcp(8, "2027-01");
    await fetchExtraDocument(8, 2, 41);
    await fetchAcceptancePackage(3, "2026-12");
    expect(apiMock.get.mock.calls).toEqual([
      [`${BASE}/contract/8/documents/40`, { responseType: "blob" }],
      [`${BASE}/contract/8/kesu/package`, { params: { month: "2026-12" }, responseType: "blob" }],
      [`${BASE}/contract/8/kcp`, { params: { month: "2027-01" }, responseType: "blob" }],
      [`${BASE}/contract/8/extras/2/documents/41`, { responseType: "blob" }],
      [`${BASE}/client-acceptance/package`, { params: { client_id: 3, month: "2026-12" }, responseType: "blob" }],
    ]);
  });

  it("brak pliku (404) przechodzi do wywołującego", async () => {
    const error = { response: { status: 404 } };
    apiMock.get.mockRejectedValueOnce(error);
    await expect(fetchKesuPackage(8, "2026-12")).rejects.toBe(error);
  });
});

describe("moduł", () => {
  it("włączenie modułu odświeża moduł i start", async () => {
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useSetSettlementsModule(), { wrapper });
    await result.current.mutateAsync(false);
    expect(apiMock.put).toHaveBeenCalledWith(`${BASE}/module`, { enabled: false });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: settlementKeys.module });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: settlementKeys.start });
  });
});

describe("decyzje na karcie osoby", () => {
  it("przyjęcie, MD i odesłanie do poprawy niosą miesiąc i rodzaj w parametrach", async () => {
    const { wrapper, invalidate } = setup();
    const accept = renderHook(() => useAcceptSettlement("2026-12"), { wrapper });
    await accept.result.current.mutateAsync(8);
    const md = renderHook(() => useSetSettlementMd("2026-12", "estimate"), { wrapper });
    await md.result.current.mutateAsync({ contractId: 8, mdRegular: "0", mdExtra: null });
    const fix = renderHook(() => useNeedsFixSettlement("2027-01"), { wrapper });
    await fix.result.current.mutateAsync({ contractId: 8, reason: "Brak podpisu" });
    expect(apiMock.post.mock.calls).toEqual([
      [`${BASE}/contract/8/accept`, null, { params: { month: "2026-12", kind: "actual" } }],
      [`${BASE}/contract/8/needs-fix`, { reason: "Brak podpisu" }, { params: { month: "2027-01", kind: "actual" } }],
    ]);
    expect(apiMock.put).toHaveBeenCalledWith(
      `${BASE}/contract/8/md`,
      { md_regular: "0", md_extra: null },
      { params: { month: "2026-12", kind: "estimate" } },
    );
    expect(invalidate).toHaveBeenCalledWith(refreshAll);
  });

  it("wypłata na maila i decyzja o NIP-ie (zatwierdź/odrzuć)", async () => {
    const { wrapper } = setup();
    const pay = renderHook(() => usePayOnMail("2026-12"), { wrapper });
    await pay.result.current.mutateAsync(8);
    const nip = renderHook(() => useNipDecision(), { wrapper });
    await nip.result.current.mutateAsync({ invoiceId: 50, approve: true });
    await nip.result.current.mutateAsync({ invoiceId: 51, approve: false });
    expect(apiMock.post.mock.calls).toEqual([
      [`${BASE}/contract/8/pay-on-mail`, null, { params: { month: "2026-12" } }],
      [`${BASE}/contractor-invoices/50/approve-nip`],
      [`${BASE}/contractor-invoices/51/reject-nip`],
    ]);
  });

  it("przyjęcie hurtem: domyślnie RCP faktyczne", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useAcceptBatch(), { wrapper });
    await result.current.mutateAsync({ clientId: 3, month: "2026-12" });
    await result.current.mutateAsync({ clientId: 3, month: "2026-12", kind: "estimate" });
    expect(apiMock.post.mock.calls).toEqual([
      [`${BASE}/accept-batch`, { client_id: 3, month: "2026-12", kind: "actual" }],
      [`${BASE}/accept-batch`, { client_id: 3, month: "2026-12", kind: "estimate" }],
    ]);
  });

  it("odmowa przyjęcia (409) nie odświeża rozliczeń", async () => {
    const { wrapper, invalidate } = setup();
    apiMock.post.mockRejectedValueOnce({ response: { status: 409 } });
    const { result } = renderHook(() => useAcceptSettlement("2026-12"), { wrapper });
    await expect(result.current.mutateAsync(8)).rejects.toEqual({ response: { status: 409 } });
    expect(invalidate).not.toHaveBeenCalled();
  });
});

describe("reguły klienta", () => {
  it("zapis od daty i kopia z innego klienta", async () => {
    const { wrapper, invalidate } = setup();
    const save = renderHook(() => useSaveClientRules(3), { wrapper });
    const body = { effective_from: "2027-01-01", rules: [{ key: "order.auto_accept_clean", level: "off" as const, params: {} }] };
    await save.result.current.mutateAsync(body);
    const copy = renderHook(() => useCopyClientRules(3), { wrapper });
    await copy.result.current.mutateAsync(4);
    expect(apiMock.put).toHaveBeenCalledWith(`${BASE}/rules/3`, body);
    expect(apiMock.post).toHaveBeenCalledWith(`${BASE}/rules/3/copy-from/4`);
    expect(invalidate).toHaveBeenCalledWith(refreshAll);
  });
});

describe("koszty integracji", () => {
  it("zgłoszenie, wycofanie i decyzja Delivery Leada", async () => {
    const { wrapper, invalidate } = setup();
    const add = renderHook(() => useAddIntegrationCost(8, "2026-12"), { wrapper });
    await add.result.current.mutateAsync({ amount: "0.00", description: "Kolacja zespołu" });
    const withdraw = renderHook(() => useWithdrawIntegrationCost(8, "2026-12"), { wrapper });
    await withdraw.result.current.mutateAsync(6);
    const decide = renderHook(() => useDecideIntegrationCost(3, "2026-12"), { wrapper });
    await decide.result.current.mutateAsync({ costId: 6, approve: true });
    await decide.result.current.mutateAsync({ costId: 7, approve: false });
    expect(apiMock.post.mock.calls).toEqual([
      [`${BASE}/contract/8/integration-costs`, { amount: "0.00", description: "Kolacja zespołu" }, { params: { month: "2026-12" } }],
      ["/api/my-clients/3/settlements/integration-costs/6/approve", null, { params: { month: "2026-12" } }],
      ["/api/my-clients/3/settlements/integration-costs/7/reject", null, { params: { month: "2026-12" } }],
    ]);
    expect(apiMock.delete).toHaveBeenCalledWith(`${BASE}/contract/8/integration-costs/6`, {
      params: { month: "2026-12" },
    });
    expect(invalidate).toHaveBeenCalledWith(refreshAll);
  });
});

describe("akceptacja klienta", () => {
  it("wysłano i zaakceptowano: lista kontraktów w snake_case", async () => {
    const { wrapper, invalidate } = setup();
    const sent = renderHook(() => useMarkAcceptanceSent(), { wrapper });
    await sent.result.current.mutateAsync({ clientId: 3, month: "2026-12", contractIds: [8, 9] });
    const accept = renderHook(() => useAcceptByClient(), { wrapper });
    await accept.result.current.mutateAsync({ clientId: 3, month: "2026-12", contractIds: [] });
    expect(apiMock.post.mock.calls).toEqual([
      [`${BASE}/client-acceptance/sent`, { client_id: 3, month: "2026-12", contract_ids: [8, 9] }],
      [`${BASE}/client-acceptance/accept`, { client_id: 3, month: "2026-12", contract_ids: [] }],
    ]);
    expect(invalidate).toHaveBeenCalledWith(refreshAll);
  });

  it("odpowiedź klienta i podpisany dokument: miesiąc i plik w formularzu", async () => {
    const { wrapper, invalidate } = setup();
    const reply = renderHook(() => useUploadAcceptanceReply("2026-12"), { wrapper });
    const replyFile = new File(["eml"], "odpowiedz.eml");
    await reply.result.current.mutateAsync(replyFile);
    const signed = renderHook(() => useUploadSignedDocument("2027-01"), { wrapper });
    const signedFile = new File(["%PDF"], "protokol.pdf");
    await signed.result.current.mutateAsync(signedFile);

    const [replyUrl, replyForm, replyConfig] = apiMock.post.mock.calls[0];
    expect(replyUrl).toBe(`${BASE}/client-acceptance/reply`);
    expect((replyForm as FormData).get("month")).toBe("2026-12");
    expect((replyForm as FormData).get("file")).toBe(replyFile);
    expect(replyConfig).toEqual({ headers: { "Content-Type": "multipart/form-data" } });

    const [signedUrl, signedForm] = apiMock.post.mock.calls[1];
    expect(signedUrl).toBe(`${BASE}/client-documents/signed`);
    expect((signedForm as FormData).get("month")).toBe("2027-01");
    expect((signedForm as FormData).get("file")).toBe(signedFile);
    expect(invalidate).toHaveBeenCalledWith(refreshAll);
  });
});

describe("dodatki do rozliczenia", () => {
  it("nowy dodatek: pusty opis to null, flaga faktury do klienta w snake_case", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useAddSettlementExtra("2026-12"), { wrapper });
    await result.current.mutateAsync({ contractId: 8, kind: "travel", amount: "0.01", description: "", billToClient: false });
    await result.current.mutateAsync({ contractId: 8, kind: "other", amount: "-10.00", description: "Zwrot", billToClient: true });
    expect(apiMock.post.mock.calls).toEqual([
      [`${BASE}/contract/8/extras`, { month: "2026-12", kind: "travel", amount: "0.01", description: null, bill_to_client: false }],
      [`${BASE}/contract/8/extras`, { month: "2026-12", kind: "other", amount: "-10.00", description: "Zwrot", bill_to_client: true }],
    ]);
  });

  it("decyzja: odrzucenie niesie powód, zatwierdzenie i zmiana faktury — flagę albo null", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useDecideSettlementExtra("2026-12"), { wrapper });
    await result.current.mutateAsync({ contractId: 8, extraId: 2, decision: { action: "reject", reason: "Brak biletu" } });
    await result.current.mutateAsync({ contractId: 8, extraId: 2, decision: { action: "approve" } });
    await result.current.mutateAsync({ contractId: 8, extraId: 2, decision: { action: "approve", billToClient: false } });
    await result.current.mutateAsync({ contractId: 8, extraId: 2, decision: { action: "billing", billToClient: true } });
    const month = { params: { month: "2026-12" } };
    expect(apiMock.post.mock.calls).toEqual([
      [`${BASE}/contract/8/extras/2/reject`, { reason: "Brak biletu" }, month],
      [`${BASE}/contract/8/extras/2/approve`, { bill_to_client: null }, month],
      [`${BASE}/contract/8/extras/2/approve`, { bill_to_client: false }, month],
      [`${BASE}/contract/8/extras/2/billing`, { bill_to_client: true }, month],
    ]);
  });

  it("dokument dodatku: multipart z miesiącem w parametrach", async () => {
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useUploadExtraDocument("2026-12"), { wrapper });
    const file = new File(["%PDF"], "bilet.pdf");
    await result.current.mutateAsync({ contractId: 8, extraId: 2, file });
    const [url, form, config] = apiMock.post.mock.calls[0];
    expect(url).toBe(`${BASE}/contract/8/extras/2/documents`);
    expect((form as FormData).get("file")).toBe(file);
    expect(config).toEqual({ params: { month: "2026-12" }, headers: { "Content-Type": "multipart/form-data" } });
    expect(invalidate).toHaveBeenCalledWith(refreshAll);
  });
});
