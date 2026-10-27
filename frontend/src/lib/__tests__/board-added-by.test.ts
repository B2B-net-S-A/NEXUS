import { describe, expect, it } from "vitest";

import {
  ADDED_BY_ALL,
  addedByChoiceLabel,
  addedByEmptyColumnText,
  addedByOptions,
  addedByParam,
  addedByQueueSuffix,
  matchesAddedBy,
  parseAddedBy,
  peopleInProgress,
} from "@/lib/board-added-by";

const person = (candidate_id: number, by: number | null, name: string | null = null) => ({
  candidate_id,
  added_to_job_by_id: by,
  added_to_job_by_name: name,
});

describe("parametr adresu ?added_by= (D3)", () => {
  it("numer osoby, „none” i brak parametru", () => {
    expect(parseAddedBy("12")).toEqual({ kind: "user", userId: 12 });
    expect(parseAddedBy("none")).toEqual({ kind: "none" });
    expect(parseAddedBy(null)).toEqual(ADDED_BY_ALL);
  });

  it("śmieci w adresie dają „wszyscy”, nie pustą Tablicę", () => {
    for (const raw of ["", "0", "-3", "abc", "1.5", "me", "12345678901"]) {
      expect(parseAddedBy(raw)).toEqual(ADDED_BY_ALL);
    }
  });

  it("zapis wraca do tej samej wartości; „wszyscy” zdejmuje parametr", () => {
    expect(addedByParam({ kind: "user", userId: 7 })).toBe("7");
    expect(addedByParam({ kind: "none" })).toBe("none");
    expect(addedByParam(ADDED_BY_ALL)).toBeNull();
  });
});

describe("matchesAddedBy — po numerze osoby dodającej (D5)", () => {
  it("osoba, brak danych i wszyscy", () => {
    expect(matchesAddedBy(person(1, 7), { kind: "user", userId: 7 })).toBe(true);
    expect(matchesAddedBy(person(1, 8), { kind: "user", userId: 7 })).toBe(false);
    expect(matchesAddedBy(person(1, null), { kind: "none" })).toBe(true);
    expect(matchesAddedBy({ candidate_id: 1 }, { kind: "none" })).toBe(true);
    expect(matchesAddedBy(person(1, 7), { kind: "none" })).toBe(false);
    expect(matchesAddedBy(person(1, null), ADDED_BY_ALL)).toBe(true);
  });

  it("imiennicy z różnymi numerami to różne osoby", () => {
    expect(matchesAddedBy(person(1, 8, "Anna Nowak"), { kind: "user", userId: 7 })).toBe(false);
  });
});

describe("peopleInProgress — osoby w toku na Tablicy", () => {
  it("pomija zamkniętych, bierze „Poza szablonem”, każda osoba raz", () => {
    const columns = [
      { stage: "new", name: "Nowy", category: "internal", items: [person(1, 7), person(2, 8)] },
      { stage: "screening", name: "Screening", category: "internal", items: [person(2, 8), person(3, 7)] },
      { stage: "rejected", name: "Odrzucony", category: "terminal", terminal_type: "rejected", items: [person(4, 7)] },
    ];
    expect(peopleInProgress(columns, [person(5, null)]).map((p) => p.candidate_id)).toEqual([1, 2, 3, 5]);
  });
});

describe("addedByOptions — menu „Kto dodał”", () => {
  const people = [
    person(1, 7, "Tomasz Rybak"),
    person(2, 8, "Paulina Wrona"),
    person(3, 8, "Paulina Wrona"),
    person(4, 9, "Adam Zieliński"),
    person(5, 7, "Tomasz Rybak"),
    person(6, 7, "Tomasz Rybak"),
    person(7, null),
    person(8, 10, "Anna Bąk"),
  ];

  it("Wszyscy, Ty, pozostali od największej liczby, Brak danych na końcu", () => {
    const options = addedByOptions(people, { id: 7, name: "Tomasz Rybak" });
    expect(options.map((o) => [o.label, o.count])).toEqual([
      ["Wszyscy", 8],
      ["Ty (Tomasz Rybak)", 3],
      ["Paulina Wrona", 2],
      ["Adam Zieliński", 1],
      ["Anna Bąk", 1],
      ["Brak danych", 1],
    ]);
  });

  it("„Ty” jest zawsze, także gdy patrzący nikogo nie dodał", () => {
    const options = addedByOptions(people, { id: 99, name: null });
    expect(options[1]).toMatchObject({ label: "Ty", count: 0, isViewer: true });
  });

  it("bez kart bez danych nie ma pozycji „Brak danych”; bez zalogowanego nie ma „Ty”", () => {
    const options = addedByOptions([person(1, 8, "Paulina Wrona")], { id: null });
    expect(options.map((o) => o.key)).toEqual(["all", "user:8"]);
  });
});

describe("napisy filtra", () => {
  const options = addedByOptions([person(1, 7, "Tomasz Rybak"), person(2, 8, "Paulina Wrona")], {
    id: 7,
    name: "Tomasz Rybak",
  });

  it("przycisk", () => {
    expect(addedByChoiceLabel(ADDED_BY_ALL, options)).toBe("wszyscy");
    expect(addedByChoiceLabel({ kind: "user", userId: 7 }, options)).toBe("Ty");
    expect(addedByChoiceLabel({ kind: "user", userId: 8 }, options)).toBe("Paulina Wrona");
    expect(addedByChoiceLabel({ kind: "user", userId: 55 }, options)).toBe("osoba spoza tej Tablicy");
    expect(addedByChoiceLabel({ kind: "none" }, options)).toBe("brak danych");
  });

  it("dopisek kolejki w panelu", () => {
    expect(addedByQueueSuffix(ADDED_BY_ALL, options)).toBeNull();
    expect(addedByQueueSuffix({ kind: "user", userId: 7 }, options)).toBe("dodani przez Ciebie");
    expect(addedByQueueSuffix({ kind: "user", userId: 8 }, options)).toBe("dodani przez Paulina Wrona");
    expect(addedByQueueSuffix({ kind: "none" }, options)).toBe("bez danych o dodającym");
  });

  it("pusta kolumna", () => {
    expect(addedByEmptyColumnText({ kind: "user", userId: 7 }, options)).toBe("Brak osób dodanych przez Ciebie.");
    expect(addedByEmptyColumnText({ kind: "user", userId: 8 }, options)).toBe(
      "Brak osób dodanych przez Paulina Wrona.",
    );
  });
});

describe("„Prowadzi” w filtrze „Kto dodał” (25.10.2026)", () => {
  const assigned = {
    ...person(1, 7, "Tomasz Rybak"),
    owner_user_id: 9,
    owner_name: "Maria Przypisana",
  };

  it("przypisana osoba liczy się zamiast dodającej", () => {
    expect(matchesAddedBy(assigned, { kind: "user", userId: 9 })).toBe(true);
    expect(matchesAddedBy(assigned, { kind: "user", userId: 7 })).toBe(false);
  });

  it("osoba od systemu z przypisaniem nie jest już „System”", () => {
    const fromSystem = { ...assigned, added_to_job_by_id: null, entry_source: "system" };
    expect(matchesAddedBy(fromSystem, { kind: "system" })).toBe(false);
    expect(matchesAddedBy(fromSystem, { kind: "user", userId: 9 })).toBe(true);
  });

  it("menu podpisuje osobę przypisaną jej imieniem", () => {
    const labels = addedByOptions([assigned, person(2, 7, "Tomasz Rybak")], { id: null }).map(
      (o) => o.label,
    );
    expect(labels).toContain("Maria Przypisana");
    expect(labels).toContain("Tomasz Rybak");
  });
});

describe("„Biorę” w filtrze „Kto dodał” (27.10.2026)", () => {
  // Rekruterka wzięła osobę dodaną przez kolegę i szukała jej pod „Ty”.
  const taken = {
    ...person(1, 7, "Tomasz Rybak"),
    taken_by_user_id: 5,
    taken_by_name: "Ola Biorąca",
  };

  it("osoba, która wzięła, liczy się zamiast dodającej", () => {
    expect(matchesAddedBy(taken, { kind: "user", userId: 5 })).toBe(true);
    expect(matchesAddedBy(taken, { kind: "user", userId: 7 })).toBe(false);
  });

  it("„Prowadzi” wygrywa z osobą, która wzięła", () => {
    const assigned = { ...taken, owner_user_id: 9, owner_name: "Maria Przypisana" };
    expect(matchesAddedBy(assigned, { kind: "user", userId: 9 })).toBe(true);
    expect(matchesAddedBy(assigned, { kind: "user", userId: 5 })).toBe(false);
  });

  it("osoba od systemu po „Dzwonię” nie jest już „System”", () => {
    const fromSystem = { ...taken, added_to_job_by_id: null, entry_source: "system" };
    expect(matchesAddedBy(fromSystem, { kind: "system" })).toBe(false);
    expect(matchesAddedBy(fromSystem, { kind: "user", userId: 5 })).toBe(true);
  });

  it("„Ty” liczy wziętych, dodający traci ich z licznika", () => {
    const options = addedByOptions([taken, person(2, 7, "Tomasz Rybak")], {
      id: 5,
      name: "Ola Biorąca",
    });
    const count = (key: string) => options.find((o) => o.key === key)?.count;
    expect(count("user:5")).toBe(1);
    expect(count("user:7")).toBe(1);
  });
});
