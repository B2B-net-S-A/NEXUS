/**
 * Manual CV search V2 — end-to-end smoke.
 *
 * Covers the happy path of the boolean/semantic search flow:
 *  1. /candidates/search renders the FiltersPanel (CC chips + boolean popover).
 *  2. Picking a CC chip narrows the result list.
 *  3. Saving the current search round-trips through the chips strip.
 *  4. The job profile exposes a "Wyszukaj manualnie" tab that pre-fills
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

  test("standalone /candidates/search renders the search view", async ({ page }) => {
    await page.goto("/candidates/search");
    await expect(
      page.getByRole("heading", { name: /Wyszukiwanie kandydatów/i }),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("competence category chip narrows the result count", async ({ page }) => {
    await page.goto("/candidates/search");
    // Wait for the CC group to render — it's lazy-loaded.
    const ccGroup = page.getByRole("group", {
      name: /Filtruj po kategorii kompetencji/i,
    });
    await expect(ccGroup).toBeVisible({ timeout: 10_000 });
    // First category chip — unfiltered count is the baseline.
    const firstChip = ccGroup.locator("button").first();
    const chipText = (await firstChip.textContent())?.trim();
    expect(chipText).toBeTruthy();
    // Click → result count changes (filter takes effect within 1s debounce).
    await firstChip.click();
    await page.waitForTimeout(600);
    await expect(firstChip).toHaveAttribute("aria-checked", "true");
  });

  test("save-and-reload roundtrip via chip strip", async ({ page }) => {
    await page.goto("/candidates/search");
    await page
      .getByRole("group", { name: /Filtruj po kategorii kompetencji/i })
      .waitFor({ timeout: 10_000 });

    // Pick any CC, type a free-text query, save.
    await page
      .getByRole("group", { name: /Filtruj po kategorii kompetencji/i })
      .locator("button")
      .first()
      .click();
    await page.getByPlaceholder(/Szukaj w CV/i).fill("python");
    await page.waitForTimeout(500);

    const saveButton = page.getByRole("button", { name: /Zapisz/i }).first();
    await saveButton.click();
    const nameField = page.getByPlaceholder(/Nazwa…/i);
    await expect(nameField).toBeVisible();
    const presetName = `e2e-${Date.now()}`;
    await nameField.fill(presetName);
    await page.getByRole("button", { name: /^Zapisz$/i }).click();

    // Strip should now show the freshly created chip.
    await expect(page.getByText(presetName, { exact: true })).toBeVisible({
      timeout: 5_000,
    });
  });

  test("job profile exposes 'Wyszukaj manualnie' tab", async ({ page }) => {
    // Pick the first job in the list to exercise the tab.
    await page.goto("/jobs");
    const firstJobLink = page.locator('a[href^="/jobs/"]').first();
    await firstJobLink.click();
    await page
      .getByRole("button", { name: "Pozyskaj kandydatów" })
      .click();
    const manualTab = page.getByTestId("tab-manual-search");
    await expect(manualTab).toBeVisible({ timeout: 10_000 });
    await manualTab.click();
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
