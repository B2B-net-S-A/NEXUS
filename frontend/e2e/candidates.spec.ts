import { test, expect, Page } from "@playwright/test";

const EMAIL = process.env.E2E_USER_EMAIL || "artur@b2bnet.pl";
const PASSWORD = process.env.E2E_USER_PASSWORD || "";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(EMAIL);
  await page
    .getByLabel(/hasło/i)
    .or(page.getByLabel(/password/i))
    .fill(PASSWORD);
  await page.getByRole("button", { name: /zaloguj|sign in|login/i }).click();
  await page.waitForURL(/\/(?:$|dashboard)/, { timeout: 15_000 });
}

test.describe("Candidates flow", () => {
  test.skip(!PASSWORD, "Set E2E_USER_PASSWORD to run candidates tests");

  test("lista kandydatów ładuje się z talent-radar importu", async ({ page }) => {
    await login(page);
    await page.goto("/candidates");
    await expect(page.getByRole("heading", { name: /Kandydaci/i })).toBeVisible();
    // After Phase 7a import there should be 30k+ candidates; the total counter shows "X w bazie"
    const totalText = await page
      .getByText(/\d[\d\s]*\s*w bazie/i)
      .first()
      .textContent();
    expect(totalText).toBeTruthy();
  });

  test("eksport wyników i import są dostępne z hierarchicznego toolbaru", async ({ page }) => {
    await login(page);
    await page.goto("/candidates");
    await page.getByRole("button", { name: "Więcej" }).click();
    await expect(page.getByRole("button", { name: "Eksportuj wyniki CSV" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Eksportuj wyniki XLSX" })).toBeVisible();

    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Importuj" }).click();
    await expect(page.getByRole("button", { name: "Import CSV" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Bulk CV" })).toBeVisible();
  });

  test("SavedSearchPicker Filtry button widoczny", async ({ page }) => {
    await login(page);
    await page.goto("/candidates");
    await expect(page.getByRole("button", { name: /Filtry/i })).toBeVisible();
  });

  test("quick view zachowuje listę, przechodzi przez granicę strony i oddaje fokus", async ({ page }) => {
    await login(page);
    await page.goto("/candidates?view=list");

    const scroller = page.getByTestId("candidate-list-scroll");
    await expect(scroller).toBeVisible();
    await scroller.evaluate((node) => {
      node.scrollTop = node.scrollHeight;
    });

    const lastRow = page.locator('[data-testid^="candidate-row-"][data-index="19"]');
    await expect(lastRow).toBeVisible();
    const trigger = lastRow.getByRole("button").first();
    await trigger.click();

    const quickView = page.getByTestId("candidate-quick-view");
    await expect(quickView).toBeVisible();
    await expect(quickView.getByText(/^20 z /)).toBeVisible();
    await quickView.getByRole("button", { name: "Następny kandydat" }).click();
    await expect(quickView.getByText(/^21 z /)).toBeVisible();

    await page.keyboard.press("k");
    await expect(quickView.getByText(/^20 z /)).toBeVisible();
    await expect(quickView.getByRole("button", { name: "Zamknij szybki podgląd" })).toHaveCount(1);

    for (let index = 0; index < 12; index += 1) await page.keyboard.press("Tab");
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]')))).toBe(true);

    await quickView.getByRole("button", { name: "Zamknij szybki podgląd" }).click();
    await expect(quickView).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("pełny profil ma pięć sekcji i obsługuje legacy chat link", async ({ page }) => {
    await login(page);
    await page.goto("/candidates?view=list");

    const firstRow = page.locator('[data-testid^="candidate-row-"]').first();
    await firstRow.getByRole("button").first().click();
    await page.getByTestId("candidate-quick-view").getByRole("button", { name: "Pełny profil" }).click();
    await expect(page).toHaveURL(/\/candidates\/\d+\?tab=summary/);

    for (const section of ["Podsumowanie", "Rekrutacje", "Aktywność", "Dopasowanie", "Pliki i umowy"]) {
      await expect(page.getByRole("tab", { name: new RegExp(section) })).toBeVisible();
    }

    const candidateId = page.url().match(/\/candidates\/(\d+)/)?.[1];
    expect(candidateId).toBeTruthy();
    await page.goto(`/candidates/${candidateId}?tab=chat&msg=123`);
    await expect(page).toHaveURL(/tab=activity.*activity=chat|activity=chat.*tab=activity/);
    await expect(page.getByRole("tab", { name: /Aktywność/ })).toHaveAttribute("aria-selected", "true");
  });

  test("eksportuje dokładnie zaznaczonego kandydata", async ({ page }) => {
    await login(page);
    await page.goto("/candidates?view=list");

    const firstRow = page.locator('[data-testid^="candidate-row-"]').first();
    await firstRow.getByRole("checkbox").check();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: /Eksportuj zaznaczone \(1\)/ }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.csv$/);
  });

  test("quick view rozróżnia 403, 404 i pozwala ponowić po 500", async ({ page }) => {
    await login(page);
    await page.goto("/candidates?view=list");

    const firstRow = page.locator('[data-testid^="candidate-row-"]').first();
    const testId = await firstRow.getAttribute("data-testid");
    const candidateId = testId?.replace("candidate-row-", "");
    expect(candidateId).toBeTruthy();
    const detailUrl = new RegExp(`/api/candidates/${candidateId}(?:\\?.*)?$`);

    for (const scenario of [
      { status: 403, message: "Nie masz dostępu do tego profilu" },
      { status: 404, message: "Nie znaleziono kandydata" },
    ]) {
      await page.route(detailUrl, (route) =>
        route.fulfill({ status: scenario.status, contentType: "application/json", body: '{"detail":"test"}' }),
      );
      await firstRow.getByRole("button").first().click();
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
    await page.locator('[data-testid^="candidate-row-"]').first().getByRole("button").first().click();
    await expect(page.getByRole("heading", { name: "Nie udało się otworzyć podglądu" })).toBeVisible();
    allowSuccess = true;
    await page.getByRole("button", { name: "Spróbuj ponownie" }).click();
    await expect(page.getByTestId("candidate-quick-view").getByRole("heading").first()).toBeVisible();
  });
});
