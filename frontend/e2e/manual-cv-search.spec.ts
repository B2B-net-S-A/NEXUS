/**
 * Manual CV search V2 — end-to-end smoke.
 *
 * Covers the happy path of the boolean/semantic search flow:
 *  1. The old /candidates/search address lands on the single candidates list
 *     (22.09.2026) with the search state carried over.
 *  2. The job profile exposes a "Wyszukaj manualnie" tab that pre-fills
 *     filters from job metadata.
 *
 * NB: the standalone toolbar entry link on /candidates was removed — it
 * duplicated the in-list "Filtry" panel. The route stays reachable directly
 * and via the job-profile tab below.
 *
 * Runs against a live Nexus instance — uses the persisted auth state from
 * e2e/.auth/state.json (set up by auth.setup.ts).
 */
import { test, expect } from "@playwright/test";

const PASSWORD = process.env.E2E_USER_PASSWORD || "";

test.describe("Manual CV search V2", () => {
  test.skip(!PASSWORD, "Set E2E_USER_PASSWORD to run");

  test("stary adres /candidates/search prowadzi na listę z polem wyszukiwania", async ({ page }) => {
    // Od 22.09.2026 wyszukiwanie żyje na liście „Kandydaci"; stan `?s=`
    // przechodzi na parametry listy.
    await page.goto(`/candidates/search?s=${encodeURIComponent('{"q":"python"}')}`);
    await expect(page).toHaveURL(/\/candidates\?q=python/);
    await expect(page.getByLabel("Szukaj kandydatów")).toHaveValue("python");
  });

  test("job profile exposes 'Szukaj ręcznie' slide-over", async ({ page }) => {
    // Pick the first job in the list to exercise the slide-over.
    await page.goto("/jobs");
    const firstJobLink = page.locator('a[href^="/jobs/"]').first();
    await firstJobLink.click();
    // Wersja 3: dawna zakładka „Wyszukaj manualnie" to okno obok tabeli osób.
    await page.getByRole("button", { name: /Szukaj ręcznie/ }).first().click();
    const manualSearch = page.getByTestId("manual-search-slideover");
    await expect(manualSearch).toBeVisible({ timeout: 10_000 });
    // The embedded view shares the heading with /candidates/search.
    await expect(
      page.getByRole("heading", { name: /Wyszukiwanie kandydatów/i }),
    ).toBeVisible({ timeout: 10_000 });
    // Bulk-add bar shows up only after a row is selected; the checkbox column
    // is the differentiator from the standalone view.
    await page.waitForTimeout(800);
    const firstCheckbox = page.locator('input[type="checkbox"]').first();
    if (await firstCheckbox.isVisible()) {
      await firstCheckbox.check();
      await expect(page.getByText(/Wybrano/)).toBeVisible({ timeout: 3_000 });
    }
  });
});
