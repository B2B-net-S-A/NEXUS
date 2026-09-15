import { test, expect } from "@playwright/test";

import { fetchAuthMethods, type AuthMethods } from "./helpers/session";

const EMAIL = process.env.E2E_USER_EMAIL || "artur@b2bnet.pl";
const PASSWORD = process.env.E2E_USER_PASSWORD || "";

test.describe("Authentication", () => {
  test.skip(!PASSWORD, "Set E2E_USER_PASSWORD to run auth tests");
  // Ekran logowania oglądamy bez sesji — z zapisanym stanem setupu sonda sesji
  // przekierowuje z /login, zanim formularz się pokaże.
  test.use({ storageState: { cookies: [], origins: [] } });

  let methods: AuthMethods;
  test.beforeAll(async () => {
    methods = await fetchAuthMethods();
  });

  test("login page renders", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: /Nexus/i }).first()).toBeVisible();
    if (methods.password) {
      await expect(page.getByLabel(/email/i)).toBeVisible();
      await expect(page.getByLabel(/hasło/i).or(page.getByLabel(/password/i))).toBeVisible();
    } else {
      // Tryb SSO-only (produkcja): jedyną drogą jest Microsoft, formularza hasła nie ma.
      await expect(page.getByRole("button", { name: "Zaloguj się przez Microsoft" })).toBeVisible();
      await expect(page.locator("#login-password")).toHaveCount(0);
    }
  });

  test("valid login redirects to dashboard", async ({ page }) => {
    test.skip(
      !methods.password,
      "Logowanie hasłem wyłączone (SSO-only) — sesję E2E zakłada setup przez API."
    );
    await page.goto("/login");
    await page.getByLabel(/email/i).fill(EMAIL);
    await page
      .getByLabel(/hasło/i)
      .or(page.getByLabel(/password/i))
      .fill(PASSWORD);
    await page.getByRole("button", { name: "Zaloguj się", exact: true }).click();
    // After login should land on dashboard
    await expect(page).toHaveURL(/\/(?:$|dashboard)/, { timeout: 15_000 });
    await expect(page.getByText(/Dashboard|Kandydaci|Rekrutacje/).first()).toBeVisible();
  });
});
