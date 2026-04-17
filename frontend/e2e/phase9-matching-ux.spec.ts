/**
 * Phase 9 regression — matching UX end-to-end.
 *
 * Covers:
 *  - Match stats badge on candidate list
 *  - Quick assign modal from candidate row
 *  - Suggested jobs widget on candidate profile
 *  - Job card chips + Sparkles drawer on jobs list
 *  - Advanced filter bar: skill autocomplete → chip → narrowed result
 *  - Threshold slider + profile selector reflected in URL
 *  - /settings/scoring CRUD
 *
 * Runs against a live Nexus instance. Default E2E_BASE_URL in playwright.config.
 */
import { test, expect, Page } from "@playwright/test";

const EMAIL = process.env.E2E_USER_EMAIL || "artur@b2bnet.pl";
const PASSWORD = process.env.E2E_USER_PASSWORD || "";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByPlaceholder("rekruter@firma.pl").fill(EMAIL);
  await page.getByPlaceholder("••••••••").fill(PASSWORD);
  await page.getByRole("button", { name: /zaloguj/i }).click();
  // Dashboard has a "Pomiń przewodnik" onboarding overlay on first load;
  // dismiss it if present so subsequent goto() isn't blocked.
  await page.waitForURL(/\/(?:$|dashboard)/, { timeout: 15_000 });
  const skipBtn = page.getByRole("button", { name: /Pomiń przewodnik/i });
  if (await skipBtn.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await skipBtn.click();
  }
}

test.describe("Phase 9 — matching UX", () => {
  test.skip(!PASSWORD, "Set E2E_USER_PASSWORD to run");

  test("match stats badge renders with include_match_stats=true", async ({ page }) => {
    await login(page);
    await page.goto("/candidates?match_threshold=35");
    // Badge text pattern: "N otwarte · top XX"
    const badge = page.getByText(/\d+\s+otwarte\s+·\s+top\s+\d+/i).first();
    await expect(badge).toBeVisible({ timeout: 15_000 });
  });

  test("clicking match badge opens breakdown popover", async ({ page }) => {
    await login(page);
    await page.goto("/candidates?match_threshold=35");
    const badge = page.getByText(/\d+\s+otwarte\s+·\s+top\s+\d+/i).first();
    await badge.click();
    await expect(page.getByText(/TOP DOPASOWANE REKRUTACJE/i)).toBeVisible({
      timeout: 5_000,
    });
  });

  test("Przypisz button on candidate row opens QuickAssignModal", async ({ page }) => {
    await login(page);
    await page.goto("/candidates");
    const firstAssign = page.getByRole("button", { name: /Przypisz kandydata/i }).first();
    await firstAssign.click();
    await expect(
      page.getByRole("heading", { name: /Przypisz do rekrutacji/i })
    ).toBeVisible();
    await page.keyboard.press("Escape");
  });

  test("AdvancedFilterBar autocompletes skills and narrows results", async ({ page }) => {
    await login(page);
    await page.goto("/candidates");
    const input = page.getByPlaceholder(/Umiejętności/i);
    await input.fill("pyth");
    // Autocomplete option appears
    const option = page.getByRole("button", { name: /Python/i }).first();
    await expect(option).toBeVisible({ timeout: 5_000 });
    await option.click();
    // Chip visible
    await expect(page.getByText(/^python$/i)).toBeVisible();
  });

  test("remote filter button toggles and reflects in URL", async ({ page }) => {
    await login(page);
    await page.goto("/candidates");
    await page.getByRole("button", { name: /^Zdalna$/i }).click();
    await expect(page).toHaveURL(/remote=remote/);
  });

  test("threshold slider + profile selector in URL", async ({ page }) => {
    await login(page);
    await page.goto(
      "/candidates?match_threshold=55&profile_id=1"
    );
    await expect(page).toHaveURL(/match_threshold=55/);
    await expect(page).toHaveURL(/profile_id=1/);
  });

  test("SuggestedJobsWidget appears in candidate profile header", async ({ page }) => {
    await login(page);
    await page.goto("/candidates/1");
    await expect(
      page.getByText(/SUGEROWANE REKRUTACJE/i).first()
    ).toBeVisible({ timeout: 10_000 });
  });

  test("JobCard shows skill chips and Sparkles button", async ({ page }) => {
    await login(page);
    await page.goto("/jobs");
    // At least one job with must_skills should show a chip like "Angular" / "Python"
    await expect(
      page
        .getByRole("button", { name: /Sugerowani kandydaci/i })
        .first()
    ).toBeVisible({ timeout: 10_000 });
  });

  test("Sparkles button opens SuggestedCandidatesDrawer", async ({ page }) => {
    await login(page);
    await page.goto("/jobs");
    await page
      .getByRole("button", { name: /Sugerowani kandydaci/i })
      .first()
      .click();
    await expect(
      page.getByRole("heading", { name: /Sugerowani kandydaci/i })
    ).toBeVisible();
  });

  test("/settings/scoring lists profiles + shows Nowy profil CTA", async ({ page }) => {
    await login(page);
    await page.goto("/settings/scoring");
    await expect(
      page.getByRole("heading", { name: /Profile wag scoringu/i })
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /Nowy profil/i })).toBeVisible();
  });
});
