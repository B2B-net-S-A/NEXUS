import { expect, type Page } from "@playwright/test";

/**
 * Adres pierwszej rekrutacji z listy `/jobs`. Scenariusze odczytu na żywej
 * instancji nie zakładają konkretnego id w bazie. Filtr po numerze, bo lista
 * linkuje też `/jobs/umowy-przedwstepne`.
 */
export async function firstJobPath(page: Page): Promise<string> {
  await page.goto("/jobs");
  await expect(page.getByTestId("job-row-client").first()).toBeVisible({ timeout: 15_000 });
  const path = await page
    .locator('a[href^="/jobs/"]')
    .evaluateAll((links) =>
      links.map((link) => link.getAttribute("href") ?? "").find((href) => /^\/jobs\/\d+/.test(href))
    );
  expect(path, "lista /jobs nie ma żadnej rekrutacji").toBeTruthy();
  return (path as string).split("?")[0];
}
