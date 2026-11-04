import { describe, expect, it } from "vitest";

import { textareaFitHeight } from "@/lib/textarea-autogrow";

// Pole `text-sm`: linia 20 px, padding 8 + 8, ramka 1 + 1.
const base = { lineHeight: 20, padding: 16, border: 2 };

describe("textareaFitHeight", () => {
  it("treść krótsza niż sufit → pole ma wysokość treści plus ramkę", () => {
    // 4 linie: 4 × 20 + 16 = 96 px treści z paddingiem.
    expect(textareaFitHeight({ ...base, scrollHeight: 96 }, 10)).toEqual({ height: 98, scroll: false });
  });

  it("minimum z `rows` przychodzi w `scrollHeight` — funkcja go nie obcina", () => {
    // Puste pole z rows=3 mierzy 3 × 20 + 16 = 76 px.
    expect(textareaFitHeight({ ...base, scrollHeight: 76 }, 10)).toEqual({ height: 78, scroll: false });
  });

  it("treść dłuższa niż `maxRows` → sufit i przewijanie w środku", () => {
    // 14 linii = 296 px; sufit 10 × 20 + 16 = 216 px.
    expect(textareaFitHeight({ ...base, scrollHeight: 296 }, 10)).toEqual({ height: 218, scroll: true });
  });

  it("dokładnie `maxRows` linii mieści się bez przewijania", () => {
    expect(textareaFitHeight({ ...base, scrollHeight: 216 }, 10)).toEqual({ height: 218, scroll: false });
  });

  it("ułamkowa wysokość linii (pole 16 px na dotyku) nie włącza przewijania o piksel za wcześnie", () => {
    // 16 px × 4/3 = 21,33 px; 10 linii = 213,33 → przeglądarka podaje 230 z paddingiem 16.
    const touch = { lineHeight: 21.3333, padding: 16, border: 2 };
    expect(textareaFitHeight({ ...touch, scrollHeight: 230 }, 10)).toEqual({ height: 232, scroll: false });
  });

  it("układ niepoliczony (jsdom, pole w ukrytym panelu) → null, wysokości nie ustawiamy", () => {
    expect(textareaFitHeight({ ...base, scrollHeight: 0 }, 10)).toBeNull();
    expect(textareaFitHeight({ ...base, lineHeight: Number.NaN, scrollHeight: 96 }, 10)).toBeNull();
  });
});
