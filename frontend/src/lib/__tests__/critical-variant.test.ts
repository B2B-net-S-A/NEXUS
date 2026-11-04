import { describe, expect, it } from "vitest";

import { rowsWithVariant } from "@/lib/critical-variant";
import { ROW_WORDS_MAX } from "@/lib/requirement-rows";

const ROWS = [
  { level: "must" as const, words: ["SailPoint IIQ", "IIQ"] },
  { level: "nice" as const, words: ["SailPoint"] },
  { level: "must" as const, words: ["Python"] },
];

describe("rowsWithVariant — „„X” = krytyczna” (28.10.2026)", () => {
  it("dopisuje słowo do wiersza „musi mieć” po etykiecie, bez wielkości liter; reszta bez zmian", () => {
    const result = rowsWithVariant(ROWS, "sailpoint iiq", "SailPoint");
    expect(result).toEqual({
      ok: true,
      rows: [
        { level: "must", words: ["SailPoint IIQ", "IIQ", "SailPoint"] },
        ROWS[1],
        ROWS[2],
      ],
    });
  });

  it("odmawia, gdy wiersza nie ma, słowo już stoi albo wiersz jest pełny", () => {
    expect(rowsWithVariant(ROWS, "Okta", "Okta Cloud")).toMatchObject({ ok: false });
    expect(rowsWithVariant(ROWS, "SailPoint IIQ", "iiq")).toMatchObject({
      ok: false,
      reason: "„iiq” jest już w wierszu „SailPoint IIQ”.",
    });
    const full = [{ level: "must" as const, words: Array.from({ length: ROW_WORDS_MAX }, (_, i) => `Słowo${i}`) }];
    expect(rowsWithVariant(full, "Słowo0", "Nowe")).toMatchObject({ ok: false });
    expect(rowsWithVariant(null, "SailPoint IIQ", "SailPoint")).toMatchObject({ ok: false });
  });
});
