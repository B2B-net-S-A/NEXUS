import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import { b2bEsignApi, signedPdfProblem } from "@/lib/api/b2bEsign";

beforeEach(() => {
  apiMock.get.mockReset();
  apiMock.post.mockReset();
  apiMock.put.mockReset();
  apiMock.get.mockResolvedValue({ data: { ok: "get" } });
  apiMock.post.mockResolvedValue({ data: { ok: "post" } });
  apiMock.put.mockResolvedValue({ data: { ok: "put" } });
});

function pdf(name: string, size: number): File {
  const file = new File(["x"], name, { type: "application/pdf" });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("signedPdfProblem", () => {
  it("przyjmuje PDF niezależnie od wielkości liter rozszerzenia", () => {
    expect(signedPdfProblem(pdf("umowa.pdf", 1024))).toBeNull();
    expect(signedPdfProblem(pdf("UMOWA.PDF", 1024))).toBeNull();
  });

  it("odrzuca skan i zdjęcie, bo nie niosą podpisu", () => {
    expect(signedPdfProblem(pdf("skan.jpg", 1024))).toBe("Wgraj podpisany plik PDF.");
    expect(signedPdfProblem(pdf("umowa.pdf.png", 1024))).toBe("Wgraj podpisany plik PDF.");
    expect(signedPdfProblem(pdf("umowa", 1024))).toBe("Wgraj podpisany plik PDF.");
  });

  it("odrzuca pusty plik", () => {
    expect(signedPdfProblem(pdf("umowa.pdf", 0))).toBe("Plik jest pusty.");
  });

  it("granica 20 MB: dokładnie 20 MB przechodzi, bajt więcej nie", () => {
    const limit = 20 * 1024 * 1024;
    expect(signedPdfProblem(pdf("umowa.pdf", limit))).toBeNull();
    expect(signedPdfProblem(pdf("umowa.pdf", limit + 1))).toBe(
      "Plik jest za duży, może mieć najwyżej 20 MB.",
    );
  });
});

describe("b2bEsignApi", () => {
  it("ustawienia: odczyt i zapis zwracają samo `data`", async () => {
    await expect(b2bEsignApi.settings()).resolves.toEqual({ ok: "get" });
    expect(apiMock.get).toHaveBeenCalledWith("/api/b2b-generator/esign/settings");

    const body = { mode: "pilot" as const, pilot_user_ids: [3], company_signer_ids: [7] };
    await expect(b2bEsignApi.saveSettings(body)).resolves.toEqual({ ok: "put" });
    expect(apiMock.put).toHaveBeenCalledWith("/api/b2b-generator/esign/settings", body);
  });

  it("domyślne dane i wysyłka idą pod umowę wygenerowaną", async () => {
    await b2bEsignApi.defaults(41);
    expect(apiMock.get).toHaveBeenCalledWith("/api/b2b-generator/generated/41/esign/defaults");

    const body = {
      contractor_email: "jan.testowy@example.com",
      company_signer_id: 2,
      days: 7,
      cc_user_ids: [5],
      start_document_ids: [],
      qualified_document_ids: [9],
    };
    await expect(b2bEsignApi.send(41, body)).resolves.toEqual({ ok: "post" });
    expect(apiMock.post).toHaveBeenCalledWith("/api/b2b-generator/generated/41/esign/send", body);
  });

  it("przedłużenie, nowy link, przejęcie i wycofanie trafiają w swój wniosek", async () => {
    await b2bEsignApi.extend(12, 14);
    await b2bEsignApi.relink(12, 0);
    await b2bEsignApi.takeOver(12);
    await b2bEsignApi.withdraw(12, "Kontraktor zrezygnował");
    expect(apiMock.post.mock.calls).toEqual([
      ["/api/b2b-generator/esign/12/extend", { days: 14 }],
      ["/api/b2b-generator/esign/12/relink", { days: 0 }],
      ["/api/b2b-generator/esign/12/take-over"],
      ["/api/b2b-generator/esign/12/withdraw", { reason: "Kontraktor zrezygnował" }],
    ]);
  });

  it("lista „Czeka na mój podpis”", async () => {
    apiMock.get.mockResolvedValueOnce({ data: [] });
    await expect(b2bEsignApi.mine()).resolves.toEqual([]);
    expect(apiMock.get).toHaveBeenCalledWith("/api/b2b-generator/esign/mine");
  });

  it("PDF-y pobiera jako blob i oddaje całą odpowiedź (nagłówki do nazwy pliku)", async () => {
    const response = { data: new Blob(["%PDF"]), headers: { "content-disposition": "x" } };
    apiMock.get.mockResolvedValue(response);
    await expect(b2bEsignApi.companyPdf(3)).resolves.toBe(response);
    await expect(b2bEsignApi.signedPdf(3)).resolves.toBe(response);
    expect(apiMock.get).toHaveBeenNthCalledWith(1, "/api/b2b-generator/esign/3/pdf", {
      responseType: "blob",
    });
    expect(apiMock.get).toHaveBeenNthCalledWith(2, "/api/b2b-generator/esign/3/signed-pdf", {
      responseType: "blob",
    });
  });

  it("podpis firmy wysyła plik jako multipart pod polem `file`", async () => {
    const file = pdf("podpisana.pdf", 10);
    await b2bEsignApi.companySign(8, file);
    const [url, form, config] = apiMock.post.mock.calls[0];
    expect(url).toBe("/api/b2b-generator/esign/8/company-sign");
    expect(form).toBeInstanceOf(FormData);
    expect((form as FormData).get("file")).toBe(file);
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });
  });

  it("podpis w chmurze: dostępność, start z listą wniosków, stan sesji z zakodowanym id", async () => {
    await b2bEsignApi.companyRemoteAvailable();
    expect(apiMock.get).toHaveBeenCalledWith(
      "/api/b2b-generator/esign/company-remote/available",
    );

    await b2bEsignApi.companyRemoteStart([1, 2]);
    expect(apiMock.post).toHaveBeenCalledWith("/api/b2b-generator/esign/company-remote/start", {
      request_ids: [1, 2],
    });

    await b2bEsignApi.companyRemoteStatus("a/b c?d");
    expect(apiMock.get).toHaveBeenLastCalledWith(
      "/api/b2b-generator/esign/company-remote/a%2Fb%20c%3Fd",
    );
  });

  it("błąd serwera przechodzi do wywołującego", async () => {
    const error = Object.assign(new Error("Request failed"), { response: { status: 409 } });
    apiMock.post.mockRejectedValueOnce(error);
    await expect(b2bEsignApi.withdraw(1, "x")).rejects.toBe(error);
  });
});
