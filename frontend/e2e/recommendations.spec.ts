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

  test("job detail AI Matching tab shows SuggestedCandidatesWidget", async ({
    page,
  }) => {
    await login(page);
    // Go to first job (Senior Angular Developer from seed)
    await page.goto("/jobs/1");
    await page.getByRole("button", { name: /AI Matching/i }).click();
    // Phase 7b.2 widget header
    await expect(page.getByText(/Rekomendowani kandydaci/i)).toBeVisible();
    // Sugeruj kandydatów button
    await expect(
      page.getByRole("button", { name: /Sugeruj kandydat/i })
    ).toBeVisible();
    // Phase 7b.2 CriteriaPreviewModal trigger
    await expect(page.getByTestId("preview-criteria")).toBeVisible();
  });

  test("suggestion widget returns results after click", async ({ page }) => {
    await login(page);
    await page.goto("/jobs/1");
    await page.getByRole("button", { name: /AI Matching/i }).click();
    const suggest = page.getByTestId("suggest-candidates-btn");
    await suggest.click();
    // Wait for at least one candidate card (Phase 7a real data = 30k+ candidates)
    await expect(page.locator("text=/\\d+\\/100/").first()).toBeVisible({
      timeout: 30_000,
    });
  });
});
