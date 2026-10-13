/**
 * Audyt 13.10.2026 (okno „Dodaj kandydatów”): numer-zaślepka „000 000 000”
 * u dwóch różnych osób dawał „Ten sam telefon” i „Scal…”, pole z dwoma
 * numerami porównywało tylko ostatni, a numer szukany po 6–8 cyfrach nie był
 * podświetlony. Ta sama reguła zaślepek jest w `dedup_service._normalize_phone`.
 */
import { describe, expect, it } from "vitest";

import {
  phoneKey,
  phoneKeys,
  phoneMatchesQuery,
  samePhoneRefs,
} from "@/components/v2/modals/add-candidates-identity";

const person = (id: number, phone: string | null) => ({ id, name: "Anna", lastname: "Przykładowa", phone });

describe("phoneKey — zaślepki nie są numerem", () => {
  it.each(["000 000 000", "+48 000 000 000", "000-000-000", "111 111 111", "999999999", "0048 555 555 555"])(
    "%s → brak numeru",
    (value) => {
      expect(phoneKey(value)).toBeNull();
      expect(phoneKeys(value)).toEqual([]);
    },
  );

  it("prawdziwy numer bez zmian: ostatnie 9 cyfr", () => {
    expect(phoneKey("+48 601 204 118")).toBe("601204118");
    expect(phoneKey("601-204-118")).toBe("601204118");
    expect(phoneKey("000 000 101")).toBe("000000101");
    expect(phoneKey("12345")).toBeNull();
  });
});

describe("phoneKeys — każdy numer z pola osobno", () => {
  it("dwa numery rozdzielone znakiem albo słowem", () => {
    expect(phoneKeys("601 204 118 / 502 333 444")).toEqual(["601204118", "502333444"]);
    expect(phoneKeys("+48 601 204 118, 502-333-444")).toEqual(["601204118", "502333444"]);
    expect(phoneKeys("601204118 lub 502333444")).toEqual(["601204118", "502333444"]);
  });

  it("jeden numer z prefiksem kraju i nawiasem to wciąż jeden numer", () => {
    expect(phoneKeys("(+48) 601 204 118")).toEqual(["601204118"]);
    expect(phoneKeys("tel. 601 204 118")).toEqual(["601204118"]);
  });

  it("zaślepka obok prawdziwego numeru znika, prawdziwy zostaje", () => {
    expect(phoneKeys("000 000 000 / 601 204 118")).toEqual(["601204118"]);
  });

  it("numer wewnętrzny po „wew.” nie skleja się z numerem głównym", () => {
    expect(phoneKeys("22 123 45 67 wew. 123")).toEqual(["221234567"]);
  });
});

describe("samePhoneRefs — zaślepki i pola z dwoma numerami", () => {
  it("dwie osoby z „000 000 000” nie dostają plakietki", () => {
    const refs = samePhoneRefs([person(1, "000 000 000"), person(2, "+48 000-000-000")], [
      person(30, "000000000"),
    ]);
    expect(refs.size).toBe(0);
  });

  it("pierwszy numer z pola z dwoma numerami też się liczy", () => {
    const refs = samePhoneRefs(
      [person(1, "601 204 118"), person(2, "601-204-118 / 502 333 444")],
      [],
    );
    expect(refs.get(2)).toEqual({ kind: "row", id: 1, row: 1 });
  });

  it("drugi numer pola trafia w osobę z rekrutacji", () => {
    const refs = samePhoneRefs([person(1, "601 204 118, 502 333 444")], [person(30, "502333444")]);
    expect(refs.get(1)).toEqual({ kind: "in_job", id: 30 });
  });
});

describe("phoneMatchesQuery — podświetlenie jak wyszukiwanie (`phone_digits_clause`)", () => {
  it("6–8 cyfr to podciąg cyfr numeru", () => {
    expect(phoneMatchesQuery("+48 601 204 118", "204118")).toBe(true);
    expect(phoneMatchesQuery("+48 601 204 118", "6012041")).toBe(true);
    expect(phoneMatchesQuery("+48 601 204 118", "999999")).toBe(false);
  });

  it("9 cyfr i drugi numer w polu", () => {
    expect(phoneMatchesQuery("601 204 118", "601204118")).toBe(true);
    expect(phoneMatchesQuery("601 204 118 / 502 333 444", "502333444")).toBe(true);
  });

  it("bez numeru albo bez frazy nic nie świeci", () => {
    expect(phoneMatchesQuery(null, "204118")).toBe(false);
    expect(phoneMatchesQuery("601 204 118", null)).toBe(false);
    expect(phoneMatchesQuery("601 204 118", "")).toBe(false);
  });
});
