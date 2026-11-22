/**
 * Sesja przeglądarki E2E bez formularza hasła.
 *
 * Produkcja działa w trybie SSO-only (`PASSWORD_LOGIN_ENABLED=false`) i ekran
 * `/login` nie renderuje wtedy formularza hasła. Konto E2E z listy
 * `PASSWORD_LOGIN_BREAK_GLASS_EMAILS` nadal loguje się przez
 * `POST /api/auth/login`, więc token pobieramy przez API. Front nie przyjmuje
 * tokenu z JS (od 22.11.2026), dlatego harness wymienia go na ciasteczko
 * HttpOnly przez `POST /api/auth/session` z karty frontu (przeglądarka dostaje
 * ciasteczko z właściwym `Origin`, jak po zwykłym logowaniu), a sesję
 * potwierdza sonda ekranu logowania (`src/app/login/page.tsx`).
 */
import { expect, request as playwrightRequest, type Page } from "@playwright/test";

import { API_URL } from "./api";

/** Odpowiedź `GET /api/auth/methods` — źródło prawdy ekranu logowania. */
export interface AuthMethods {
  password: boolean;
  microsoft: boolean;
  self_registration: boolean;
}

export async function fetchAuthMethods(): Promise<AuthMethods> {
  const api = await playwrightRequest.newContext({ baseURL: API_URL });
  try {
    const response = await api.get("/api/auth/methods");
    expect(response.status(), "GET /api/auth/methods").toBe(200);
    return (await response.json()) as AuthMethods;
  } finally {
    await api.dispose();
  }
}

/**
 * Loguje przez API i otwiera `/login` z tokenem w localStorage. Kończy się,
 * gdy aplikacja przekierowała z ekranu logowania do powłoki.
 */
export async function openSessionViaApi(
  page: Page,
  email: string,
  password: string
): Promise<void> {
  const api = await playwrightRequest.newContext({ baseURL: API_URL });
  let token = "";
  try {
    const response = await api.post("/api/auth/login", { data: { email, password } });
    if (response.status() !== 200) {
      // Treść odpowiedzi tylko przy błędzie — udana odpowiedź niesie token.
      const body = await response.text().catch(() => "<brak treści>");
      throw new Error(
        `POST /api/auth/login: oczekiwano HTTP 200, jest ${response.status()} — ${body.slice(0, 300)}`
      );
    }
    token = ((await response.json()) as { access_token: string }).access_token;
  } finally {
    await api.dispose();
  }
  expect(token, "POST /api/auth/login nie zwrócił access_token").not.toBe("");

  await adoptBrowserSession(page, token);
  await page.waitForURL(/\/(?:$|dashboard)/, { timeout: 20_000 });
}

/**
 * Wymienia token (Bearer) na sesję przeglądarki w ciasteczku HttpOnly i otwiera
 * `/login`, którego sonda kończy logowanie. `frontUrl` — gdy kontekst nie ma
 * `baseURL`. Token żyje tylko w tym wywołaniu; aplikacja go nie widzi.
 */
export async function adoptBrowserSession(
  page: Page,
  token: string,
  frontUrl?: string
): Promise<void> {
  const loginUrl = frontUrl ? new URL("/login", frontUrl).toString() : "/login";
  await page.goto(loginUrl);
  await page.evaluate(
    async ({ api, accessToken }) => {
      const adopted = await fetch(`${api}/api/auth/session`, {
        method: "POST",
        credentials: "include",
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (!adopted.ok) throw new Error(`POST /api/auth/session: HTTP ${adopted.status}`);
      const me = await fetch(`${api}/api/auth/me`, { credentials: "include" });
      if (!me.ok) throw new Error(`GET /api/auth/me (ciasteczko): HTTP ${me.status}`);
      // Zapamiętany profil uruchamia sondę sesji na /login; przewodnik
      // onboardingowy zamknięty, żeby nie zasłaniał ekranu.
      window.localStorage.setItem("nexus_user", JSON.stringify(await me.json()));
      window.localStorage.setItem("onboarding_completed", "true");
    },
    { api: API_URL, accessToken: token }
  );
  await page.goto(loginUrl);
}
