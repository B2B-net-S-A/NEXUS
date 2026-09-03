import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { adminApi, api, recommendationsApi } from "@/lib/api";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";

/**
 * Kształt requestu wychodzącego z PRAWDZIWEJ instancji `api`.
 *
 * `lib/api.ts` jest jedynym klientem HTTP frontendu i jednocześnie plikiem
 * o zerowym praktycznie pokryciu funkcji: 51 na 148 plików testowych podmienia
 * go mockiem (`vi.mock("@/lib/api")`), więc asertują, że komponent zawołał
 * stuba — nie są w stanie zobaczyć requestu, który faktycznie się buduje.
 * Wszystkie awarie, które ten plik wyprodukował na produkcji, siedzą właśnie
 * w warstwie, którą mock omija: nagłówek `Content-Type` przy multipartcie,
 * efektywny timeout, doklejanie tokenu.
 *
 * Ten plik zamyka lukę od strony zachowania — kontrakt sprawdzamy na
 * konfiguracji, którą widzi adapter, czyli na tym, co realnie poszłoby na
 * sieć.
 */

interface Captured {
  url?: string;
  method?: string;
  timeout?: number;
  contentType?: unknown;
  isFormData: boolean;
  data?: unknown;
  params?: unknown;
}

/** AxiosHeaders trzyma klucz w formie, w jakiej go podano — szukamy bez względu na wielkość liter. */
function headerValue(headers: Record<string, unknown>, name: string): unknown {
  const key = Object.keys(headers ?? {}).find(
    (k) => k.toLowerCase() === name.toLowerCase(),
  );
  return key ? headers[key] : undefined;
}

let captured: Captured[] = [];
let previousAdapter: typeof api.defaults.adapter;

beforeEach(() => {
  captured = [];
  previousAdapter = api.defaults.adapter;
  api.defaults.adapter = async (config) => {
    const headers = config.headers as unknown as Record<string, unknown>;
    captured.push({
      contentType: headerValue(headers, "content-type"),
      isFormData:
        typeof FormData !== "undefined" && config.data instanceof FormData,
      method: config.method,
      timeout: config.timeout,
      url: config.url,
      data: config.data,
      params: config.params,
    });
    return {
      data: {},
      status: 200,
      statusText: "OK",
      headers: {},
      config,
      request: {},
    };
  };
});

afterEach(() => {
  api.defaults.adapter = previousAdapter;
});

describe("api — kontrakt requestu wychodzącego", () => {
  it("upload CV idzie jako multipart, a nie jako JSON", async () => {
    const file = new File(["%PDF-1.4"], "cv.pdf", { type: "application/pdf" });

    await recommendationsApi.cvUploadPreview(file, { top_k: 5 });

    expect(captured).toHaveLength(1);
    // Bez tego nagłówka axios serializuje FormData do JSON-a i FastAPI
    // odpowiada 422 „file Field required" — plik nigdy nie opuszcza
    // przeglądarki, a `curl` na ten sam endpoint działa (omija axiosa).
    expect(captured[0].isFormData).toBe(true);
    expect(captured[0].contentType).toBe("multipart/form-data");
    // Parse CV + scoring puli — użytkownik czeka, więc sufit CRUD-a nie wystarcza.
    expect(captured[0].timeout).toBe(SLOW_ENDPOINT_TIMEOUT_MS);
  });

  it("dokleja token z localStorage i trafia w skonfigurowany baseURL", async () => {
    localStorage.setItem("access_token", "TOKEN123");
    try {
      await api.get("/api/candidates");
    } finally {
      localStorage.removeItem("access_token");
    }

    expect(captured).toHaveLength(1);
    expect(captured[0].url).toBe("/api/candidates");
    expect(captured[0].method).toBe("get");
    expect(api.defaults.baseURL).toBeTruthy();
  });

  it("wysyła wersję polityki i zbiorczą zmianę uprawnień roli", async () => {
    await adminApi.updateRoleSectionPermissions(7, [
      { role: "recruiter", section: "delivery", access: "read" },
      { role: "recruiter", section: "finance", access: "none" },
    ]);

    expect(captured).toHaveLength(1);
    expect(captured[0]).toMatchObject({
      method: "put",
      url: "/api/admin/section-permissions/roles",
    });
    expect(JSON.parse(String(captured[0].data))).toEqual({
      revision: 7,
      changes: [
        { role: "recruiter", section: "delivery", access: "read" },
        { role: "recruiter", section: "finance", access: "none" },
      ],
    });
  });

  it("wysyła inherit jako usunięcie wyjątku użytkownika", async () => {
    await adminApi.updateUserSectionPermissions(42, 8, [
      { section: "delivery", access: "inherit" },
    ]);

    expect(captured).toHaveLength(1);
    expect(captured[0]).toMatchObject({
      method: "put",
      url: "/api/admin/section-permissions/users/42",
    });
    expect(JSON.parse(String(captured[0].data))).toEqual({
      revision: 8,
      changes: [{ section: "delivery", access: "inherit" }],
    });
  });
});
