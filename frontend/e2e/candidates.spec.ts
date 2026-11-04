import { test, expect } from "@playwright/test";

const PASSWORD = process.env.E2E_USER_PASSWORD || "";

test.describe("Candidates flow", () => {
  test.skip(!PASSWORD, "Set E2E_USER_PASSWORD to run candidates tests");

  test("lista kandydatów ładuje się z talent-radar importu", async ({ page }) => {
    await page.goto("/candidates");
    await expect(page.getByRole("heading", { name: /Kandydaci/i })).toBeVisible();
    // After Phase 7a import there should be 30k+ candidates; the total counter shows "X w bazie"
    const totalText = await page
      .getByText(/\d[\d\s]*\s*w bazie/i)
      .first()
      .textContent();
    expect(totalText).toBeTruthy();
  });

  test("konto tylko do odczytu nie ma eksportu w menu „Importuj”", async ({ page }) => {
    await page.goto("/candidates");
    await page.getByRole("button", { name: /Importuj/ }).click();
    await expect(page.getByRole("menuitem", { name: "Import CSV" })).toBeVisible();
    // Produkcja, publiczne logi: eksport danych osobowych nie ma prawa tu zadziałać.
    await expect(page.getByRole("menuitem", { name: /^Eksportuj wyniki/ })).toHaveCount(0);
  });

  test("filtry stoją paskiem nad tabelą", async ({ page }) => {
    await page.goto("/candidates");
    const bar = page.getByRole("region", { name: "Filtry kandydatów" });
    await expect(bar).toBeVisible();
    await bar.getByRole("button", { name: /^Lokalizacja/ }).click();
    await expect(page.getByRole("dialog").getByLabel("Miasto")).toBeVisible();
  });

  test("quick view przechodzi między kandydatami i oddaje fokus", async ({ page }) => {
    await page.goto("/candidates");

    const firstRow = page.locator('[data-testid^="candidate-row-"]').first();
    await firstRow.focus();
    await firstRow.press("Enter");

    const quickView = page.getByTestId("candidate-quick-view");
    await expect(quickView).toBeVisible();
    await expect(quickView.getByText(/^1 z /)).toBeVisible();
    await quickView.getByRole("button", { name: "Następny kandydat" }).click();
    await expect(quickView.getByText(/^2 z /)).toBeVisible();

    await page.keyboard.press("k");
    await expect(quickView.getByText(/^1 z /)).toBeVisible();

    for (let index = 0; index < 12; index += 1) await page.keyboard.press("Tab");
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]')))).toBe(true);

    await quickView.getByRole("button", { name: "Zamknij szybki podgląd" }).click();
    await expect(quickView).toBeHidden();
    await expect(firstRow).toBeFocused();
  });

  // Od 13.10.2026 (E5) sześć zakładek: CV osobno od Dokumentów.
  test("pełny profil ma sześć sekcji i obsługuje legacy chat link", async ({ page }) => {
    await page.goto("/candidates");

    const firstRow = page.locator('[data-testid^="candidate-row-"]').first();
    await firstRow.focus();
    await firstRow.press("Enter");
    await page.getByTestId("candidate-quick-view").getByRole("button", { name: "Otwórz profil" }).click();
    await expect(page).toHaveURL(/\/candidates\/\d+\?(?:.*&)?tab=summary/);

    for (const section of [/^Przegląd/, /^Rekrutacje/, /^Screening/, /^Notatki/, /^CV/, /^Dokumenty/]) {
      await expect(page.getByRole("tab", { name: section })).toBeVisible();
    }

    const candidateId = page.url().match(/\/candidates\/(\d+)/)?.[1];
    expect(candidateId).toBeTruthy();
    await page.goto(`/candidates/${candidateId}?tab=chat&msg=123`);
    await expect(page).toHaveURL(/tab=activity.*activity=chat|activity=chat.*tab=activity/);
    await expect(page.getByRole("tab", { name: /^Notatki/ })).toHaveAttribute("aria-selected", "true");
  });

  test("quick view rozróżnia 403, 404 i pozwala ponowić po 500", async ({ page }) => {
    await page.goto("/candidates");

    const firstRow = page.locator('[data-testid^="candidate-row-"]').first();
    const testId = await firstRow.getAttribute("data-testid");
    const candidateId = testId?.replace("candidate-row-", "");
    expect(candidateId).toBeTruthy();
    const detailUrl = new RegExp(`/api/candidates/${candidateId}/quick-view(?:\\?.*)?$`);

    for (const scenario of [
      { status: 403, message: "Nie masz dostępu do tego profilu" },
      { status: 404, message: "Nie znaleziono kandydata" },
    ]) {
      await page.route(detailUrl, (route) =>
        route.fulfill({ status: scenario.status, contentType: "application/json", body: '{"detail":"test"}' }),
      );
      await firstRow.focus();
      await firstRow.press("Enter");
      await expect(page.getByRole("alert").getByRole("heading", { name: scenario.message })).toBeVisible();
      await page.getByRole("button", { name: "Zamknij szybki podgląd" }).click();
      await page.unroute(detailUrl);
      await page.reload();
    }

    let allowSuccess = false;
    await page.route(detailUrl, async (route) => {
      if (!allowSuccess) {
        await route.fulfill({ status: 500, contentType: "application/json", body: '{"detail":"test"}' });
        return;
      }
      await route.continue();
    });
    await page.locator('[data-testid^="candidate-row-"]').first().focus();
    await page.locator('[data-testid^="candidate-row-"]').first().press("Enter");
    await expect(page.getByRole("heading", { name: "Nie udało się otworzyć podglądu" })).toBeVisible();
    allowSuccess = true;
    await page.getByRole("button", { name: "Spróbuj ponownie" }).click();
    await expect(page.getByTestId("candidate-quick-view").getByRole("heading").first()).toBeVisible();
  });
});
