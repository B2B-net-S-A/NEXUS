/**
 * Audyt 48 h (13.10.2026), wymagania Championa — poprawki z 14.10.2026.
 *
 * Pkt 19: serwer czyta słowo po swoim sicie (kropka na końcu zdjęta, słowo
 * przycięte do 100 znaków), więc „Do rozmowy” musi trafić w słowo wiersza
 * także wtedy, gdy tekst odczytu różni się od wpisanego.
 * Pkt 21: „Uprość do słów kluczowych” nie gubi zdań ponad limit listy (20)
 * ani końcówek zdań dłuższych niż 160 znaków — trafiają do opisu wymagań.
 */

import { describe, expect, it } from "vitest";

import {
  replaceRowWord,
  talkFromDescriptive,
  talkTextFor,
  type PhraseReading,
  type RequirementRowForm,
} from "@/lib/requirement-rows";

const reading = (over: Partial<PhraseReading>): PhraseReading => ({
  text: "",
  kind: "prose",
  keyword: null,
  comment: null,
  talk: "skills",
  talk_text: null,
  suggestions: [],
  needs_decision: true,
  ...over,
});

const LONG =
  "Minimum 5 lat doświadczenia komercyjnego w projektowaniu i wdrażaniu hurtowni danych w sektorze bankowym oraz ubezpieczeniowym";
// Tak samo jak `cut_at_word(…, 100)` na serwerze.
const LONG_CUT =
  "Minimum 5 lat doświadczenia komercyjnego w projektowaniu i wdrażaniu hurtowni danych w sektorze";

describe("pkt 19 — „Do rozmowy” trafia w słowo wiersza", () => {
  it("słowo z kropką na końcu znika z wiersza, choć odczyt jest bez kropki", () => {
    const rows: RequirementRowForm[] = [
      { key: "a", words: ["Java"], level: "must" },
      { key: "b", words: ["Doświadczenie w przetargach."], level: "must" },
    ];
    const out = replaceRowWord(rows, "b", "Doświadczenie w przetargach", []);
    expect(out.map((r) => r.key)).toEqual(["a"]);
  });

  it("słowo dłuższe niż 100 znaków trafia w odczyt przycięty przez serwer", () => {
    const rows: RequirementRowForm[] = [
      { key: "b", words: [LONG, "przetarg*"], level: "must" },
    ];
    const out = replaceRowWord(rows, "b", LONG_CUT, []);
    expect(out[0].words).toEqual(["przetarg*"]);
  });

  it("inne słowo o tym samym początku zostaje", () => {
    const rows: RequirementRowForm[] = [
      { key: "b", words: ["SQL.", "SQL Server"], level: "must" },
    ];
    expect(replaceRowWord(rows, "b", "SQL", ["PostgreSQL"])[0].words).toEqual([
      "PostgreSQL",
      "SQL Server",
    ]);
  });

  it("do rozmowy idzie całe wpisane zdanie, gdy serwer przeczytał przycięte", () => {
    const read = reading({ text: LONG_CUT, talk_text: LONG_CUT });
    expect(talkTextFor(read, [LONG])).toBe(LONG);
  });

  it("bez przycięcia do rozmowy idzie tekst z serwera", () => {
    const read = reading({
      text: "Doświadczenie w przetargach",
      talk_text: "Doświadczenie w przetargach",
    });
    expect(talkTextFor(read, ["Doświadczenie w przetargach."])).toBe(
      "Doświadczenie w przetargach",
    );
  });
});

describe("pkt 21 — „Uprość” nie gubi zdań", () => {
  it("ponad 20 pozycji: nadmiar idzie do opisu wymagań, nic nie znika", () => {
    const sentences = Array.from({ length: 25 }, (_, i) => `Zdanie klienta numer ${i}`);
    const out = talkFromDescriptive([], "Projekt dla banku.", sentences, []);
    expect(out.skills).toHaveLength(20);
    expect(out.notes.startsWith("Projekt dla banku.\n")).toBe(true);
    expect(out.notes).toContain(
      "Do sprawdzenia w rozmowie: Zdanie klienta numer 20; Zdanie klienta numer 21; Zdanie klienta numer 22; Zdanie klienta numer 23; Zdanie klienta numer 24.",
    );
  });

  it("liczy też pozycje, które już są na liście", () => {
    const existing = Array.from({ length: 19 }, (_, i) => ({
      name: `Było ${i}`,
      level: "must" as const,
      min_years: null,
      note: "",
    }));
    const out = talkFromDescriptive(existing, "", ["Nowe A", "Nowe B"], []);
    expect(out.skills.map((i) => i.name)).toContain("Nowe A");
    expect(out.skills).toHaveLength(20);
    expect(out.notes).toBe("Do sprawdzenia w rozmowie: Nowe B.");
  });

  it("zdanie dłuższe niż 160 znaków: na liście skrót, w opisie całość", () => {
    const long = `${LONG} dla dużych klientów korporacyjnych w Polsce i w Europie Środkowej`;
    expect(long.length).toBeGreaterThan(160);
    const out = talkFromDescriptive([], "", [long], []);
    expect(out.skills).toHaveLength(1);
    expect(out.skills[0].name.length).toBeLessThanOrEqual(160);
    expect(out.notes).toContain(long);
  });

  it("zdanie z „mile widziane” idzie do rozmowy jako „Mile”", () => {
    const out = talkFromDescriptive(
      [],
      "",
      ["Java 17+", "doświadczenie w sektorze bankowym"],
      ["doświadczenie w sektorze bankowym"],
    );
    expect(out.skills.map((i) => [i.name, i.level])).toEqual([
      ["Java 17+", "must"],
      ["doświadczenie w sektorze bankowym", "nice"],
    ]);
    expect(out.notes).toBe("");
  });
});
