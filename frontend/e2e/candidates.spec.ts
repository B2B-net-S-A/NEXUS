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

  test("eksport CSV pokazuje się w toolbarze", async ({ page }) => {
    await login(page);
    await page.goto("/candidates");
    // ExportDropdown from Phase 7b.4
    await expect(page.getByRole("button", { name: /Eksport/i })).toBeVisible();
    // Import CSV button also present
    await expect(page.getByRole("button", { name: /Import CSV/i })).toBeVisible();
  });

  test("SavedSearchPicker Filtry button widoczny", async ({ page }) => {
    await login(page);
    await page.goto("/candidates");
    await expect(page.getByRole("button", { name: /Filtry/i })).toBeVisible();
  });
});
