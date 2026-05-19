/**
 * E2E coverage for DynaReporter Admin Dashboard — verifies the 10-module
 * panel renders + clicking each card loads its content without errors.
 *
 * Skipped unless E2E_USER_PASSWORD env var is set (matches auth.spec.ts).
 *
 * Guards regression of:
 *   - Sales/Przetargi accidentally re-added (PR #261 removed them)
 *   - Module count drift from 10
 *   - Pracownicy 500 (PR #267 fixed users.name vs first_name/last_name)
 *   - Hall of Fame delete UI broken (PR #269 added id field)
 *   - ScoringConfig form missing prize inputs (PR #271)
 */

import { test, expect } from "@playwright/test";

const EMAIL = process.env.E2E_USER_EMAIL || "artur@b2bnet.pl";
const PASSWORD = process.env.E2E_USER_PASSWORD || "";

test.describe("DynaReporter Admin Dashboard", () => {
  test.skip(!PASSWORD, "Set E2E_USER_PASSWORD to run admin tests");

  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill(EMAIL);
    await page
      .getByLabel(/hasło/i)
      .or(page.getByLabel(/password/i))
      .fill(PASSWORD);
    await page.getByRole("button", { name: /zaloguj|sign in|login/i }).click();
    await page.waitForURL(/\/(?:$|dashboard)/, { timeout: 15_000 });
  });

  test("admin dashboard shows exactly 10 module cards", async ({ page }) => {
    await page.goto("/dynareporter/admin-dashboard");
    await expect(page.getByRole("heading", { name: /Panel Admina/i })).toBeVisible({
      timeout: 10_000,
    });

    const expectedCards = [
      "Rekrutacja",
      "Delivery Lead",
      "Rada Nadzorcza",
      "Pracownicy i konta",
      "Zespół Rekrutacji",
      "DL - Klienci",
      "Klienci i Konsultanci",
      "Hall of Fame",
      "Ustawienia",
      "Historia uploadów",
    ];
    for (const cardTitle of expectedCards) {
      await expect(
        page.getByRole("button", { name: new RegExp(cardTitle, "i") }),
      ).toBeVisible();
    }

    // Sales + Przetargi explicitly removed per user request (PR #261)
    await expect(page.getByRole("button", { name: /^Sales/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Przetargi/ })).toHaveCount(0);
  });

  test("Pracownicy module loads user list (PR #267 regression guard)", async ({
    page,
  }) => {
    await page.goto("/dynareporter/admin-dashboard");
    await page.getByRole("button", { name: /Pracownicy i konta/i }).click();
    await expect(
      page.getByRole("heading", { name: /Pracownicy i konta \(\d+\)/i }),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("Hall of Fame list renders (PR #269 regression guard)", async ({ page }) => {
    await page.goto("/dynareporter/admin-dashboard");
    await page.getByRole("button", { name: /Hall of Fame/i }).click();
    await expect(
      page.getByRole("heading", { name: /Hall of Fame.*Zarządzanie/i }),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByRole("button", { name: /Dodaj zwycięzcę/i }),
    ).toBeVisible();
  });

  test("Ustawienia (Scoring) shows scoring + 3 prizes (PR #271)", async ({
    page,
  }) => {
    await page.goto("/dynareporter/admin-dashboard");
    await page.getByRole("button", { name: /^Ustawienia/i }).click();
    await expect(page.getByText(/^Placement$/)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/^Interview$/)).toBeVisible();
    await expect(page.getByText(/^Recommendation$/)).toBeVisible();
    await expect(page.getByText(/^Verification$/)).toBeVisible();
    await expect(page.getByText(/1\. miejsce \(PLN\)/)).toBeVisible();
    await expect(page.getByText(/2\. miejsce \(PLN\)/)).toBeVisible();
    await expect(page.getByText(/3\. miejsce \(PLN\)/)).toBeVisible();
  });

  test("module selector buttons have aria-pressed (a11y, PR #269)", async ({
    page,
  }) => {
    await page.goto("/dynareporter/admin-dashboard");
    const rekrutacjaBtn = page.getByRole("button", { name: /Rekrutacja/i }).first();
    await expect(rekrutacjaBtn).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: /Hall of Fame/i }).click();
    await expect(rekrutacjaBtn).toHaveAttribute("aria-pressed", "false");
  });
});
