import { describe, expect, it } from "vitest";
import {
  largestHomonymGroup,
  monthLabel,
  nameKey,
  phoneKey,
  samePhoneLabel,
  samePhoneRefs,
  searchKindLine,
} from "@/components/v2/modals/add-candidates-identity";

const person = (id: number, name: string, lastname: string, phone: string | null = null) => ({
  id,
  name,
  lastname,
  phone,
});

describe("phoneKey", () => {
  it("porównuje ostatnie 9 cyfr niezależnie od zapisu", () => {
    expect(phoneKey("+48 000 000 101")).toBe("000000101");
    expect(phoneKey("000-000-101")).toBe("000000101");
    expect(phoneKey("0048 (000) 000 101")).toBe("000000101");
  });

  it("brak numeru albo za krótki zapis to nie numer", () => {
    expect(phoneKey(null)).toBeNull();
    expect(phoneKey("")).toBeNull();
    expect(phoneKey("brak")).toBeNull();
    expect(phoneKey("12 34 56")).toBeNull();
  });
});

describe("nameKey i largestHomonymGroup", () => {
  it("ignoruje wielkość liter i nadmiarowe spacje", () => {
    expect(nameKey("  Anna ", "PRZYKŁADOWA")).toBe(nameKey("anna", "Przykładowa"));
  });

  it("zwraca największą grupę z co najmniej dwiema osobami", () => {
    const group = largestHomonymGroup([
      person(1, "Anna", "Przykładowa"),
      person(2, "Jan", "Testowy"),
      person(3, "anna", "przykładowa"),
      person(4, "Anna", "Przykładowa"),
      person(5, "Jan", "Testowy"),
    ]);
    expect(group).toEqual({ label: "Anna Przykładowa", count: 3 });
  });

  it("bez powtórzeń nie ma paska", () => {
    expect(largestHomonymGroup([person(1, "Anna", "Przykładowa"), person(2, "Jan", "Testowy")])).toBeNull();
    expect(largestHomonymGroup([])).toBeNull();
  });
});

describe("samePhoneRefs", () => {
  it("pierwszy wiersz z numerem jest bez plakietki, kolejne wskazują na niego", () => {
    const refs = samePhoneRefs(
      [
        person(10, "Anna", "Przykładowa", "+48 000 000 101"),
        person(11, "Anna", "Przykładowa", "000 000 102"),
        person(12, "Anna", "Przykładowa", "000-000-101"),
      ],
      [],
    );
    expect(refs.has(10)).toBe(false);
    expect(refs.has(11)).toBe(false);
    expect(refs.get(12)).toEqual({ kind: "row", id: 10, row: 1 });
    expect(samePhoneLabel(refs.get(12)!)).toBe("Ten sam telefon co 1. wiersz");
  });

  it("osoba już w rekrutacji ma pierwszeństwo przed wierszem wyżej", () => {
    const refs = samePhoneRefs(
      [person(10, "Anna", "Przykładowa", "000 000 101"), person(12, "Anna", "Przykładowa", "000000101")],
      [person(20, "Anna", "Przykładowa", "+48 000 000 101")],
    );
    expect(refs.get(10)).toEqual({ kind: "in_job", id: 20 });
    expect(refs.get(12)).toEqual({ kind: "in_job", id: 20 });
    expect(samePhoneLabel(refs.get(10)!)).toBe("Ten sam telefon co osoba już w tej rekrutacji");
  });

  it("wiersze bez numeru nie są sobie równe", () => {
    const refs = samePhoneRefs(
      [person(10, "Anna", "Przykładowa"), person(11, "Anna", "Przykładowa", "")],
      [person(20, "Anna", "Przykładowa")],
    );
    expect(refs.size).toBe(0);
  });
});

describe("searchKindLine", () => {
  const base = { mode: "literal" as const, rule: "", name: [], email: null, phone: null, skills: [], locations: [], other: [] };

  it("nazywa szukanie po numerze i po adresie", () => {
    expect(searchKindLine({ ...base, kind: "phone", phone: "000000101" })).toBe("Szukam po numerze telefonu");
    expect(searchKindLine({ ...base, kind: "email", email: "anna@example.com" })).toBe("Szukam po adresie e-mail");
  });

  it("przy imieniu i nazwisku, opisie i braku frazy milczy", () => {
    expect(searchKindLine({ ...base, kind: "name" })).toBeNull();
    expect(searchKindLine({ ...base, kind: "text", mode: "semantic" })).toBeNull();
    expect(searchKindLine(null)).toBeNull();
    expect(searchKindLine(undefined)).toBeNull();
  });
});

describe("monthLabel", () => {
  it("czyta dzień i znacznik czasu w kalendarzu firmy", () => {
    expect(monthLabel("2026-03-15")).toBe("03.2026");
    // 31.12 23:30 UTC to już 1 stycznia w Warszawie.
    expect(monthLabel("2025-12-31T23:30:00Z")).toBe("01.2026");
  });

  it("brak albo zła data nie psuje wiersza", () => {
    expect(monthLabel(null)).toBeNull();
    expect(monthLabel("")).toBeNull();
    expect(monthLabel("nie-data")).toBeNull();
  });
});
