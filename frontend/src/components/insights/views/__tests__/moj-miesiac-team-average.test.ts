import { describe, expect, it } from "vitest";
import { teamAverageCv } from "../MojMiesiacView";

// Runda 6 audytu: średnia zespołu w „Moim miesiącu” pochodzi z pola
// `anchored_average` (atrybucja weryfikatora), nie z wierszy tabeli
// liczonych po „kto kliknął”.
describe("teamAverageCv", () => {
  it("zaokrągla średnią policzoną na serwerze", () => {
    expect(
      teamAverageCv({
        attribution: "verifier_anchored",
        people: 3,
        recommendations: 11.6,
      }),
    ).toBe(12);
  });

  it("brak średniej to brak porównania, nie zero", () => {
    expect(teamAverageCv(undefined)).toBeNull();
    expect(
      teamAverageCv({
        attribution: "verifier_anchored",
        people: 0,
        recommendations: null,
      }),
    ).toBeNull();
  });
});
