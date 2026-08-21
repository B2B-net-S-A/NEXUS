import { AxiosError, type InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

/**
 * Kontrakt powtarzania żądań w interceptorze `api` (`lib/api.ts`).
 *
 * To JEDYNA warstwa retry dla zapisów: `QueryProvider` ustawia `retry` tylko
 * pod `queries`, więc mutacje mają w react-query domyślne zero. Regresja tutaj
 * jest CICHA i kosztowna w obie strony:
 *
 *  - za szeroko → POST leci trzy razy. Backendowe 500 traci nagłówki CORS na
 *    najbardziej zewnętrznym middleware Starlette, więc w przeglądarce wygląda
 *    identycznie jak zerwane połączenie; wyjątek rzucony PO commicie INSERT-a
 *    dawał trzy notatki, trzech kandydatów albo trzy pozycje faktury, a
 *    użytkownik widział jeden generyczny toast;
 *  - za wąsko → wraca pierwotny objaw, dla którego ten retry powstał: okno
 *    ~30-90 s przy deployu Coolify, w którym Traefik odpowiada 502/503, a
 *    użytkownik traci wpisane dane.
 *
 * Test jedzie po PRAWDZIWEJ instancji `api` (adapter podmieniony w configu),
 * bo każdy test mockujący `@/lib/api` przechodzi obok tej warstwy — to axios
 * decyduje o powtórce, a mock nie ma czego zepsuć.
 */

type Respond = (attempt: number, config: InternalAxiosRequestConfig) => unknown;

async function run(
  requestConfig: Parameters<typeof api.request>[0],
  respond: Respond,
): Promise<{ outcome: "fulfilled" | "rejected"; attempts: number }> {
  let attempts = 0;
  const settled = api
    .request({
      ...requestConfig,
      adapter: async (config) => {
        attempts += 1;
        return respond(attempts, config) as never;
      },
    })
    .then(
      () => "fulfilled" as const,
      () => "rejected" as const,
    );

  // Interceptor śpi 1,5 s i 3 s między próbami — na realnym zegarze test
  // ocierałby się o domyślny limit vitest. Kilka przewinięć, bo każda próba
  // planuje kolejny timer dopiero po odrzuceniu poprzedniej.
  for (let i = 0; i < 4; i++) {
    await vi.advanceTimersByTimeAsync(5_000);
  }

  return { outcome: await settled, attempts };
}

function httpError(
  config: InternalAxiosRequestConfig,
  status: number,
): AxiosError {
  return new AxiosError(`Request failed with status code ${status}`, String(status), config, {}, {
    config,
    data: {},
    headers: {},
    request: {},
    status,
    statusText: "",
  });
}

/** 500 z obciętym CORS-em albo zerwane połączenie — brak `response`. */
function bodilessNetworkError(config: InternalAxiosRequestConfig): AxiosError {
  return new AxiosError("Network Error", AxiosError.ERR_NETWORK, config, {});
}

function clientTimeout(config: InternalAxiosRequestConfig): AxiosError {
  return new AxiosError(
    "timeout of 30000ms exceeded",
    AxiosError.ECONNABORTED,
    config,
    {},
  );
}

describe("api — powtarzanie żądań przejściowych", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("NIE powtarza POST-a po bezcielesnym błędzie sieci (500 bez CORS = zapis mógł przejść)", async () => {
    const { outcome, attempts } = await run(
      { url: "/api/notes", method: "post", data: { content: "x" } },
      (_n, config) => Promise.reject(bodilessNetworkError(config)),
    );

    expect(attempts).toBe(1);
    expect(outcome).toBe("rejected");
  });

  it("NIE powtarza POST-a po 504 — brama przestała czekać, backend mógł dokończyć", async () => {
    const { attempts } = await run(
      { url: "/api/candidates", method: "post", data: {} },
      (_n, config) => Promise.reject(httpError(config, 504)),
    );

    expect(attempts).toBe(1);
  });

  it("POWTARZA POST-a przy 502/503 — brama odpowiedziała ZA aplikacją (okno deployu)", async () => {
    const { attempts } = await run(
      { url: "/api/candidates", method: "post", data: {} },
      (_n, config) => Promise.reject(httpError(config, 503)),
    );

    expect(attempts).toBe(3); // pierwsza próba + TRANSIENT_RETRY_MAX
  });

  it("powtarza POST-a tylko do skutku — druga próba kończy się sukcesem", async () => {
    const { outcome, attempts } = await run(
      { url: "/api/candidates", method: "post", data: {} },
      (n, config) =>
        n === 1
          ? Promise.reject(httpError(config, 502))
          : { data: { id: 1 }, status: 201, statusText: "", headers: {}, config, request: {} },
    );

    expect(attempts).toBe(2);
    expect(outcome).toBe("fulfilled");
  });

  it("NIE powtarza DELETE-a po bezcielesnym błędzie sieci", async () => {
    const { attempts } = await run(
      { url: "/api/notes/1", method: "delete" },
      (_n, config) => Promise.reject(bodilessNetworkError(config)),
    );

    expect(attempts).toBe(1);
  });

  it("powtarza GET-a po bezcielesnym błędzie sieci — odczyt jest idempotentny", async () => {
    const { attempts } = await run(
      { url: "/api/candidates", method: "get" },
      (_n, config) => Promise.reject(bodilessNetworkError(config)),
    );

    expect(attempts).toBe(3);
  });

  it("powtarza GET-a przy 504", async () => {
    const { attempts } = await run(
      { url: "/api/candidates", method: "get" },
      (_n, config) => Promise.reject(httpError(config, 504)),
    );

    expect(attempts).toBe(3);
  });

  it("NIE powtarza po timeoucie po stronie przeglądarki — backend nadal liczy i płaci", async () => {
    const forGet = await run({ url: "/api/candidates", method: "get" }, (_n, config) =>
      Promise.reject(clientTimeout(config)),
    );
    const forPost = await run(
      { url: "/api/jobs/1/champion-profile/briefing", method: "post", data: {} },
      (_n, config) => Promise.reject(clientTimeout(config)),
    );

    expect(forGet.attempts).toBe(1);
    expect(forPost.attempts).toBe(1);
  });

  it("nie powtarza błędów, które nie są przejściowe (403 na GET)", async () => {
    const { attempts } = await run({ url: "/api/candidates", method: "get" }, (_n, config) =>
      Promise.reject(httpError(config, 403)),
    );

    expect(attempts).toBe(1);
  });
});
