import { describe, expect, it } from "vitest";

import {
  PREVIEW_DEBOUNCE_MS,
  PREVIEW_MAX_PER_MINUTE,
  bestPage,
  findBlock,
  pageChip,
  previewDelay,
  renderInfo,
  textLines,
  type PdfTextItem,
} from "../cv-new-preview";

describe("kiedy prosić o PDF", () => {
  it("pierwszy podgląd od razu, kolejny 4 s po ostatniej zmianie", () => {
    expect(previewDelay({ now: 1000, lastChangeAt: null, sent: [] })).toBe(0);
    expect(previewDelay({ now: 1000, lastChangeAt: 1000, sent: [] })).toBe(PREVIEW_DEBOUNCE_MS);
    expect(previewDelay({ now: 4000, lastChangeAt: 1000, sent: [] })).toBe(1000);
    expect(previewDelay({ now: 9000, lastChangeAt: 1000, sent: [] })).toBe(0);
  });

  it("nie przekracza limitu żądań na minutę (trasa ma 20/min na osobę)", () => {
    expect(PREVIEW_MAX_PER_MINUTE).toBeLessThan(20);
    const sent = Array.from({ length: PREVIEW_MAX_PER_MINUTE }, (_, i) => 10_000 + i * 1000);
    // Najstarsze żądanie wypada z okna minuty po 70 s.
    expect(previewDelay({ now: 30_000, lastChangeAt: 0, sent })).toBe(40_000);
    // Żądania sprzed ponad minuty się nie liczą.
    expect(previewDelay({ now: 80_000, lastChangeAt: 0, sent })).toBe(0);
  });
});

describe("nagłówki renderu i chip", () => {
  it("strona 1 mieści się, pismo 10 pt", () => {
    const info = renderInfo(new Headers({ "X-CV-Page1-Fits": "1", "X-CV-Page1-Font": "10" }));
    expect(info).toEqual({ fits: true, fontPt: 10, unmapped: 0 });
    expect(pageChip(1, 3, info)).toBe("Strona 1 z 3 · mieści się · pismo 10 pt");
  });

  it("nie mieści się i ułamek pisma po polsku", () => {
    const info = renderInfo(new Headers({ "X-CV-Page1-Fits": "0", "X-CV-Page1-Font": "9.5" }));
    expect(pageChip(1, 2, info)).toBe("Strona 1 z 2 · nie mieści się · pismo 9,5 pt");
  });

  it("bez nagłówków i na dalszej stronie sam numer", () => {
    expect(renderInfo(null)).toEqual({ fits: null, fontPt: null, unmapped: 0 });
    expect(pageChip(1, 2, renderInfo(null))).toBe("Strona 1 z 2");
    expect(pageChip(2, 3, { fits: true, fontPt: 10, unmapped: 0 })).toBe("Strona 2 z 3");
    expect(pageChip(2, null)).toBe("Strona 2");
  });
});

function item(str: string, x: number, y: number, width = 100, height = 10): PdfTextItem {
  return { str, x, y, width, height };
}

describe("gdzie na stronie stoi blok", () => {
  const page1 = textLines([
    item("Ponad 8 lat", 50, 700, 60),
    item("doświadczenia w QA i testowaniu", 112, 700, 200),
    item("Praktyczne doświadczenie z Postmanem", 50, 680, 260),
    item("Przebieg kariery", 50, 600),
  ]);
  const page2 = textLines([
    item("Firma", 40, 760, 30),
    item("Bank Przykładowy S.A.", 120, 760, 150),
    item("Rozwój mikroserwisów płatności w Java 17", 120, 740, 300),
    item("Firma", 40, 500, 30),
    item("Software House", 120, 500, 150),
  ]);

  it("skleja fragmenty jednej linii", () => {
    expect(page1[0].text).toBe("ponad 8 lat doświadczenia w qa i testowaniu");
    expect(page1[0].x1).toBe(312);
  });

  it("ramka obejmuje linie, w których zaczynają się szukane punkty", () => {
    const found = findBlock(page1, [
      "Ponad **8 lat** doświadczenia w QA i testowaniu oprogramowania.",
      "Praktyczne doświadczenie z Postmanem, Xray i Jirą.",
      "x",
    ]);
    expect(found?.hits).toBe(2);
    expect(found?.box).toEqual({ x0: 50, y0: 680, x1: 312, y1: 710 });
  });

  it("strona stanowiska = ta z największą liczbą trafień", () => {
    const found = bestPage([page1, page2], ["Bank Przykładowy S.A.", "Rozwój mikroserwisów płatności w Java 17."]);
    expect(found?.page).toBe(2);
    expect(found?.box.y0).toBe(740);
    expect(bestPage([page1], ["Nie ma tego tekstu"])).toBeNull();
  });

  it("ten sam tekst w innym stanowisku: bierze linię najbliżej firmy", () => {
    const lines = textLines([
      item("Stanowisko Senior Java Developer", 40, 760, 300),
      item("Firma Software House", 40, 500, 200),
      item("Stanowisko Java Developer", 40, 480, 250),
    ]);
    const found = findBlock(lines, ["Software House", "Java Developer"]);
    expect(found?.box).toEqual({ x0: 40, y0: 480, x1: 290, y1: 510 });
  });
});
