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

test.describe("Recommendations flow", () => {
  test.skip(!PASSWORD, "Set E2E_USER_PASSWORD to run recommendations tests");

  test("job detail „Propozycje z bazy” segment merges recommendations and admin AI tools", async ({
    page,
  }) => {
    await login(page);
    // Go to first job (Senior Angular Developer from seed). Wersja 3: dawna
    // zakładka „AI Matching" to segment „Propozycje z bazy" tabeli — stary
    // adres `?tab=ai-matching` nadal do niego prowadzi.
    await page.goto("/jobs/1?tab=ai-matching");
    const segment = page.getByTestId("proposals-segment");
    await expect(segment).toBeVisible();
    await expect(page).toHaveURL(/seg=proposals/);
    // Rekomendowani są jednym ze źródeł listy; odświeża je przycisk segmentu.
    await expect(
      segment.getByRole("button", { name: /Odśwież rekomendacje/i })
    ).toBeVisible();
    await expect(
      segment.getByRole("group", { name: "Źródło propozycji" }).getByRole("button", { name: /Rekomendowani/ })
    ).toBeVisible();
  });

  test("refreshing recommendations brings proposals into the table", async ({ page }) => {
    await login(page);
    await page.goto("/jobs/1?seg=proposals");
    const segment = page.getByTestId("proposals-segment");
    await segment.getByRole("button", { name: /Odśwież rekomendacje/i }).click();
    // Rekomendacje liczą się w tle — wiersze pojawiają się w tabeli propozycji.
    await expect(
      segment.getByRole("grid", { name: "Propozycje z bazy" }).getByRole("row").nth(1)
    ).toBeVisible({ timeout: 30_000 });
  });
});
