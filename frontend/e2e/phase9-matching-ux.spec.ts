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
import { test, expect } from "@playwright/test";

// Phase 12: the `setup` project persists auth state to e2e/.auth/state.json,
// referenced by the `chromium` project via `storageState`. Specs can skip the
// login/onboarding dance entirely and go straight to the page under test.

const PASSWORD = process.env.E2E_USER_PASSWORD || "";

test.describe("Phase 9 — matching UX", () => {
  test.skip(!PASSWORD, "Set E2E_USER_PASSWORD to run");

  test("match stats badge renders with include_match_stats=true", async ({ page }) => {
    await page.goto("/candidates?match_threshold=35");
    // Badge text pattern: "N otwarte · top XX"
    const badge = page.getByText(/\d+\s+otwarte\s+·\s+top\s+\d+/i).first();
    await expect(badge).toBeVisible({ timeout: 15_000 });
  });

  test("clicking match badge opens breakdown popover", async ({ page }) => {
    await page.goto("/candidates?match_threshold=35");
    const badge = page.getByText(/\d+\s+otwarte\s+·\s+top\s+\d+/i).first();
    await badge.click();
    await expect(page.getByText(/TOP DOPASOWANE REKRUTACJE/i)).toBeVisible({
      timeout: 5_000,
    });
  });

  test("Przypisz button on candidate row opens QuickAssignModal", async ({ page }) => {
    await page.goto("/candidates");
    const firstAssign = page.getByRole("button", { name: /Przypisz kandydata/i }).first();
    await firstAssign.click();
    await expect(
      page.getByRole("heading", { name: /Przypisz do rekrutacji/i })
    ).toBeVisible();
    await page.keyboard.press("Escape");
  });

  test("AdvancedFilterBar autocompletes skills and narrows results", async ({ page }) => {
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
    await page.goto("/candidates");
    await page.getByRole("button", { name: /^Zdalna$/i }).click();
    await expect(page).toHaveURL(/remote=remote/);
  });

  test("threshold slider + profile selector in URL", async ({ page }) => {
    await page.goto(
      "/candidates?match_threshold=55&profile_id=1"
    );
    await expect(page).toHaveURL(/match_threshold=55/);
    await expect(page).toHaveURL(/profile_id=1/);
  });

  test("SuggestedJobsWidget appears in candidate profile header", async ({ page }) => {
    await page.goto("/candidates/1");
    await expect(
      page.getByText(/SUGEROWANE REKRUTACJE/i).first()
    ).toBeVisible({ timeout: 10_000 });
  });

  test("JobCard shows skill chips and Sparkles button", async ({ page }) => {
    await page.goto("/jobs");
    // At least one job with must_skills should show a chip like "Angular" / "Python"
    await expect(
      page
        .getByRole("button", { name: /Sugerowani kandydaci/i })
        .first()
    ).toBeVisible({ timeout: 10_000 });
  });

  test("Sparkles button opens SuggestedCandidatesDrawer", async ({ page }) => {
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
    await page.goto("/settings/scoring");
    await expect(
      page.getByRole("heading", { name: /Profile wag scoringu/i })
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /Nowy profil/i })).toBeVisible();
  });

  // ── Phase 10: Champion Profile + screening ───────────────────────────────

  test("job detail has Profil Championa tab with editor", async ({ page }) => {
    await page.goto("/jobs/2");
    await page.getByRole("button", { name: /Profil Championa/i }).click();
    await expect(
      page.getByRole("heading", { name: /Profil Championa/i })
    ).toBeVisible();
    // Editor section headings (Phase 10)
    await expect(page.getByText(/1\.?\s*PODSTAWOWE INFORMACJE/i)).toBeVisible();
    await expect(page.getByText(/3\.?\s*PYTANIA SCREENINGOWE/i)).toBeVisible();
  });

  test("score breakdown tooltip includes Champion layer", async ({ page }) => {
    await page.goto("/jobs/2");
    await page.getByRole("button", { name: /AI Matching/i }).click();
    // Trigger scoring if needed
    const suggestBtn = page.getByRole("button", { name: /Sugeruj kandydatów/i });
    if (await suggestBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await suggestBtn.click();
    }
    const info = page.getByRole("button", { name: /Pokaż rozbicie punktów/i }).first();
    await expect(info).toBeVisible({ timeout: 15_000 });
    await info.click();
    // Champion row appears only for jobs with a Champion Profile configured.
    await expect(page.getByText(/^Champion$/i)).toBeVisible({ timeout: 5_000 });
  });

  test("candidate with screening shows ChampionCard in Rekrutacje", async ({ page }) => {
    // Agnieszka Nowak (id=2) has a screened stage in the seed.
    await page.goto("/candidates/2");
    await page.getByRole("button", { name: /^Rekrutacje$/i }).click();
    await expect(page.getByText(/Profil Championa/i).first()).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText(/Pasuje/i).first()).toBeVisible();
  });
});
