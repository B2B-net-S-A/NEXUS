import { describe, expect, it } from "vitest";

import { peopleCount, reportsSummary } from "../lifecycle-format";

const base = {
  kind: "reports",
  count: 3,
  planned_count: 3,
  receiver_name: "Marta Fikcyjna",
  status: "planned",
  result: null,
};

describe("podwładni przy odejściu (D5)", () => {
  it("odmienia liczbę osób", () => {
    expect(peopleCount(1)).toBe("1 osoba");
    expect(peopleCount(3)).toBe("3 osoby");
    expect(peopleCount(5)).toBe("5 osób");
    expect(peopleCount(12)).toBe("12 osób");
    expect(peopleCount(22)).toBe("22 osoby");
  });

  it("mówi, kto zostanie przełożonym", () => {
    expect(reportsSummary([base])).toBe(
      "Podwładni: 3 osoby. Po przekazaniu ich przełożonym będzie Marta Fikcyjna — od tej chwili wnioski i timesheety idą do tej osoby.",
    );
  });

  it("bez przejmującego ostrzega, że konto poczeka", () => {
    expect(reportsSummary([{ ...base, receiver_name: null }])).toMatch(
      /^Podwładni: 3 osoby\. Wskaż, kto zostanie ich przełożonym/,
    );
  });

  it("po przekazaniu liczy z wyniku, nie ze stanu na teraz", () => {
    expect(
      reportsSummary([{ ...base, status: "done", count: 0, result: { people: 2 } }]),
    ).toBe("Podwładni przekazani (2 osoby) — ich przełożonym jest Marta Fikcyjna.");
  });

  it("bez podwładnych albo bez liczby — nic", () => {
    expect(reportsSummary([{ ...base, count: 0 }])).toBeNull();
    expect(reportsSummary([{ ...base, count: null }])).toBeNull();
    expect(reportsSummary([{ ...base, kind: "my_people" }])).toBeNull();
    expect(reportsSummary([])).toBeNull();
  });
});
