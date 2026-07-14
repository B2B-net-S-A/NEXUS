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

const EMAIL = process.env.E2E_USER_EMAIL || "artur@b2bnet.pl";
const PASSWORD = process.env.E2E_USER_PASSWORD || "";
const COOKIE_PREFIX = process.env.E2E_SESSION_COOKIE_PREFIX || "nexus";

export const AUTH_STATE_PATH = path.join(__dirname, ".auth", "state.json");

setup("authenticate", async ({ page }) => {
  setup.skip(!PASSWORD, "Set E2E_USER_PASSWORD to enable auth-setup");

  fs.mkdirSync(path.dirname(AUTH_STATE_PATH), { recursive: true });

  await page.goto("/login");
  await page.getByPlaceholder("rekruter@firma.pl").fill(EMAIL);
  await page.getByPlaceholder("••••••••").fill(PASSWORD);
  const loginResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/auth/session/login") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /zaloguj/i }).click();
  const loginResponse = await loginResponsePromise;
  expect(loginResponse.status()).toBe(200);
  const loginBody = await loginResponse.json();
  expect(loginBody).not.toHaveProperty("access_token");
  expect(loginBody).not.toHaveProperty("refresh_token");

  // Wait until we are out of /login (dashboard redirect).
  await page.waitForURL(/\/(?:$|dashboard)/, { timeout: 20_000 });

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

  // Browser auth contract: no new persistent JS token, secure HttpOnly JWTs,
  // readable double-submit CSRF value and fail-closed mutation without it.
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("access_token")))
    .toBeNull();
  const cookies = await page.context().cookies();
  const access = cookies.find((cookie) => cookie.name === `${COOKIE_PREFIX}_access`);
  const refresh = cookies.find((cookie) => cookie.name === `${COOKIE_PREFIX}_refresh`);
  const csrf = cookies.find((cookie) => cookie.name === `${COOKIE_PREFIX}_csrf`);
  expect(access).toMatchObject({ httpOnly: true, secure: true, sameSite: "Lax" });
  expect(refresh).toMatchObject({
    httpOnly: true,
    secure: true,
    sameSite: "Lax",
    path: "/api/auth",
  });
  expect(csrf).toMatchObject({ httpOnly: false, secure: true, sameSite: "Lax" });

  const apiOrigin = new URL(loginResponse.url()).origin;
  const missingCsrf = await page.request.post(
    `${apiOrigin}/api/auth/session/logout`,
  );
  expect(missingCsrf.status()).toBe(403);

  await page.context().storageState({ path: AUTH_STATE_PATH });
});
