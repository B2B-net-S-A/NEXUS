/**
 * Ścieżka sesji, której setup używa na produkcji SSO-only: token z
 * `POST /api/auth/login` → ciasteczko HttpOnly (`POST /api/auth/session`) +
 * sonda sesji ekranu /login. Produkcja nie ma
 * formularza hasła, więc bez tego scenariusza jedyny test tej ścieżki
 * odbywałby się dopiero na produkcji, po założeniu konta E2E.
 */
import { test, expect } from "@playwright/test";

import { openSessionViaApi } from "./helpers/session";

test.use({ storageState: { cookies: [], origins: [] } });

test("sesja z tokenu API otwiera aplikację bez formularza hasła @stack", async ({ page }) => {
  const email = process.env.E2E_USER_EMAIL || "";
  const password = process.env.E2E_USER_PASSWORD || "";
  expect(email, "E2E_USER_EMAIL jest wymagane").not.toBe("");
  expect(password, "E2E_USER_PASSWORD jest wymagane").not.toBe("");

  await openSessionViaApi(page, email, password);
  await expect(page.getByRole("link", { name: /Kandydaci/i }).first()).toBeVisible();

  // API ustawiło ciasteczko `nexus_access` (HttpOnly), więc middleware wpuszcza
  // na chronioną trasę zamiast odsyłać na /login, a token nie trafił do JS.
  const cookies = await page.context().cookies();
  const session = cookies.find((cookie) => cookie.name === "nexus_access");
  expect(session?.httpOnly).toBe(true);
  expect(await page.evaluate(() => window.localStorage.getItem("access_token"))).toBeNull();
  await page.goto("/candidates");
  await expect(page).not.toHaveURL(/\/login/);
});
