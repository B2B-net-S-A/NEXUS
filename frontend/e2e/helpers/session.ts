/**
 * Sesja przeglądarki E2E bez formularza hasła.
 *
 * Produkcja działa w trybie SSO-only (`PASSWORD_LOGIN_ENABLED=false`) i ekran
 * `/login` nie renderuje wtedy formularza hasła. Konto E2E z listy
 * `PASSWORD_LOGIN_BREAK_GLASS_EMAILS` nadal loguje się przez
 * `POST /api/auth/login`, więc token pobieramy przez API i oddajemy go sondzie
 * sesji ekranu logowania (`src/app/login/page.tsx`). Sonda sprawdza JWT przez
 * `/api/auth/me`, zapisuje użytkownika i odtwarza cookie `nexus_access`
 * czytane przez middleware — tak samo jak po zwykłym logowaniu formularzem.
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

  // Przewodnik onboardingowy pamięta zamknięcie w localStorage — ustawiamy go
  // przed pierwszym renderem zamiast ścigać się z nakładką (jak w setupie).
  await page.addInitScript((accessToken: string) => {
    window.localStorage.setItem("onboarding_completed", "true");
    window.localStorage.setItem("access_token", accessToken);
  }, token);
  await page.goto("/login");
  await page.waitForURL(/\/(?:$|dashboard)/, { timeout: 20_000 });
}
