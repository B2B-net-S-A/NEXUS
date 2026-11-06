import { describe, expect, it } from "vitest";

import {
  curateActionLabel,
  hintMessage,
  missingWords,
  rowActionLabel,
  rowWithHint,
  type DictionaryHint,
} from "@/lib/dictionary-hints";

function hint(over: Partial<DictionaryHint>): DictionaryHint {
  return {
    word: "mikroserwisy",
    kind: "alias",
    proposal_id: 7,
    word_count: 234,
    target: { name: "Microservices", count: 2327 },
    add_words: [{ name: "Microservices", count: 2327 }],
    canonical: "Microservices",
    category: "backend",
    ...over,
  };
}

describe("podpowiedź słownika w wierszu wymagań (06.11.2026)", () => {
  it("wariant znanego hasła: liczby obu zapisów i dopisanie hasła do wiersza", () => {
    const h = hint({});
    expect(hintMessage(h)).toContain(
      `„mikroserwisy” ma 234 osoby, a „Microservices” ${(2327).toLocaleString("pl-PL")}`,
    );
    expect(rowActionLabel(h, missingWords(["mikroserwisy"], h))).toBe("Dodaj do wiersza „Microservices”");
    expect(rowWithHint(["mikroserwisy"], h)).toEqual(["mikroserwisy", "Microservices"]);
  });

  it("nie dubluje słowa, które wiersz już ma (bez wielkości liter)", () => {
    const h = hint({});
    expect(missingWords(["mikroserwisy", "microservices"], h)).toEqual([]);
    expect(rowActionLabel(h, [])).toBeNull();
  });

  it("ogólnik: warianty konkretnych haseł", () => {
    const h = hint({
      word: "relacyjne bazy danych",
      kind: "generic",
      word_count: 36,
      target: null,
      add_words: [
        { name: "PostgreSQL", count: 9756 },
        { name: "MySQL", count: 5335 },
        { name: "Oracle DB", count: null },
        { name: "Microsoft SQL Server", count: 100 },
      ],
    });
    expect(hintMessage(h)).toMatch(/^Ogólne wymaganie: w umiejętnościach profili ma je dosłownie 36 osób/);
    expect(rowActionLabel(h, missingWords([h.word], h))).toBe("Dodaj warianty: PostgreSQL, MySQL, Oracle DB…");
    expect(curateActionLabel(h)).toBeNull();
  });

  it("nowe hasło: zapisy z danych i przycisk słownika tylko z propozycją", () => {
    const h = hint({
      word: "excel",
      kind: "new",
      target: null,
      canonical: "Microsoft Excel",
      add_words: [
        { name: "microsoft excel", count: 2665 },
        { name: "ms excel", count: 721 },
      ],
    });
    expect(rowActionLabel(h, missingWords(["excel"], h))).toBe("Dodaj zapisy: microsoft excel, ms excel");
    expect(curateActionLabel(h)).toBe("Dodaj do słownika jako „Microsoft Excel”");
    expect(curateActionLabel({ ...h, proposal_id: null })).toBeNull();
  });

  it("wiersz pełny: nic nie dopisuje ponad limit słów", () => {
    const full = Array.from({ length: 20 }, (_, i) => `słowo${i}`);
    expect(missingWords(full, hint({}))).toEqual([]);
  });
});
