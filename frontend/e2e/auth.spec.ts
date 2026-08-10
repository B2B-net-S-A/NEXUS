import { test, expect } from "@playwright/test";

const EMAIL = process.env.E2E_USER_EMAIL || "artur@b2bnet.pl";
const PASSWORD = process.env.E2E_USER_PASSWORD || "";

test.describe("Authentication", () => {
  test.skip(!PASSWORD, "Set E2E_USER_PASSWORD to run auth tests");

  test("login page renders", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: /Nexus/i }).first()).toBeVisible();
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expect(page.getByLabel(/hasło/i).or(page.getByLabel(/password/i))).toBeVisible();
  });

  test("valid login redirects to dashboard", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill(EMAIL);
    await page
      .getByLabel(/hasło/i)
      .or(page.getByLabel(/password/i))
      .fill(PASSWORD);
    await page.getByRole("button", { name: /zaloguj|sign in|login/i }).click();
    // After login should land on dashboard
    await expect(page).toHaveURL(/\/(?:$|dashboard)/, { timeout: 15_000 });
    await expect(page.getByText(/Dashboard|Kandydaci|Rekrutacje/).first()).toBeVisible();
  });
});
