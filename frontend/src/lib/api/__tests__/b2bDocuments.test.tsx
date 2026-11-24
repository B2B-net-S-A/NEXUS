import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import {
  B2B_DOCUMENTS_PAGE_SIZE,
  type DocumentRequestBody,
  b2bDocumentsApi,
  b2bDocumentsKeys,
  useDocumentTypes,
} from "@/lib/api/b2bDocuments";

const body: DocumentRequestBody = {
  document_type: "annex_rate",
  language: "pl",
  parent_generated_contract_id: 3,
} as DocumentRequestBody;

beforeEach(() => {
  for (const fn of Object.values(apiMock)) {
    fn.mockReset();
    fn.mockResolvedValue({ data: { ok: true } });
  }
});

describe("b2bDocumentsKeys", () => {
  it("lista: rodziny złączone przecinkiem, brak rodzin = pusty tekst", () => {
    expect(
      b2bDocumentsKeys.list({ documentType: "", status: "unsigned", q: "Jan", family: ["annex", "termination"] }),
    ).toEqual(["b2b-documents", "list", "", "unsigned", "Jan", "annex,termination"]);
    expect(b2bDocumentsKeys.list({ documentType: "x", status: "", q: "" })).toEqual([
      "b2b-documents",
      "list",
      "x",
      "",
      "",
      "",
    ]);
  });

  it("prefill i podmioty: brak id zastępuje 0", () => {
    expect(b2bDocumentsKeys.prefill("annex_rate", null, null)).toEqual([
      "b2b-documents",
      "prefill",
      "annex_rate",
      0,
      0,
      0,
      0,
    ]);
    expect(b2bDocumentsKeys.prefill("preliminary", 1, 2, 3, 4)).toEqual([
      "b2b-documents",
      "prefill",
      "preliminary",
      1,
      2,
      3,
      4,
    ]);
    expect(b2bDocumentsKeys.subjects("annex_rate", "an")).toEqual([
      "b2b-documents",
      "subjects",
      "annex_rate",
      "an",
      0,
    ]);
    expect(b2bDocumentsKeys.effects(5)).toEqual(["b2b-documents", "effects", 5]);
    expect(b2bDocumentsKeys.history(5)).toEqual(["b2b-documents", "history", 5]);
    expect(b2bDocumentsKeys.preliminaryOptions(1, 2)).toEqual(["b2b-documents", "preliminary-options", 1, 2]);
  });
});

describe("prefill", () => {
  it("sam typ: żadnych pustych identyfikatorów w zapytaniu", async () => {
    await b2bDocumentsApi.prefill({
      documentType: "termination",
      parentGeneratedContractId: null,
      candidateId: 0,
      jobId: undefined,
      contractId: null,
    });
    expect(apiMock.get).toHaveBeenCalledWith("/api/b2b-generator/documents/prefill", {
      params: { document_type: "termination" },
    });
  });

  it("wszystkie identyfikatory w snake_case", async () => {
    await b2bDocumentsApi.prefill({
      documentType: "preliminary",
      parentGeneratedContractId: 1,
      candidateId: 2,
      jobId: 3,
      contractId: 4,
    });
    expect(apiMock.get).toHaveBeenCalledWith("/api/b2b-generator/documents/prefill", {
      params: {
        document_type: "preliminary",
        parent_generated_contract_id: 1,
        candidate_id: 2,
        job_id: 3,
        contract_id: 4,
      },
    });
  });
});

describe("subjects", () => {
  it("fraza przycięta, pusta pominięta, kontrakt z modułu Kontrakty", async () => {
    await b2bDocumentsApi.subjects({ documentType: "annex_rate", q: "  Anna  ", contractId: 9 });
    await b2bDocumentsApi.subjects({ documentType: "annex_rate", q: "   ", contractId: null });
    expect(apiMock.get.mock.calls).toEqual([
      [
        "/api/b2b-generator/documents/subjects",
        { params: { document_type: "annex_rate", q: "Anna", contract_id: 9 } },
      ],
      ["/api/b2b-generator/documents/subjects", { params: { document_type: "annex_rate" } }],
    ]);
  });
});

describe("list", () => {
  it("domyślnie strona 50 i powtórzony parametr dla listy (bez `[]`)", async () => {
    await b2bDocumentsApi.list();
    expect(apiMock.get).toHaveBeenCalledWith("/api/b2b-generator/documents", {
      params: { limit: B2B_DOCUMENTS_PAGE_SIZE },
      paramsSerializer: { indexes: null },
    });
  });

  it("wszystkie filtry; rodziny kopiowane do zwykłej tablicy", async () => {
    const family = Object.freeze(["annex"] as const);
    await b2bDocumentsApi.list({
      limit: 10,
      offset: 50,
      parentGeneratedContractId: 3,
      documentType: "annex_rate",
      status: "no_contract",
      family,
      q: " Firma Testowa ",
    });
    const params = apiMock.get.mock.calls[0][1].params;
    expect(params).toEqual({
      limit: 10,
      offset: 50,
      parent_generated_contract_id: 3,
      document_type: "annex_rate",
      status: "no_contract",
      family: ["annex"],
      q: "Firma Testowa",
    });
    expect(params.family).not.toBe(family);
  });

  it("pierwsza strona (offset 0), pusta lista rodzin i pusta fraza nie trafiają do zapytania", async () => {
    await b2bDocumentsApi.list({ offset: 0, family: [], q: "", status: undefined });
    expect(apiMock.get.mock.calls[0][1].params).toEqual({ limit: 50 });
  });
});

describe("pliki dokumentu", () => {
  it("utworzenie, ponowne pobranie, PDF i przerysowanie zwracają blob z nagłówkami", async () => {
    const response = { data: new Blob(["docx"]), headers: { "x-document-id": "12" } };
    apiMock.post.mockResolvedValue(response);
    await expect(b2bDocumentsApi.create(body)).resolves.toBe(response);
    await b2bDocumentsApi.redownload(12);
    await b2bDocumentsApi.pdf(12, { pesel: "00000000000" });
    await b2bDocumentsApi.rerender(12, body);
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/b2b-generator/documents", body, { responseType: "blob" }],
      ["/api/b2b-generator/documents/12/docx", { values: {} }, { responseType: "blob" }],
      ["/api/b2b-generator/documents/12/pdf", { values: { pesel: "00000000000" } }, { responseType: "blob" }],
      ["/api/b2b-generator/documents/12/rerender", body, { responseType: "blob" }],
    ]);
  });

  it("wzór zlecenia: klucz zakodowany w ścieżce", async () => {
    await b2bDocumentsApi.mandateForm("umowa zlecenie/2026");
    expect(apiMock.get).toHaveBeenCalledWith(
      "/api/b2b-generator/mandate-forms/umowa%20zlecenie%2F2026",
      { responseType: "blob" },
    );
  });

  it("503 przy PDF (konwerter chwilowo niedostępny) dochodzi do ekranu", async () => {
    const error = { response: { status: 503 } };
    apiMock.post.mockRejectedValueOnce(error);
    await expect(b2bDocumentsApi.pdf(12)).rejects.toBe(error);
  });

  it("skan podpisanego aneksu jako multipart", async () => {
    const file = new File(["%PDF"], "aneks.pdf");
    await b2bDocumentsApi.uploadSignedScan(7, file);
    const [url, form, config] = apiMock.post.mock.calls[0];
    expect(url).toBe("/api/b2b-generator/documents/7/signed-scan");
    expect((form as FormData).get("file")).toBe(file);
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });
  });
});

describe("cykl życia dokumentu", () => {
  it("podgląd, formularz, skutki, historia i opcje umowy przedwstępnej", async () => {
    await b2bDocumentsApi.types();
    await b2bDocumentsApi.preview(body);
    await b2bDocumentsApi.form(4);
    await b2bDocumentsApi.effects(4);
    await b2bDocumentsApi.history(4);
    await b2bDocumentsApi.preliminaryOptions(10, 20);
    expect(apiMock.get.mock.calls).toEqual([
      ["/api/b2b-generator/document-types"],
      ["/api/b2b-generator/documents/4/form"],
      ["/api/b2b-generator/documents/4/effects"],
      ["/api/b2b-generator/documents/4/history"],
      ["/api/b2b-generator/documents/preliminary-options", { params: { candidate_id: 10, job_id: 20 } }],
    ]);
    expect(apiMock.post).toHaveBeenCalledWith("/api/b2b-generator/documents/preview", body);
  });

  it("podpis, anulowanie, przywrócenie, powiązanie z kontraktem i wypowiedzenie Partnera", async () => {
    await b2bDocumentsApi.confirmSigned(4);
    await b2bDocumentsApi.cancel(4, "Pomyłka w stawce");
    await b2bDocumentsApi.restore(4);
    await b2bDocumentsApi.linkContract(4, 30);
    await b2bDocumentsApi.partnerNotice({
      parent_generated_contract_id: 3,
      delivered_on: "2026-12-31",
      termination_date: null,
    });
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/b2b-generator/documents/4/confirm-signed"],
      ["/api/b2b-generator/documents/4/cancel", { reason: "Pomyłka w stawce" }],
      ["/api/b2b-generator/documents/4/restore"],
      ["/api/b2b-generator/documents/4/link-contract", { contract_id: 30 }],
      [
        "/api/b2b-generator/documents/partner-notice",
        { parent_generated_contract_id: 3, delivered_on: "2026-12-31", termination_date: null },
      ],
    ]);
  });

  it("usunięcie nie zwraca treści odpowiedzi", async () => {
    apiMock.delete.mockResolvedValueOnce({ data: { deleted: true } });
    await expect(b2bDocumentsApi.remove(4)).resolves.toBeUndefined();
    expect(apiMock.delete).toHaveBeenCalledWith("/api/b2b-generator/documents/4");
  });

  it("kandydaci i rekrutacje do umowy przedwstępnej z tras Generatora", async () => {
    await b2bDocumentsApi.searchCandidates("Przykładowa");
    await b2bDocumentsApi.candidateRecruitments(10);
    expect(apiMock.get.mock.calls).toEqual([
      ["/api/cv-generator/candidates", { params: { q: "Przykładowa", limit: 20 } }],
      ["/api/cv-generator/candidates/10/recruitments"],
    ]);
  });
});

describe("useDocumentTypes", () => {
  it("czyta definicje typów z serwera", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    apiMock.get.mockResolvedValueOnce({ data: { types: [] } });
    const { result } = renderHook(() => useDocumentTypes(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ types: [] });
  });
});
