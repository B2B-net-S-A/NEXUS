import { describe, expect, it } from "vitest";

import {
  choosePopupPlacement,
  findMentionToken,
  matchMentionUsers,
} from "@/lib/mention-autocomplete";

const users = [
  { id: 1, name: "Marta Nowak", email: "marta.nowak@example.com", role: "recruiter" },
  { id: 2, name: "Łukasz Żak", email: "lzak@example.com", role: "delivery_lead" },
  { id: 3, name: "Anna Markowska", email: "anna.m@example.com", role: "recruiter" },
  { id: 4, name: "Jan Kowalski", email: "jan@example.com", role: "head_of_recruitment" },
];

describe("findMentionToken", () => {
  it("samo „@” zaczyna wzmiankę z pustym tekstem", () => {
    expect(findMentionToken("Hej @", 5)).toEqual({ start: 4, query: "" });
    expect(findMentionToken("@", 1)).toEqual({ start: 0, query: "" });
  });

  it("przyjmuje imię i nazwisko ze spacją", () => {
    expect(findMentionToken("@Jan Kow", 8)).toEqual({ start: 0, query: "Jan Kow" });
  });

  it("„@” w środku słowa to adres e-mail, nie wzmianka", () => {
    expect(findMentionToken("pisz na jan@firma", 17)).toBeNull();
    // Po wstawionej wzmiance dalszy tekst nie otwiera listy ponownie.
    expect(findMentionToken("@jan@example.com dzięki", 23)).toBeNull();
  });

  it("nowa linia, spacja zaraz po „@” i długie zdanie kończą wzmiankę", () => {
    expect(findMentionToken("@ Jan", 5)).toBeNull();
    expect(findMentionToken("@Jan\nKow", 8)).toBeNull();
    expect(findMentionToken("@Jan prosi o kontakt dziś", 25)).toBeNull();
  });
});

describe("matchMentionUsers", () => {
  it("pusty tekst zwraca początek listy w kolejności z serwera", () => {
    expect(matchMentionUsers(users, "", 2).map((u) => u.id)).toEqual([1, 2]);
  });

  it("szuka bez polskich znaków i wielkości liter", () => {
    expect(matchMentionUsers(users, "lukasz", 6).map((u) => u.id)).toEqual([2]);
    expect(matchMentionUsers(users, "ZAK", 6).map((u) => u.id)).toEqual([2]);
  });

  it("początek imienia przed początkiem nazwiska, potem reszta", () => {
    expect(matchMentionUsers(users, "mar", 6).map((u) => u.id)).toEqual([1, 3]);
  });

  it("imię i nazwisko ze spacją dopasowuje tylko nazwę", () => {
    expect(matchMentionUsers(users, "jan kow", 6).map((u) => u.id)).toEqual([4]);
    expect(matchMentionUsers(users, "jan prosi", 6)).toEqual([]);
  });

  it("znajduje po adresie e-mail, ale nie po wspólnej domenie", () => {
    expect(matchMentionUsers(users, "lzak", 6).map((u) => u.id)).toEqual([2]);
    expect(matchMentionUsers(users, "exam", 6)).toEqual([]);
  });
});

describe("choosePopupPlacement", () => {
  it("pole przy górnej krawędzi karty (notatka w profilu) → lista pod polem", () => {
    expect(choosePopupPlacement(40, 500, 264)).toEqual({ side: "below", maxHeight: 264 });
  });

  it("pole na dole czatu → lista nad polem", () => {
    expect(choosePopupPlacement(450, 12, 264)).toEqual({ side: "above", maxHeight: 264 });
  });

  it("mało miejsca po obu stronach → większa strona, lista przewijana", () => {
    expect(choosePopupPlacement(200, 150, 264)).toEqual({ side: "above", maxHeight: 192 });
    expect(choosePopupPlacement(0, 0, 264)).toEqual({ side: "below", maxHeight: 120 });
  });
});
