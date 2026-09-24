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
  test(`file picker preserves the CV generator layout at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/cv-generator");
    // Generator v3: plik z dysku tylko dla osoby spoza bazy.
    await page.getByRole("button", { name: "Osoby nie ma w bazie? Wgraj jej plik CV" }).click();
    const dropzone = page.getByText("Upuść plik CV (PDF albo DOCX) albo wybierz z dysku", { exact: true });
    await expect(dropzone).toBeVisible();
    await page.locator("main > div").evaluate(async (element) => {
      await Promise.all(element.getAnimations().map((animation) => animation.finished));
    });

    for (let attempt = 0; attempt < 2; attempt += 1) {
      // Start elsewhere: the regression detached the input's position from its
      // label once main had been scrolled.
      await page.getByRole("button", { name: "Wróć do wyszukiwania osoby" }).scrollIntoViewIfNeeded();
      await dropzone.scrollIntoViewIfNeeded();
      const before = await page.locator("main").evaluate((element) => element.scrollTop);
      const chooserPromise = page.waitForEvent("filechooser");
      await dropzone.click();
      await (await chooserPromise).setFiles([]);
      await expectShellInViewport(page);
      await expect.poll(() => page.locator("main").evaluate((element) => element.scrollTop)).toBe(before);
    }
  });
}
