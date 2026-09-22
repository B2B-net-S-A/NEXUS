import { expect, test, type Page } from "@playwright/test";

const VIEWPORTS = [
  { name: "mobile", width: 390, height: 844 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop", width: 1440, height: 900 },
] as const;

async function expectNoPageOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
}

test.describe("candidate UX deterministic previews", () => {
  for (const viewport of VIEWPORTS) {
    test(`contact queue is readable at ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto("/preview/contact-queue");

      await expect(
        page.getByRole("heading", { name: "Do przedzwonienia" }),
      ).toBeVisible();
      await expect(page.getByText("18/20")).toBeVisible();
      await expect(
        page.getByRole("link", { name: "Alicja Zielińska" }),
      ).toHaveCount(1);
      await expect(page.getByText("Senior Java Developer").first()).toBeVisible();
      await expect(page.getByText("Backend Tech Lead")).toBeVisible();
      await expectNoPageOverflow(page);
    });
  }

  test("contact queue logs only an explicit outcome", async ({ page }) => {
    await page.goto("/preview/contact-queue");

    await page.getByRole("button", { name: /zaloguj wynik/i }).first().click();
    for (const outcome of [
      "Rozmowa odbyta",
      "Brak odpowiedzi",
      "Prośba o oddzwonienie",
      "Błędny numer",
      "Nie kontaktować",
    ]) {
      await expect(page.getByText(outcome, { exact: true })).toBeVisible();
    }

    await page
      .getByRole("radio", { name: "Prośba o oddzwonienie" })
      .click();
    await page.getByRole("button", { name: "Zapisz wynik" }).click();
    await expect(
      page.getByText("Wskaż prawidłowy termin oddzwonienia."),
    ).toBeVisible();
  });

  for (const viewport of VIEWPORTS) {
    test(`candidate list is readable at ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto("/preview/candidates");

      await expect(page.getByRole("heading", { name: "Czytelna lista kandydatów" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Dodaj kandydata" })).toBeVisible();
      await expectNoPageOverflow(page);

      if (viewport.width < 1024) {
        await expect(page.getByRole("heading", { name: "Janusz Prażmowski" })).toBeVisible();
        await expect(page.getByRole("button", { name: "Podgląd" }).first()).toBeVisible();
        await expect(page.getByRole("table")).toBeHidden();
      } else {
        await expect(page.getByRole("button", { name: "Janusz Prażmowski", exact: true })).toBeVisible();
        await expect(page.getByRole("table")).toBeVisible();
        await expect(page.getByRole("columnheader", { name: "Kandydat" })).toBeVisible();
        await expect(page.getByRole("columnheader", { name: "Ostatnia aktywność" })).toBeVisible();
      }
    });
  }

  // Profil ma od 22.09.2026 CZTERY zakładki (Profil · Rekrutacje · Historia ·
  // Pliki i umowy, #1689) w jednym pasku, który na telefonie przewija się
  // poziomo — dawnej listy rozwijanej „Sekcja profilu" już nie ma.
  test("profile exposes four sections and they stay usable on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/preview/candidate-profile");

    const tabs = page.getByRole("tablist", { name: "Sekcje profilu kandydata" });
    await expect(tabs).toBeVisible();
    const history = tabs.getByRole("tab", { name: /Historia/ });
    await history.scrollIntoViewIfNeeded();
    await history.click();
    await expect(history).toHaveAttribute("aria-selected", "true");
    await expectNoPageOverflow(page);

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.reload();
    for (const label of ["Profil", "Rekrutacje", "Historia", "Pliki i umowy"]) {
      await expect(page.getByRole("tab", { name: new RegExp(label) })).toBeVisible();
    }
  });

  // Szybki podgląd żyje na liście kandydatów (od 22.09.2026 harness profilu
  // pokazuje wyłącznie pełny profil). Pytamy o STRUKTURĘ, nie o napisy — patrz
  // historia z „Oczekiwaną stawką" → „Stawką B2B", która zrobiła z tego testu
  // alarm czerwony przez 21 nocy z samej zmiany copy.
  test("quick view opens from the list with one close and the key facts", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/preview/candidates-list");

    const row = page.getByRole("group", { name: /Marta Przykładowa — Enter otwiera podgląd/ });
    await row.focus();
    await page.keyboard.press("Enter");

    await expect(page.getByRole("button", { name: "Zamknij szybki podgląd" })).toHaveCount(1);
    const facts = page.getByRole("dialog").locator("dl").first();
    await expect(facts).toBeVisible();
    await expect(facts.locator("dt")).toHaveCount(3);

    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "Zamknij szybki podgląd" })).toHaveCount(0);
  });

  for (const theme of ["light", "dark", "soft", "kids"] as const) {
    test(`candidate previews render in ${theme} theme`, async ({ page }) => {
      await page.goto("/preview/candidate-profile");
      await page.evaluate((selectedTheme) => {
        document.documentElement.classList.toggle("dark", selectedTheme === "dark");
        document.documentElement.toggleAttribute("data-soft", selectedTheme === "soft");
        document.documentElement.toggleAttribute("data-kids", selectedTheme === "kids");
        if (selectedTheme === "soft") document.documentElement.setAttribute("data-soft", "true");
        if (selectedTheme === "kids") document.documentElement.setAttribute("data-kids", "true");
      }, theme);
      await expect(page.getByRole("heading", { level: 1, name: /Marta Kowalczyk/ })).toBeVisible();
      await expect(page.getByRole("tablist", { name: "Sekcje profilu kandydata" })).toBeVisible();
      await expectNoPageOverflow(page);
    });
  }
});
