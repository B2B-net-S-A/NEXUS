import { describe, expect, it } from "vitest";

import {
  candidateHourly,
  peopleLabel,
  profileTiers,
  selectionHourly,
  startingPicks,
  teamHourlyRange,
  teamStart,
  togglePick,
  type SeatGroup,
} from "../team-logic";
import { person } from "./team-fixtures";
import type { PanelCandidate } from "@/lib/api/clientPanel";

const id = (c: PanelCandidate) => c.public_id;

function groups(): SeatGroup<PanelCandidate>[] {
  return [
    { key: "a", headcount: 1, candidates: [person("a1", "140.00", "2026-11-01"), person("a2", "120.00", "2026-12-01")] },
    { key: "t", headcount: 2, candidates: [person("t1", "100.00", "2026-11-01"), person("t2", null, null)] },
  ];
}

describe("cena zespołu od–do", () => {
  it("na każdym miejscu najtańsza i najdroższa osoba razy liczba miejsc", () => {
    const range = teamHourlyRange(groups(), candidateHourly);
    expect(range).toEqual({ min: 120 + 2 * 100, max: 140 + 2 * 100, unpriced: [] });
  });

  it("stanowisko bez żadnej stawki nie wchodzi do sumy, ale jest nazwane", () => {
    const list = [...groups(), { key: "x", headcount: 3, candidates: [person("x1", null, null)] }];
    expect(teamHourlyRange(list, candidateHourly)).toMatchObject({ min: 320, max: 340, unpriced: ["x"] });
  });

  it("stawka dzienna nie udaje godzinowej", () => {
    const daily = { ...person("d", null, null), rate: { value: "1200", unit: "daily", currency: "PLN" } };
    expect(candidateHourly(daily)).toBeNull();
  });
});

describe("skład klienta", () => {
  it("liczy sumę, puste miejsca i osoby bez stawki osobno", () => {
    const result = selectionHourly(groups(), { a: ["a2"], t: ["t2"] }, id, candidateHourly);
    expect(result).toEqual({ total: 120, openSeats: 1, unpriced: 1 });
  });

  it("nieznany identyfikator w wyborze nie liczy się jako osoba", () => {
    expect(selectionHourly(groups(), { a: ["obcy"] }, id, candidateHourly).openSeats).toBe(3);
  });

  it("na pełnym stanowisku nowa osoba zastępuje ostatnio wybraną, klik w wybraną ją zdejmuje", () => {
    expect(togglePick({ a: ["a1"] }, "a", 1, "a2")).toEqual({ a: ["a2"] });
    expect(togglePick({ t: ["t1"] }, "t", 2, "t2")).toEqual({ t: ["t1", "t2"] });
    expect(togglePick({ t: ["t1", "t2"] }, "t", 2, "t3")).toEqual({ t: ["t1", "t3"] });
    expect(togglePick({ t: ["t1", "t2"] }, "t", 2, "t1")).toEqual({ t: ["t2"] });
  });

  it("skład startowy: najwcześniej dostępni, przy remisie tańsi, bez „nie pasuje”", () => {
    const list: SeatGroup<PanelCandidate>[] = [
      {
        key: "a",
        headcount: 1,
        candidates: [
          person("drozszy", "150.00", "2026-11-01"),
          person("tanszy", "130.00", "2026-11-01"),
          person("odrzucony", "90.00", "2026-10-01", { state: "not_fit" }),
        ],
      },
    ];
    expect(startingPicks(list)).toEqual({ a: ["tanszy"] });
  });

  it("start zespołu to najpóźniejsza data; „do ustalenia” liczy się osobno", () => {
    expect(teamStart(groups(), { a: ["a2"], t: ["t1", "t2"] }, "2026-11-15")).toEqual({
      date: "2026-12-01",
      unknown: 1,
    });
    expect(teamStart(groups(), { a: ["a1"] }, "2026-11-15")).toEqual({ date: "2026-11-15", unknown: 0 });
  });
});

describe("drobiazgi", () => {
  it("profile stawek rosnąco, bez osób bez stawki", () => {
    const tiers = profileTiers([person("1", "150.00", "2026-11-01"), person("2", "130.00", null), person("3", null, null)]);
    expect(tiers.map((t) => [t.rate, t.count, t.availableNow])).toEqual([
      [130, 1, 0],
      [150, 1, 1],
    ]);
  });

  it("odmiana „osoba”", () => {
    expect([1, 2, 4, 5, 12, 22, 25].map(peopleLabel)).toEqual([
      "1 osoba",
      "2 osoby",
      "4 osoby",
      "5 osób",
      "12 osób",
      "22 osoby",
      "25 osób",
    ]);
  });
});
