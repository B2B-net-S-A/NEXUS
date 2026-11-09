/**
 * Manual CV search V2 — end-to-end smoke.
 *
 * Covers the happy path of the boolean/semantic search flow:
 *  1. The old /candidates/search address lands on the single candidates list
 *     (22.09.2026) with the search state carried over.
 *  2. The recruitment window exposes the "Szukaj ręcznie" tab.
 *
 * NB: the standalone toolbar entry link on /candidates was removed — it
 * duplicated the in-list "Filtry" panel. The route stays reachable directly
 * and via the job-profile tab below.
 *
 * Runs against a live Nexus instance — uses the persisted auth state from
 * e2e/.auth/state.json (set up by auth.setup.ts).
 */
import { test, expect } from "@playwright/test";

import { firstJobPath } from "./helpers/first-job";

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

  test("okno rekrutacji ma zakładkę „Szukaj ręcznie”", async ({ page }) => {
    // 14.10.2026: „Szukaj ręcznie" to zakładka okna „Kandydaci do dodania”
    // (`?win=add&wintab=manual`), nie osobne okno.
    await page.goto(`${await firstJobPath(page)}?win=add&wintab=manual`);
    const manualSearch = page.getByTestId("manual-search-tab");
    await expect(manualSearch).toBeVisible({ timeout: 10_000 });
    await expect(manualSearch.getByLabel("Szukaj kandydatów")).toBeVisible({ timeout: 10_000 });
  });
});
