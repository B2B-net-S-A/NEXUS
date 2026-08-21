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

  test("profile exposes five sections and a mobile section selector", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/preview/candidate-profile");

    const selector = page.getByLabel("Sekcja profilu");
    await expect(selector).toBeVisible();
    await selector.selectOption("activity");
    await expect(page.getByRole("button", { name: "Historia" })).toBeVisible();
    await expectNoPageOverflow(page);

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.reload();
    for (const label of ["Podsumowanie", "Rekrutacje", "Aktywność", "Dopasowanie", "Pliki i umowy"]) {
      await expect(page.getByRole("tab", { name: new RegExp(label) })).toBeVisible();
    }
  });

  test("quick view has one close and candidate facts precede suggestions", async ({ page }) => {
    await page.goto("/preview/candidate-profile");
    await page.getByRole("button", { name: "Quick view" }).click();

    const quickView = page.getByRole("region", { name: "Szybki podgląd kandydata" });
    await expect(quickView).toBeVisible();
    await expect(page.getByRole("button", { name: "Zamknij szybki podgląd" })).toHaveCount(1);
    // Asercja szła po WIDOCZNEJ etykiecie („Oczekiwana stawka"). PR #1009
    // przemianował ją na „Stawka B2B" i nocny bieg zrobił się czerwony na 21
    // nocy z rzędu — przestał odróżniać regresję od przeterminowanego napisu,
    // a jest to jedyny automatyczny test dotykający produkcji. Pytamy więc
    // o STRUKTURĘ: quick view ma listę faktów kandydata z kompletem pozycji.
    // Zmiana copy nie może już zepsuć alarmu; usunięcie faktów — może.
    // Pierwszy `dl` w quick view to KeyFacts — jedyny komponent w `ds/`, który
    // renderuje listę definicji; `dl`-e rekomendacji są niżej w DOM.
    const facts = quickView.locator("dl").first();
    await expect(facts).toBeVisible();
    await expect(facts.locator("dt")).toHaveCount(4);
    await expect(page.getByRole("heading", { name: "Sugerowane rekrutacje" })).toBeVisible();

    const order = await page.evaluate(() => {
      const facts = document.querySelector("dl");
      const suggestions = document.querySelector("#quick-matches");
      return facts && suggestions
        ? facts.compareDocumentPosition(suggestions) & Node.DOCUMENT_POSITION_FOLLOWING
        : 0;
    });
    expect(order).toBeTruthy();
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
      await expect(page.getByRole("heading", { name: "Quick view i pełny profil" })).toBeVisible();
      await expect(page.getByText("Janusz Prażmowski").first()).toBeVisible();
      await expectNoPageOverflow(page);
    });
  }
});
