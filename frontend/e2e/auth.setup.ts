/**
 * Playwright setup project — logs in once and stores the session so the rest
 * of the specs run against a warm state instead of re-logging per test.
 *
 * Skipping this step is also what fixed the intermittent `waitForURL` timeouts
 * in the Phase 9 suite — the post-login dashboard has an onboarding overlay
 * with a `Pomiń przewodnik` CTA that sometimes racing with the navigation.
 * Here we log in once, dismiss the overlay, and write the browser state.
 */
import { test as setup, expect } from "@playwright/test";
import fs from "fs";
import path from "path";

import { fetchAuthMethods, openSessionViaApi } from "./helpers/session";

const EMAIL = process.env.E2E_USER_EMAIL || "artur@b2bnet.pl";
const PASSWORD = process.env.E2E_USER_PASSWORD || "";

export const AUTH_STATE_PATH = path.join(__dirname, ".auth", "state.json");

setup("authenticate", async ({ page }) => {
  // Na stacku E2E w CI brak hasła jest BŁĘDEM konfiguracji, nie powodem do
  // pominięcia: pominięty setup zostawiał wszystkie scenariusze po zalogowaniu
  // niewykonane przy zielonym biegu (audyt QA 14.09.2026).
  if (process.env.E2E_REQUIRE_AUTH === "1") {
    expect(PASSWORD, "E2E_REQUIRE_AUTH=1 wymaga E2E_USER_PASSWORD").not.toBe("");
  }
  setup.skip(!PASSWORD, "Set E2E_USER_PASSWORD to enable auth-setup");

  fs.mkdirSync(path.dirname(AUTH_STATE_PATH), { recursive: true });

  // Produkcja działa w trybie SSO-only: bez formularza hasła na /login konto E2E
  // (lista PASSWORD_LOGIN_BREAK_GLASS_EMAILS) loguje się przez API. Stack E2E ma
  // logowanie hasłem włączone, więc w CI dalej sprawdzamy formularz.
  const methods = await fetchAuthMethods();
  if (methods.password) {
    // Przewodnik onboardingowy zapamiętuje zamknięcie w localStorage — ustawiamy
    // go przed pierwszym renderem zamiast ścigać się z nakładką.
    await page.addInitScript(() => {
      window.localStorage.setItem("onboarding_completed", "true");
    });
    await page.goto("/login");
    // Selektory po `id` pól i DOKŁADNEJ nazwie przycisku: placeholder e-maila
    // zmienił się z `rekruter@firma.pl`, a `/zaloguj/i` łapał też przycisk
    // „Zaloguj się przez Microsoft".
    await page.locator("#login-email").fill(EMAIL);
    await page.locator("#login-password").fill(PASSWORD);
    await page.getByRole("button", { name: "Zaloguj się", exact: true }).click();

    // Wait until we are out of /login (dashboard redirect).
    await page.waitForURL(/\/(?:$|dashboard)/, { timeout: 20_000 });
  } else {
    await openSessionViaApi(page, EMAIL, PASSWORD);
  }

  // Dismiss onboarding overlay if it appears — this is the race that broke
  // the Phase 9 suite.
  const skipBtn = page.getByRole("button", { name: /Pomiń przewodnik/i });
  try {
    await skipBtn.click({ timeout: 3_000 });
  } catch {
    /* overlay already dismissed or not shown */
  }

  // Sanity: we should see a logged-in shell element.
  await expect(
    page.getByRole("link", { name: /Kandydaci/i }).first()
  ).toBeVisible();

  await page.context().storageState({ path: AUTH_STATE_PATH });
});
