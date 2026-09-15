/**
 * Uprawnienia: rekruter dostaje odmowę w API i w UI, administrator — dostęp.
 *
 * `@stack`. Scenariusz sprawdza oba poziomy naraz, bo rozjazd UI ↔ API to
 * klasa błędu, którą audyt wskazał jako niepokrytą: link widoczny, a klik 403
 * (albo odwrotnie — strona otwarta, a API odmawia bez komunikatu).
 */
import { test, expect, expectStatus } from "./helpers/api";

test.describe("Uprawnienia ról @stack", () => {
  test("rekruter nie czyta listy użytkowników, administrator tak", async ({ admin, apiAs }) => {
    const recruiter = await apiAs("recruiter");

    await expectStatus(await recruiter.api.get("/api/admin/users"), 403, "rekruter → admin/users");
    await expectStatus(await admin.api.get("/api/admin/users"), 200, "admin → admin/users");
  });

  test("rekruter otwierający /manager widzi stronę braku uprawnień", async ({
    apiAs,
    browser,
  }) => {
    const recruiter = await apiAs("recruiter");
    const login = await recruiter.api.post("/api/auth/login", {
      data: { email: recruiter.email, password: process.env.E2E_USER_PASSWORD },
    });
    await expectStatus(login, 200, "logowanie rekrutera do sesji przeglądarki");
    const { access_token: token } = (await login.json()) as { access_token: string };

    // Sesja przeglądarki rekrutera: token w localStorage (klient API) i cookie
    // `nexus_access` (middleware) — tak jak po zalogowaniu przez UI.
    const context = await browser.newContext({ storageState: undefined });
    const baseURL = process.env.E2E_BASE_URL || "https://nexus.dynaminds.pl";
    await context.addCookies([{ name: "nexus_access", value: token, url: baseURL }]);
    await context.addInitScript(
      ([accessToken]) => {
        window.localStorage.setItem("access_token", accessToken);
        window.localStorage.setItem("onboarding_completed", "true");
      },
      [token]
    );
    const page = await context.newPage();

    await page.goto(`${baseURL}/manager`);
    await expect(page).toHaveURL(/\/403/);
    await expect(page.getByRole("heading", { name: /403 — Brak uprawnień/ })).toBeVisible();
    await context.close();
  });
});
