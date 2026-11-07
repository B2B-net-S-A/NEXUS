import { describe, expect, it } from "vitest";

import { broadVariant, broadVariantWords } from "../requirement-rows";

describe("broadVariant — rdzeń, który rozlewa wiersz (789198, 07.11.2026)", () => {
  const WORDS = ["microsoft*", "Dynamics 365", "D365"];

  it("„microsoft*” obok Dynamics 365: 31× szerzej", () => {
    expect(broadVariant(WORDS, { "microsoft*": 21_314, "Dynamics 365": 692, D365: 410 })).toEqual({
      word: "microsoft*",
      wide: 21_314,
      narrow: 692,
      ratio: 31,
    });
  });

  it("rdzeń odmiany obok słowa z maila nie ostrzega („bankow*” przy „bankowości”)", () => {
    expect(broadVariant(["bankowości", "bankow*"], { bankowości: 55, "bankow*": 323 })).toBeNull();
  });

  it("mały zasięg nie ostrzega, nawet przy dużym stosunku", () => {
    expect(broadVariant(["płatn*", "PSD2"], { "płatn*": 400, PSD2: 12 })).toBeNull();
  });

  it("czeka, aż policzą się wszystkie słowa wiersza", () => {
    expect(broadVariant(WORDS, { "microsoft*": 21_314, "Dynamics 365": 692 })).toBeNull();
    expect(broadVariant(WORDS, { "microsoft*": 21_314, "Dynamics 365": null, D365: 410 })).toBeNull();
  });

  it("liczy tylko wiersz z rdzeniem i drugim słowem", () => {
    expect(broadVariantWords(WORDS)).toEqual(WORDS);
    expect(broadVariantWords(["Security*"])).toEqual([]);
    expect(broadVariantWords(["Kafka", "RabbitMQ"])).toEqual([]);
  });
});
