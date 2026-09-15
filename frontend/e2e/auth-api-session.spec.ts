/**
 * Ścieżka sesji, której setup używa na produkcji SSO-only: token z
 * `POST /api/auth/login` + sonda sesji ekranu /login. Produkcja nie ma
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

  // Sonda sesji odtworzyła cookie `nexus_access`, więc middleware wpuszcza na
  // chronioną trasę zamiast odsyłać na /login.
  const cookies = await page.context().cookies();
  expect(cookies.some((cookie) => cookie.name === "nexus_access")).toBe(true);
  await page.goto("/candidates");
  await expect(page).not.toHaveURL(/\/login/);
});
