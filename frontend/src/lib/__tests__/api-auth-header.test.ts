import { beforeEach, describe, expect, it } from "vitest";

import { api } from "@/lib/api";

/**
 * Regresja: pętla logowania przez Microsoft SSO.
 *
 * Zgłoszenie (Anna Korycka): „nie mogę się zalogować. Jak wchodzę przez
 * Microsoft to próbuje się zalogować, a po chwili mnie wyrzuca na tę stronę
 * ponownie" + baner „Could not validate credentials".
 *
 * Mechanizm: strona /login/microsoft/callback wymienia jednorazowy kod na
 * świeży JWT i woła `/api/auth/me` podając ten token JAWNIE w nagłówku —
 * jeszcze zanim `setAuth` zapisze go do localStorage. Interceptor requestów
 * nadpisywał ten nagłówek tokenem z localStorage, więc backend dostawał STARY
 * (wygasły) token → 401 → redirect z powrotem na /login. Pętla była trwała:
 * handler 401 nie czyści storage będąc na ścieżce /login*, więc martwy token
 * przeżywał każdą kolejną próbę.
 *
 * TA SAMA przyczyna psuła logowanie e-mailem i hasłem: `handleSubmit`
 * w src/app/login/page.tsx również woła `/api/auth/me` ze świeżym tokenem
 * podanym jawnie (src/app/login/page.tsx:140), więc poprawne hasło kończyło
 * się banerem „Could not validate credentials". Użytkownik z martwym tokenem
 * w localStorage był odcięty OBIEMA drogami — stąd „nie mogę się zalogować".
 *
 * Kontrakt: nagłówek podany jawnie przez wołającego ZAWSZE wygrywa z
 * localStorage.
 */

/** Odpal łańcuch interceptorów bez ruchu sieciowego — adapter zwraca config. */
async function resolvedHeaders(
  requestConfig: Parameters<typeof api.request>[0],
): Promise<Record<string, unknown>> {
  const res = await api.request({
    ...requestConfig,
    adapter: async (config) => ({
      data: null,
      status: 200,
      statusText: "OK",
      headers: {},
      config,
      request: {},
    }),
  });
  return res.config.headers as unknown as Record<string, unknown>;
}

describe("api — nagłówek Authorization", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("nie nadpisuje jawnego tokenu tym z localStorage (pętla logowania SSO)", async () => {
    // Stan Anny: martwy token po wygasłej sesji wciąż siedzi w localStorage.
    localStorage.setItem("access_token", "STALE_EXPIRED");

    // Callback SSO woła /api/auth/me świeżym tokenem z wymiany kodu.
    const headers = await resolvedHeaders({
      url: "/api/auth/me",
      method: "get",
      headers: { Authorization: "Bearer FRESH_SSO" },
    });

    expect(headers.Authorization).toBe("Bearer FRESH_SSO");
    expect(headers.Authorization).not.toBe("Bearer STALE_EXPIRED");
  });

  it("nadal dokleja token z localStorage, gdy wołający nic nie podał", async () => {
    localStorage.setItem("access_token", "STORED");

    const headers = await resolvedHeaders({ url: "/api/candidates", method: "get" });

    expect(headers.Authorization).toBe("Bearer STORED");
  });

  it("nie ustawia nagłówka, gdy nie ma ani jawnego, ani zapisanego tokenu", async () => {
    const headers = await resolvedHeaders({ url: "/api/health", method: "get" });

    expect(headers.Authorization).toBeUndefined();
  });
});
