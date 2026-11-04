/**
 * Konto E2E na produkcji: rola `automation`, czyli podgląd bez kwot, zapisu i eksportu.
 *
 * Hasło tego konta leży w sekretach repo i omija SSO (lista
 * `PASSWORD_LOGIN_BREAK_GLASS_EMAILS`), więc rola jest jedyną ochroną danych, gdyby
 * wyciekło. Ten plik pada, gdy ktoś podniesie kontu uprawnienia, i pilnuje
 * bramki ekranu admina na żywej produkcji.
 */
import { request as playwrightRequest, test, expect } from "@playwright/test";

import { API_URL } from "./helpers/api";

const PASSWORD = process.env.E2E_USER_PASSWORD || "";

test.describe("Konto E2E tylko do odczytu", () => {
  test.skip(!PASSWORD, "Set E2E_USER_PASSWORD to run");

  test("ma wyłącznie rolę automation", async ({ page }) => {
    await page.goto("/candidates");
    const token = await page.evaluate(() => window.localStorage.getItem("access_token"));
    expect(token, "brak tokenu w localStorage").toBeTruthy();

    const api = await playwrightRequest.newContext({
      baseURL: API_URL,
      extraHTTPHeaders: { Authorization: `Bearer ${token}` },
    });
    const me = await api.get("/api/auth/me");
    expect(me.status()).toBe(200);
    const { role, roles } = (await me.json()) as { role: string; roles?: string[] };
    await api.dispose();
    expect(role).toBe("automation");
    expect(roles ?? [role]).toEqual(["automation"]);
  });

  test("ustawienia rankingu odsyłają na 403", async ({ page }) => {
    await page.goto("/settings/scoring");
    await expect(page).toHaveURL(/\/403/);
    await expect(page.getByRole("heading", { name: /403/ })).toBeVisible();
  });
});
