/**
 * Podpowiedź pod odpowiedzią ze screeningu (23.10.2026): zaślepka i samo
 * „tak” dostają ostrzeżenie, konkretna odpowiedź i „nie” — nie.
 */

import { describe, expect, it } from "vitest";

import { screeningAnswerHint } from "@/lib/screening-answer-hint";

describe("screeningAnswerHint", () => {
  it("zaślepka to nie odpowiedź", () => {
    for (const response of ["x", "X", "-", "?", "...", "n/a", "b/d"]) {
      expect(screeningAnswerHint(response), response).toMatch(/nie trafi do CV/);
    }
  });

  it("samo „tak” prosi o konkret", () => {
    for (const response of ["Tak", "tak.", "Tak, zna", "Yes", "ok"]) {
      expect(screeningAnswerHint(response), response).toMatch(/Dopisz konkret/);
    }
  });

  it("konkretna odpowiedź, przeczenie i puste pole bez ostrzeżenia", () => {
    for (const response of [
      "Tak, 3 lata Kafka w projekcie dla banku",
      "Nie",
      "Nie zna Terraform",
      "C",
      "",
      "   ",
      null,
      undefined,
    ]) {
      expect(screeningAnswerHint(response), String(response)).toBeNull();
    }
  });
});
