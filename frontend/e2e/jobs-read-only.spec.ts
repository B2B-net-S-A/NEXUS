/**
 * Rekrutacje na żywej instancji: lista, Tablica, Propozycje z bazy, Profil Championa.
 * Tylko odczyt (`prod-smoke`); rekrutację bierzemy z listy, żeby test nie zależał
 * od konkretnego id w bazie.
 */
import { test, expect } from "@playwright/test";

import { firstJobPath } from "./helpers/first-job";

const PASSWORD = process.env.E2E_USER_PASSWORD || "";

test.describe("Rekrutacje — odczyt", () => {
  test.skip(!PASSWORD, "Set E2E_USER_PASSWORD to run");

  test("lista otwiera rekrutację z etapami Tablicy", async ({ page }) => {
    await page.goto(await firstJobPath(page));
    await expect(page.getByRole("button", { name: /Propozycje z bazy/ })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("heading", { name: "Screening" })).toBeVisible();
  });

  test("stary adres ?tab=ai-matching prowadzi do „Propozycji z bazy”", async ({ page }) => {
    await page.goto(`${await firstJobPath(page)}?tab=ai-matching`);
    await expect(page).toHaveURL(/seg=proposals/);
    const segment = page.getByTestId("proposals-segment");
    await expect(segment).toBeVisible({ timeout: 15_000 });
    await expect(segment.getByRole("group", { name: "Źródło propozycji" })).toBeVisible();
  });

  test("Profil Championa ma zakładki z briefem", async ({ page }) => {
    await page.goto(`${await firstJobPath(page)}?tab=champion`);
    const tabs = page.getByRole("tablist", { name: "Profil Championa" });
    await expect(tabs.getByRole("tab", { name: "Brief" })).toBeVisible({ timeout: 15_000 });
    await expect(tabs.getByRole("tab", { name: /Technologie po ludzku/ })).toBeVisible();
  });
});
