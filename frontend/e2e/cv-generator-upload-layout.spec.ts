import { expect, test, type Page } from "@playwright/test";

// Uses the existing authenticated setup. Opening/cancelling a picker is local:
// no file is uploaded, no CV is generated, and no business record is changed.
async function expectShellInViewport(page: Page) {
  await expect.poll(() => page.evaluate(() => {
    const shell = document.querySelector(".app-shell-root")!;
    const rect = shell.getBoundingClientRect();
    return {
      documentOverflow: document.documentElement.scrollHeight - innerHeight,
      windowScroll: scrollY,
      shellTop: rect.top,
      shellBottom: rect.bottom,
      viewportHeight: innerHeight,
    };
  })).toEqual({
    documentOverflow: 0,
    windowScroll: 0,
    shellTop: 0,
    shellBottom: page.viewportSize()!.height,
    viewportHeight: page.viewportSize()!.height,
  });
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 1366, height: 650 }]) {
  test(`file pickers preserve the CV generator layout at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/cv-generator");
    await page.getByRole("radio", { name: /Old \(upload plików\)/ }).click();
    const champion = page.getByText("Upuść DOCX championa tutaj lub kliknij, by wybrać", { exact: true });
    await expect(champion).toBeVisible();
    // The entry animation temporarily provides a containing block. Wait until
    // it finishes so it cannot conceal an unanchored absolute file input.
    await page.locator("main > div").evaluate(async (element) => {
      await Promise.all(element.getAnimations().map((animation) => animation.finished));
    });

    for (const trigger of [
      champion,
      page.getByText("Upuść CV tutaj lub kliknij, by wybrać plik", { exact: true }),
      page.getByText("Wybierz zrzut (PNG / JPEG)", { exact: true }),
      champion,
    ]) {
      // Start elsewhere in the form: the regression detached the input's
      // position from its label once main had been scrolled.
      await page.getByLabel("Nice-to-have", { exact: true }).click();
      await trigger.scrollIntoViewIfNeeded();
      const before = await page.locator("main").evaluate((element) => element.scrollTop);
      const chooserPromise = page.waitForEvent("filechooser");
      await trigger.click();
      await (await chooserPromise).setFiles([]);
      await expectShellInViewport(page);
      await expect.poll(() => page.locator("main").evaluate((element) => element.scrollTop)).toBe(before);
    }

    // Continue editing without a refresh after cancelling the picker.
    const requirements = page.getByLabel("Must-have", { exact: true });
    await requirements.fill("Kubernetes");
    await expect(requirements).toHaveValue("Kubernetes");
    await expectShellInViewport(page);
  });
}
