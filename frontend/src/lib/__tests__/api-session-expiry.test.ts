import { AxiosError, type AxiosResponse } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * Reakcja PRAWDZIWEJ instancji `api` na odpowiedź, która znaczy „twoja sesja
 * umarła" — i na taką, która tego NIE znaczy.
 *
 * `lib/api.ts` to jedyny klient HTTP frontendu, a 51 ze 148 plików testowych
 * podmienia go mockiem (`vi.mock("@/lib/api")`). Mock nie ma interceptorów,
 * więc każdy taki test przechodzi OBOK tej warstwy: pokrycie funkcji tego
 * pliku wynosiło 0,45%, a interceptor odpowiedzi nie był wykonywany nigdzie.
 *
 * Regresje w tym miejscu są ciche dla CI i głośne dla użytkownika — obie już
 * się zdarzyły:
 *  - 403 potraktowane jak martwa sesja wylogowywało ludzi hurtowo (zakładka
 *    Czat kandydata strzela na mount czterema requestami, wszystkie 403 dla
 *    osoby spoza zespołu);
 *  - pominięcie `clearSessionArtifacts()` zostawiało `nexus_impersonate_id`
 *    po martwej sesji, więc nagłówek „podglądu jako użytkownik" jechał dalej
 *    do NASTĘPNEGO logowania.
 *
 * Każdy przypadek dostaje świeży moduł: `sessionRedirectInFlight` w
 * `lib/api.ts` jest stanem modułu i po pierwszym przekierowaniu nie wraca do
 * `false` — bez resetu drugi przypadek badałby wyłącznie ten strażnik.
 */

const SESSION_KEYS = [
  "access_token",
  "nexus_user",
  "nexus_real_user",
  "nexus_impersonate_id",
] as const;

function seedSession(): void {
  localStorage.setItem("access_token", "DEAD_JWT");
  localStorage.setItem("nexus_user", '{"id":1}');
  localStorage.setItem("nexus_real_user", '{"id":2}');
  localStorage.setItem("nexus_impersonate_id", "7");
}

function survivingKeys(): string[] {
  return SESSION_KEYS.filter((key) => localStorage.getItem(key) !== null);
}

/** Wymuś odpowiedź o danym statusie na świeżym module `@/lib/api`.
 *
 * Adapter RZUCA `AxiosError`, a nie zwraca odpowiedź z kodem 4xx: własny
 * adapter omija `validateStatus` (to wbudowane adaptery wołają `settle`),
 * więc zwrócone 401 przeszłoby jako sukces i interceptor błędu nigdy by nie
 * wystartował — test byłby zielony, nie dotykając badanej ścieżki.
 */
async function respondWith(status: number, data: unknown): Promise<void> {
  vi.resetModules();
  const { api } = await import("@/lib/api");
  api.defaults.adapter = async (config) => {
    const response = {
      data,
      status,
      statusText: "",
      headers: {},
      config,
    } as unknown as AxiosResponse;
    throw new AxiosError(
      `Request failed with status code ${status}`,
      "ERR_BAD_REQUEST",
      config,
      {},
      response,
    );
  };
  // Interesuje nas skutek uboczny interceptora, nie sam błąd — ale odrzucenie
  // MUSI dojść do wołającego (komponent obsługuje 403 na miejscu).
  await expect(api.get("/api/candidates")).rejects.toBeTruthy();
}

afterEach(() => {
  localStorage.clear();
  window.history.pushState({}, "", "/");
});

describe("api — martwa sesja vs brak uprawnień", () => {
  it("401 kasuje KOMPLET artefaktów sesji, łącznie z markerami podglądu", async () => {
    seedSession();

    await respondWith(401, { detail: "Could not validate credentials" });

    expect(survivingKeys()).toEqual([]);
  });

  it("403 z listą ról NIE wylogowuje — to brak uprawnień, nie martwa sesja", async () => {
    seedSession();

    await respondWith(403, { detail: "Requires one of roles: ['admin', 'tac']" });

    // Regresja tutaj jest hurtowa: cztery równoległe 403 z jednej zakładki
    // wyrzucałyby użytkownika z aplikacji w trakcie normalnej pracy.
    expect(survivingKeys()).toEqual([...SESSION_KEYS]);
  });

  it("403 z detalem Not authenticated to martwa sesja w przebraniu", async () => {
    seedSession();

    // HTTPBearer(auto_error=True) raportuje BRAK nagłówka jako 403. Backend
    // odpowiada dziś 401, ale strażnik zostaje na wypadek starszego backendu
    // albo odpowiedzi z cache — inaczej użytkownik utyka w powłoce aplikacji.
    await respondWith(403, { detail: "Not authenticated" });

    expect(survivingKeys()).toEqual([]);
  });

  it("na /login 401 nie rusza storage — tam nie ma czego przekierowywać", async () => {
    window.history.pushState({}, "", "/login");
    seedSession();

    await respondWith(401, { detail: "Could not validate credentials" });

    expect(survivingKeys()).toEqual([...SESSION_KEYS]);
  });
});
