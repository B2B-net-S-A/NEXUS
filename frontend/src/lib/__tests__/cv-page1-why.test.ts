import { describe, expect, it } from "vitest";

import type { CvPage1Extras } from "@/lib/api";
import {
  autoTexts,
  fallbackTexts,
  isEdited,
  page1Sentences,
  plainText,
  whyPatch,
  whySlots,
} from "@/lib/cv-page1-why";

const POINTS = ["Punkt 1.", "Punkt 2.", "Punkt 3."];

describe("zdania 1–3 strony 1 — lustro compose_page1_why", () => {
  it("pusty slot bierze punkt z CV, slot 3 najpierw sprawdzony wynik", () => {
    const extras: CvPage1Extras = {
      why: ["", "Zdanie 2.", ""],
      results: [{ text: "Wynik.", verified: true }],
    };
    expect(page1Sentences(POINTS, extras)).toEqual(["Punkt 1.", "Zdanie 2.", "Wynik."]);
    expect(page1Sentences(POINTS, null)).toEqual(POINTS);
    expect(page1Sentences(POINTS, { results: [{ text: "Bez cytatu.", verified: false }] })).toEqual(POINTS);
    expect(page1Sentences([], { why: ["", "Tylko 2."] })).toEqual(["Tylko 2."]);
    expect(fallbackTexts(["  ", "A"], { result_text: "Wpisany." })).toEqual(["A", "", "Wpisany."]);
  });

  it("sloty: zawsze trzy, spacje złączone, śmieci = pusty slot", () => {
    expect(whySlots({ why: ["a\n b"] })).toEqual(["a b", "", ""]);
    expect(whySlots({ why: null })).toEqual(["", "", ""]);
    expect(whySlots(undefined)).toEqual(["", "", ""]);
  });

  it("poprawiony slot = inny niż sprawdzone zdanie generatora", () => {
    const extras: CvPage1Extras = {
      why: ["Z modelu.", "Moje.", ""],
      why_generated: [
        { slot: "experience", text: "Z modelu.", verified: true },
        { slot: "requirements", text: "Moje.", verified: false },
      ],
    };
    expect(autoTexts(extras)).toEqual(["Z modelu.", "", ""]);
    expect([0, 1, 2].map((i) => isEdited(extras, i))).toEqual([false, true, false]);
  });

  it("zapis zmienia jeden slot, pogrubienia znikają tylko w polu", () => {
    expect(whyPatch(1, "x")).toEqual([null, "x", null]);
    expect(plainText("**9 lat** w IT")).toBe("9 lat w IT");
  });
});
