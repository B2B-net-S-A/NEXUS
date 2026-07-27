/**
 * Phase 9 regression — matching UX end-to-end.
 *
 * Covers:
 *  - Match stats badge on candidate list
 *  - Quick assign modal from candidate row
 *  - Suggested jobs widget on candidate profile
 *  - Rekomendowani kandydaci widget on job detail (zakładka AI Matching)
 *  - Threshold slider + profile selector reflected in URL
 *  - /settings/scoring CRUD
 *  - Phase 10: Champion Profile + screening
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
    // Kolumna "match" (domyślnie widoczna) renderuje <MatchScoreBadge> obok
    // licznika "<dopasowane>/<wszystkie otwarte> ofert".
    const badge = page.getByText(/\d+\/\d+\s+ofert/i).first();
    await expect(badge).toBeVisible({ timeout: 15_000 });
  });

  test("Przypisz button on candidate row opens QuickAssignModal", async ({ page }) => {
    await page.goto("/candidates");
    // aria-label budowany per kandydat: "Przypisz <imię nazwisko> do oferty"
    // (widok tabeli) / "... do rekrutacji" (kafelki).
    const firstAssign = page
      .getByRole("button", { name: /^Przypisz .+ do (oferty|rekrutacji)$/i })
      .first();
    await firstAssign.click();
    await expect(
      page.getByRole("heading", { name: /Przypisz do rekrutacji/i })
    ).toBeVisible();
    await page.keyboard.press("Escape");
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

  test("job detail AI Matching tab shows SuggestedCandidatesWidget", async ({ page }) => {
    await page.goto("/jobs/2");
    await page.getByRole("button", { name: /AI Matching/i }).click();
    await expect(
      page.getByRole("heading", { name: /Rekomendowani kandydaci/i })
    ).toBeVisible({ timeout: 15_000 });
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
