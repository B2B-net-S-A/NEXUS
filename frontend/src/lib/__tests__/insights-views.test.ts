import { describe, expect, it } from "vitest";

import {
  biggestGapVsTeam,
  buildSteps,
  compactPln,
  countDelta,
  gapSentence,
  myMonthSentence,
  pctDelta,
  placementsPl,
  previousComparablePeriod,
  previousSameStretch,
  sameStretchLabel,
  stepConversions,
  topWithRest,
  weakestStepIndex,
  weakestStepSentence,
  yearToDate,
} from "@/lib/insights-views";

const LABELS = ["Zweryfikowani", "CV wysłane", "Rozmowy", "Zatrudnieni"];

describe("lejek i najsłabsze przejście", () => {
  it("zerowy mianownik to brak procentu, nie 0%", () => {
    expect(stepConversions([10, 0, 0, 0])).toEqual([null, 0, null, null]);
  });

  it("wskazuje krok z najniższym przejściem", () => {
    const steps = buildSteps(LABELS, [412, 142, 61, 21]);
    expect(steps.map((s) => s.conversion)).toEqual([null, 34, 43, 34]);
    // Remis 34% = wcześniejszy krok: on odcina resztę lejka.
    expect(weakestStepIndex(steps)).toBe(1);
    expect(weakestStepSentence(steps)).toBe(
      "Najwięcej osób odpada między etapem „Zweryfikowani” a „CV wysłane” — przechodzi 34%.",
    );
  });

  it("dokłada wartość z poprzedniego okresu", () => {
    const now = buildSteps(LABELS, [412, 142, 61, 21]);
    const before = buildSteps(LABELS, [400, 156, 60, 20]);
    expect(
      weakestStepSentence(now, { previous: before, previousLabel: "w sierpniu" }),
    ).toMatch(/przechodzi 34% \(w sierpniu 39%\)\.$/);
  });

  it("lejek bez danych nie daje zdania", () => {
    expect(weakestStepSentence(buildSteps(LABELS, [0, 0, 0, 0]))).toBeNull();
  });
});

describe("porównanie z zespołem", () => {
  it("wskazuje największą stratę względem zespołu", () => {
    const mine = buildSteps(LABELS, [58, 11, 6, 2]);
    const team = buildSteps(LABELS, [412, 142, 61, 21]);
    expect(biggestGapVsTeam(mine, team)).toEqual({ index: 1, mine: 19, team: 34 });
    expect(gapSentence(mine, team)).toBe(
      "Najwięcej tracisz między etapem „Zweryfikowani” a „CV wysłane”: 19%, w zespole 34%.",
    );
  });

  it("różnica poniżej 5 pp to szum, nie wniosek", () => {
    const mine = buildSteps(LABELS, [100, 32, 14, 5]);
    const team = buildSteps(LABELS, [100, 34, 15, 5]);
    expect(biggestGapVsTeam(mine, team)).toBeNull();
  });
});

describe("okno porównania", () => {
  it("24 września → 1–24 sierpnia", () => {
    expect(previousSameStretch(new Date(2026, 8, 24))).toEqual({
      date_from: "2026-08-01",
      date_to: "2026-08-24",
    });
    expect(sameStretchLabel(new Date(2026, 8, 24))).toBe("w dniach 1–24 sierpnia");
  });

  it("31 marca → koniec lutego", () => {
    expect(previousSameStretch(new Date(2026, 2, 31))).toEqual({
      date_from: "2026-02-01",
      date_to: "2026-02-28",
    });
  });

  it("styczeń porównuje z grudniem poprzedniego roku", () => {
    expect(previousSameStretch(new Date(2027, 0, 10))).toEqual({
      date_from: "2026-12-01",
      date_to: "2026-12-10",
    });
  });

  it("bieżący miesiąc → ten sam odcinek, zamknięty kwartał → poprzedni kwartał", () => {
    expect(
      previousComparablePeriod({ period: "month", offset: 0 }, new Date(2026, 8, 24)),
    ).toEqual({
      params: { period: "custom", date_from: "2026-08-01", date_to: "2026-08-24" },
      label: "w dniach 1–24 sierpnia",
    });
    expect(
      previousComparablePeriod({ period: "quarter", offset: -1 }, new Date(2026, 8, 24)),
    ).toEqual({
      params: { period: "quarter", offset: -2 },
      label: "w poprzednim kwartale",
    });
    expect(previousComparablePeriod({ period: "custom" }, new Date())).toBeNull();
  });
});

describe("delty", () => {
  it("wzrost dobry, spadek zły, brak danych = brak delty", () => {
    expect(countDelta(21, 17, "w sierpniu")).toEqual({
      text: "▲ 4 więcej niż w sierpniu",
      tone: "good",
    });
    expect(countDelta(3, 5, "w sierpniu")?.tone).toBe("bad");
    expect(countDelta(3, 5, "x", { lowerIsBetter: true })?.tone).toBe("good");
    expect(countDelta(null, 5, "x")).toBeNull();
  });

  it("delta procentowa z serwera", () => {
    expect(pctDelta(4.2, "wobec Q2")).toEqual({ text: "▲ 4% wobec Q2", tone: "good" });
    expect(pctDelta(null, "wobec Q2")).toBeNull();
  });
});

describe("zdanie Mojego miesiąca", () => {
  const base = {
    placements: 2,
    placementsTarget: 1,
    raceRank: 3,
    leaderPlacements: 4,
    leaderName: "Ola K.",
    verificationsToday: 3,
    verificationsDailyTarget: 4,
  };

  it("mówi o celu, wyścigu i dzisiejszych weryfikacjach", () => {
    expect(myMonthSentence(base)).toBe(
      "Masz 2 placementy w tym miesiącu — cel osiągnięty. Jesteś 3. w wyścigu placementów — do prowadzenia (Ola K.) brakuje Ci 2. Dziś 3 z 4 weryfikacji.",
    );
  });

  it("poza rankingiem nie wymyśla miejsca", () => {
    expect(myMonthSentence({ ...base, placements: 0, raceRank: null })).toBe(
      "Masz 0 placementów w tym miesiącu — do celu brakuje 1. Dziś 3 z 4 weryfikacji.",
    );
  });

  it("odmiana placementów", () => {
    expect([1, 2, 5, 12, 22].map(placementsPl)).toEqual([
      "placement",
      "placementy",
      "placementów",
      "placementów",
      "placementy",
    ]);
  });
});

describe("kwoty i klienci", () => {
  it("kompaktowe kwoty", () => {
    expect(compactPln(3_410_000)).toBe("3,41 mln zł");
    expect(compactPln(612_000)).toBe("612 tys. zł");
    expect(compactPln(null)).toBe("—");
  });

  it("top N + pozostali; brak kwoty nie udaje zera", () => {
    const result = topWithRest(
      [
        { name: "A", value: 110 },
        { name: "B", value: 80 },
        { name: "C", value: 61 },
        { name: "D", value: 49 },
        { name: "E", value: null },
      ],
      2,
    );
    expect(result.top.map((r) => r.name)).toEqual(["A", "B"]);
    expect(result.rest).toBe(110);
    expect(result.total).toBe(300);
    expect(result.top3Share).toBe(84);
  });

  it("rok do dziś liczy tylko pełne miesiące w obu latach", () => {
    expect(yearToDate([18, 20, 22, 5], [15, 17, 19, 16], 3)).toEqual({
      current: 60,
      previous: 51,
    });
    expect(yearToDate([1], [2], 0)).toBeNull();
  });
});
