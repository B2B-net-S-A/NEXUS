import { describe, expect, it } from "vitest";

import {
  cardCareLabel,
  columnCounts,
  columnsText,
  jobsLocative,
  jobsPhrase,
  peoplePhrase,
  shortName,
} from "@/lib/departed-care";

describe("odejście rekrutera — teksty", () => {
  it("skraca nazwisko jak mail i dzwonek", () => {
    expect(shortName("Anna Przykładowa")).toBe("Anna P.");
    expect(shortName("Anna")).toBe("Anna");
    expect(shortName("  ")).toBe("ktoś z zespołu");
  });

  it("odmienia osoby i rekrutacje", () => {
    expect(peoplePhrase(1)).toBe("1 osoba");
    expect(peoplePhrase(4)).toBe("4 osoby");
    expect(peoplePhrase(13)).toBe("13 osób");
    expect(peoplePhrase(78)).toBe("78 osób");
    expect(jobsPhrase(1)).toBe("1 rekrutacja");
    expect(jobsPhrase(3)).toBe("3 rekrutacje");
    expect(jobsPhrase(7)).toBe("7 rekrutacji");
    expect(jobsLocative(1)).toBe("1 rekrutacji");
    expect(jobsLocative(19)).toBe("19 rekrutacjach");
  });

  it("kolumny idą od najbliższej klienta i bez zer", () => {
    const columns = { new: 41, client_interview: 3, cv_sent: 18, verified: 0 };
    expect(columnCounts(columns)).toEqual([
      ["client_interview", 3],
      ["cv_sent", 18],
      ["new", 41],
    ]);
    expect(columnsText(columns)).toBe("3 rozmowa u klienta · 18 CV wysłane · 41 nowi");
  });

  it("karta mówi „domykasz Ty” opiekunowi i imię innym", () => {
    expect(cardCareLabel("Anna Przykładowa", 7, "Maria Opiekunka", 7)).toEqual({
      departed: "Anna P. · konto wyłączone",
      caretaker: "domykasz Ty",
    });
    expect(cardCareLabel("Anna Przykładowa", 7, "Maria Opiekunka", 8).caretaker).toBe(
      "domyka Maria O.",
    );
  });
});
