/**
 * Spis treści procedury musi trafiać tam, gdzie obiecuje.
 *
 * Link, który skacze w złe miejsce, jest gorszy od braku spisu treści:
 * czytelnik nie wie, że wylądował gdzie indziej, i czyta instrukcję innego
 * klienta niż zamierzał — a te instrukcje różnią się przelicznikami stawek.
 */
import { describe, expect, it } from "vitest";

import { assignHeadingIds, slugifyHeading } from "@/lib/procedure-headings";

function render(html: string): HTMLElement {
  const root = document.createElement("div");
  root.innerHTML = html;
  return root;
}

describe("slugifyHeading", () => {
  it("zdejmuje polskie znaki diakrytyczne", () => {
    expect(slugifyHeading("Zamówienia okresowe")).toBe("zamowienia-okresowe");
    expect(slugifyHeading("Wyłączenia i częstotliwość")).toBe(
      "wylaczenia-i-czestotliwosc",
    );
  });

  it("transliteruje ł, którego NFKD nie rozkłada", () => {
    // Bez jawnej pary „ł→l" ten nagłówek dałby slug „g-wne", a dwa różne
    // nagłówki różniące się tylko tą literą — slug identyczny.
    expect(slugifyHeading("Główne zasady")).toBe("glowne-zasady");
    expect(slugifyHeading("ŁÓDŹ")).toBe("lodz");
  });

  it("nie zwraca pustego sluga dla nagłówka bez liter ASCII", () => {
    expect(slugifyHeading("⚠️")).toBe("sekcja");
  });
});

describe("assignHeadingIds", () => {
  it("nadaje id nagłówkom h2 i h3 i zwraca je w kolejności dokumentu", () => {
    const root = render(
      "<h2>Nordea</h2><p>x</p><h3>Powiadomienia</h3><h2>Erste Bank Polska</h2>",
    );

    const headings = assignHeadingIds(root);

    expect(headings).toEqual([
      { id: "nordea", text: "Nordea", level: 2 },
      { id: "powiadomienia", text: "Powiadomienia", level: 3 },
      { id: "erste-bank-polska", text: "Erste Bank Polska", level: 2 },
    ]);
    expect(root.querySelector("h2")?.id).toBe("nordea");
  });

  it("rozróżnia powtórzone tytuły sekcji", () => {
    // Każdy klient ma podsekcję o tej samej nazwie. Bez licznika wszystkie
    // punkty spisu treści prowadziłyby do pierwszego klienta.
    const root = render(
      "<h2>BNP</h2><h3>Co robi system</h3><h2>BIK</h2><h3>Co robi system</h3>",
    );

    const headings = assignHeadingIds(root);

    expect(headings.map((h) => h.id)).toEqual([
      "bnp",
      "co-robi-system",
      "bik",
      "co-robi-system-2",
    ]);
  });

  it("jest idempotentna — ponowne wywołanie nie zmienia id", () => {
    // Widok procedury odświeża się w tle (react-query), więc efekt biegnie
    // ponownie na tym samym drzewie. Gdyby licznik nakładał się na poprzedni
    // przebieg, skopiowany link przestałby działać po pierwszym refetchu.
    const root = render("<h2>Zamówienia</h2><h2>Zamówienia</h2>");

    const first = assignHeadingIds(root);
    const second = assignHeadingIds(root);

    expect(second).toEqual(first);
    expect(second.map((h) => h.id)).toEqual(["zamowienia", "zamowienia-2"]);
  });

  it("pomija nagłówki bez tekstu", () => {
    const root = render("<h2></h2><h2>Realny nagłówek</h2>");

    expect(assignHeadingIds(root).map((h) => h.text)).toEqual([
      "Realny nagłówek",
    ]);
  });

  it("nie widzi nagłówków w blokach kodu", () => {
    // Markdown renderuje `## coś` w bloku kodu jako tekst, nie jako <h2> —
    // dlatego czytamy DOM, a nie źródło. Ten test przypina tę własność.
    const root = render("<pre><code>## To nie jest nagłówek</code></pre>");

    expect(assignHeadingIds(root)).toEqual([]);
  });
});
