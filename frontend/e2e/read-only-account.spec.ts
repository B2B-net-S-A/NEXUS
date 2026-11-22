/**
 * Konto E2E na produkcji: rola `automation`, czyli podgląd bez kwot, zapisu i eksportu.
 *
 * Hasło tego konta leży w sekretach repo i omija SSO (lista
 * `PASSWORD_LOGIN_BREAK_GLASS_EMAILS`), więc rola jest jedyną ochroną danych, gdyby
 * wyciekło. Ten plik pada, gdy ktoś podniesie kontu uprawnienia, i pilnuje
 * bramki ekranu admina na żywej produkcji.
 */
import { test, expect } from "@playwright/test";

import { API_URL } from "./helpers/api";

const PASSWORD = process.env.E2E_USER_PASSWORD || "";

test.describe("Konto E2E tylko do odczytu", () => {
  test.skip(!PASSWORD, "Set E2E_USER_PASSWORD to run");

  test("ma wyłącznie rolę automation", async ({ page }) => {
    await page.goto("/candidates");
    // Sesja przeglądarki w ciasteczku HttpOnly — pytamy API z karty, token
    // nie istnieje w JS (od 22.11.2026).
    const me = await page.evaluate(async (api) => {
      const res = await fetch(`${api}/api/auth/me`, { credentials: "include" });
      return { status: res.status, body: res.ok ? await res.json() : null };
    }, API_URL);
    expect(me.status).toBe(200);
    const { role, roles } = me.body as { role: string; roles?: string[] };
    expect(role).toBe("automation");
    expect(roles ?? [role]).toEqual(["automation"]);
  });

  test("ustawienia rankingu odsyłają na 403", async ({ page }) => {
    await page.goto("/settings/scoring");
    await expect(page).toHaveURL(/\/403/);
    await expect(page.getByRole("heading", { name: /403/ })).toBeVisible();
  });
});
