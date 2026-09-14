import { describe, expect, it } from "vitest";
import {
  filterClients,
  foldText,
  matchRank,
  type ClientRef,
} from "@/lib/contract-client-filter";

// Sample mirrors the real Contracts dropdown (alphabetical), where "po" is a
// substring of almost every Polish client name.
const CLIENTS: ClientRef[] = [
  { id: 1, name: "AMERICAN HEARTS OF POLAND" },
  { id: 2, name: "Asseco Poland S.A." },
  { id: 3, name: "BNP Paribas Bank Polska Spółka Akcyjna" },
  { id: 4, name: "Bank Pocztowy S.A." },
  { id: 5, name: "DEKPOL" },
  { id: 6, name: "Gaspol" },
  { id: 7, name: "ING Poland" },
  { id: 8, name: "IPOPEMA Securities" },
  { id: 9, name: "PANSA - Polska Agencja Żeglugi Powietrznej" },
];

const names = (clients: ClientRef[]) => clients.map((c) => c.name);

describe("foldText", () => {
  it("lowercases and strips diacritics including Polish ł", () => {
    expect(foldText("Żeglugi")).toBe("zeglugi");
    expect(foldText("Spółka")).toBe("spolka");
    expect(foldText("Crédit")).toBe("credit");
  });
});

describe("matchRank", () => {
  it("ranks a full-name prefix above a word prefix, and rejects mid-word", () => {
    expect(matchRank("Bank Pocztowy S.A.", "bank")).toBe(0); // name prefix
    expect(matchRank("Bank Pocztowy S.A.", "po")).toBe(1); // word prefix
    expect(matchRank("IPOPEMA Securities", "po")).toBe(-1); // only mid-word
  });
});

describe("filterClients", () => {
  it("returns the head of the list for an empty query", () => {
    expect(names(filterClients(CLIENTS, ""))).toEqual(names(CLIENTS));
    expect(names(filterClients(CLIENTS, "   "))).toEqual(names(CLIENTS));
  });

  it("reacts from the first letter — a single char already narrows", () => {
    // "d" only matches DEKPOL (word/name prefix), not "Poland"/"Polska".
    expect(names(filterClients(CLIENTS, "d"))).toEqual(["DEKPOL"]);
  });

  it('drops mid-word matches for "po" that made the list look unfiltered', () => {
    const result = names(filterClients(CLIENTS, "po"));
    // Word-prefix hits on "Poland"/"Polska"/"Pocztowy" survive...
    expect(result).toContain("AMERICAN HEARTS OF POLAND");
    expect(result).toContain("Bank Pocztowy S.A.");
    expect(result).toContain("ING Poland");
    // ...but pure mid-word occurrences are gone.
    expect(result).not.toContain("IPOPEMA Securities");
    expect(result).not.toContain("Gaspol");
    expect(result).not.toContain("DEKPOL");
  });

  it("ranks name-prefix matches ahead of word-prefix matches", () => {
    const result = names(filterClients(CLIENTS, "po"));
    // "PANSA ..." would only be a word-prefix hit; a name-prefix hit (none here
    // start with "po") would precede it. Verify Bank Pocztowy (word hit) and
    // stable alphabetical order within the tier are preserved.
    expect(result.indexOf("AMERICAN HEARTS OF POLAND")).toBeLessThan(
      result.indexOf("Bank Pocztowy S.A."),
    );
  });

  it("matches accent-insensitively", () => {
    expect(names(filterClients(CLIENTS, "zeglugi"))).toEqual([
      "PANSA - Polska Agencja Żeglugi Powietrznej",
    ]);
  });

  it("finds a bracket-prefixed name by its inner tag and by a multi-word fragment (UAT M02-B02)", () => {
    const clients: ClientRef[] = [
      { id: 1, name: "[QA-E2E] Klient Testowy D1" },
      { id: 2, name: "[QA-E2E] Klient Testowy D2" },
      { id: 3, name: "Klient Inny" },
    ];
    expect(names(filterClients(clients, "QA-E2E"))).toEqual([
      "[QA-E2E] Klient Testowy D1",
      "[QA-E2E] Klient Testowy D2",
    ]);
    expect(names(filterClients(clients, "Klient Testowy"))).toEqual([
      "[QA-E2E] Klient Testowy D1",
      "[QA-E2E] Klient Testowy D2",
    ]);
    expect(names(filterClients(clients, "klient"))).toHaveLength(3);
    // Tokenizacja nie wpuszcza dopasowań w środku słowa.
    expect(names(filterClients(clients, "estowy"))).toEqual([]);
  });

  it("ranks a punctuation-stripped name prefix above a word prefix", () => {
    expect(matchRank("[QA-E2E] Klient", "qa-e2e")).toBe(0);
    expect(matchRank("[QA-E2E] Klient", "klient")).toBe(1);
    expect(matchRank("Bank Pocztowy S.A.", "bank poc")).toBe(0);
    expect(matchRank("Bank Pocztowy S.A.", "pocztowy bank")).toBe(1);
  });

  it("respects the result limit", () => {
    const many: ClientRef[] = Array.from({ length: 150 }, (_, i) => ({
      id: i,
      name: `Polska Firma ${i}`,
    }));
    expect(filterClients(many, "polska")).toHaveLength(100);
  });
});
