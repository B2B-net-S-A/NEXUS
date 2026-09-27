/**
 * Blokada zapisów w harnessach `/preview/*` (runda 10 audytu, R10-N10-2).
 *
 * Harnessy renderują PRODUKCYJNE komponenty na danych fikcyjnych. Do 27.09.2026
 * kliknięcie w harnessie w zalogowanej przeglądarce (tak każe weryfikacja UI:
 * „authed → harness /preview/*”) wysyłało prawdziwy zapis: „Zakończ zamówienie”
 * w `/preview/order-tile` zamykało zamówienie 1 klienta 1, checkbox w
 * `/preview/dl-alerts` zamykał prawdziwą sprawę DL o ID 101.
 *
 * Reguła (decyzja Artura 27.09.2026): każde żądanie inne niż odczyt jest
 * odrzucane przed wysłaniem, a odczyt idzie bez `Authorization` (i bez nagłówka
 * podglądu „jako”) — harness nie działa na tożsamości oglądającego.
 *
 * Odrzucenie ma kod `ECONNABORTED` i nie ma odpowiedzi: interceptor ponowień
 * w `lib/api.ts` takiego błędu nie powtarza, a wylogowanie po 401 go nie
 * dotyczy. Z tego samego powodu 401/403 odczytu bez tokenu zamieniamy na błąd
 * bez odpowiedzi — inaczej `triggerSessionExpiredRedirect` wylogowałby
 * zalogowanego oglądającego z całej aplikacji.
 *
 * Opakowania (adapter axios i `window.fetch`) instalują się raz; flaga
 * `active` włącza je tylko na czas życia layoutu `/preview`, więc po miękkiej
 * nawigacji z harnessu do aplikacji ruch wraca do normy.
 */
import {
  AxiosError,
  getAdapter,
  type AxiosAdapter,
  type InternalAxiosRequestConfig,
} from "axios";

import { api } from "@/lib/api";

const READ_METHODS = new Set(["get", "head", "options"]);
const STRIPPED_HEADERS = ["Authorization", "X-Impersonate-User-Id"];

export const PREVIEW_WRITE_BLOCKED = "preview: zapisy wyłączone w podglądzie";

let active = false;
let installed = false;

function isRead(method: string | undefined): boolean {
  return READ_METHODS.has((method ?? "get").toLowerCase());
}

function stripAxiosHeaders(config: InternalAxiosRequestConfig): void {
  const headers = config.headers as
    | { delete?: (name: string) => unknown; [key: string]: unknown }
    | undefined;
  if (!headers) return;
  for (const name of STRIPPED_HEADERS) {
    if (typeof headers.delete === "function") headers.delete(name);
    delete headers[name];
    delete headers[name.toLowerCase()];
  }
}

function blocked(config: InternalAxiosRequestConfig, message: string): AxiosError {
  return new AxiosError(message, "ECONNABORTED", config);
}

function installAxiosGuard(): void {
  const original: AxiosAdapter = getAdapter(api.defaults.adapter);
  api.defaults.adapter = async (config) => {
    if (!active) return original(config);
    if (!isRead(config.method)) throw blocked(config, PREVIEW_WRITE_BLOCKED);
    stripAxiosHeaders(config);
    try {
      return await original(config);
    } catch (error) {
      const status = (error as AxiosError).response?.status;
      if (status === 401 || status === 403) {
        throw blocked(config, "preview: odczyt bez sesji");
      }
      throw error;
    }
  };
}

function fetchMethod(input: RequestInfo | URL, init?: RequestInit): string {
  if (init?.method) return init.method;
  if (typeof Request !== "undefined" && input instanceof Request) return input.method;
  return "GET";
}

function installFetchGuard(): void {
  if (typeof window === "undefined" || typeof window.fetch !== "function") return;
  const original = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    if (!active) return original(input, init);
    if (!isRead(fetchMethod(input, init))) {
      return Promise.reject(new TypeError(PREVIEW_WRITE_BLOCKED));
    }
    const headers = new Headers(
      init?.headers ??
        (typeof Request !== "undefined" && input instanceof Request
          ? input.headers
          : undefined),
    );
    for (const name of STRIPPED_HEADERS) headers.delete(name);
    return original(input, { ...init, headers });
  };
}

/** Włącza blokadę (idempotentnie). Bez okna przeglądarki nic nie robi — SSR
 * dzieli moduł `api` z każdą inną trasą procesu Node. */
export function activatePreviewNetworkGuard(): void {
  if (typeof window === "undefined") return;
  if (!installed) {
    installAxiosGuard();
    installFetchGuard();
    installed = true;
  }
  active = true;
}

export function deactivatePreviewNetworkGuard(): void {
  active = false;
}
