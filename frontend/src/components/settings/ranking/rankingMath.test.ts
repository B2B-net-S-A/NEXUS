import { describe, expect, it } from "vitest";

import cases from "@/lib/__fixtures__/ranking-score-cases.json";
import type { RankingComponents, RankingPanelWeights, RankingPreviewPerson } from "@/lib/api";

import { restorable } from "./HistoryTab";
import {
  displayScore,
  engineWeights,
  panelShares,
  proposalEligible,
  rankPeople,
  sameWeights,
  score,
  type LayerWeights,
} from "./rankingMath";

interface FixtureCase {
  components: RankingComponents;
  renormalize: boolean;
  panel: RankingPanelWeights;
  weights: LayerWeights;
  expected: number;
}

const FIXTURE = (cases as unknown as { cases: FixtureCase[] }).cases;

describe("„Dop.” w przeglądarce = silnik na serwerze", () => {
  it("ma przypadki z obu trybów składania wyniku", () => {
    expect(FIXTURE.length).toBeGreaterThanOrEqual(20);
    expect(FIXTURE.some((c) => c.renormalize)).toBe(true);
    expect(FIXTURE.some((c) => !c.renormalize)).toBe(true);
  });

  it.each(FIXTURE.map((c, i) => [i, c] as const))("przypadek %i", (_i, c) => {
    expect(engineWeights(c.panel)).toEqual(c.weights);
    expect(score(c.components, c.weights, c.renormalize)).toBeCloseTo(c.expected, 3);
  });
});

describe("ważności panelu", () => {
  it("60/10/5 to dzisiejsze 67/11/6/17/0", () => {
    const shares = panelShares({ semantic: 60, skills: 10, location: 5, threshold: 70 });
    expect(Math.round(shares.semantic)).toBe(67);
    expect(Math.round(shares.skills)).toBe(11);
    expect(Math.round(shares.location)).toBe(6);
    expect(Math.round(shares.salary)).toBe(17);
    expect(shares.availability).toBe(0);
  });

  it("więcej umiejętności zabiera udział CV i stawce", () => {
    const shares = panelShares({ semantic: 60, skills: 30, location: 5, threshold: 70 });
    expect(shares.skills).toBeCloseTo(27.27, 1);
    expect(shares.semantic).toBeCloseTo(54.55, 1);
  });

  it("porównuje szkic z opublikowanymi razem z progiem", () => {
    const a = { semantic: 60, skills: 10, location: 5, threshold: 70 };
    expect(sameWeights(a, { ...a })).toBe(true);
    expect(sameWeights(a, { ...a, threshold: 75 })).toBe(false);
  });
});

function person(id: number, sem: number, sk: number, rank: number, matched = 1): RankingPreviewPerson {
  return {
    candidate_id: id,
    layers: {
      semantic: [sem, 1, true],
      skills: [sk, 1, true],
      salary: [0.65, 1, true],
      location: [1, 1, true],
      availability: [0, 1, true],
    },
    extra: null,
    factor: 1,
    matched_must: matched,
    must_total: 2,
    vector_rank: rank,
    name: `Osoba ${id}`,
    city: null,
    positive: false,
  };
}

describe("kolejność i propozycje", () => {
  const people = [person(1, 0.95, 0.2, 1), person(2, 0.7, 1, 2), person(3, 0.7, 1, 3)];

  it("układa malejąco, remis rozstrzyga kolejność wektora", () => {
    const now = engineWeights({ semantic: 60, skills: 10, location: 5, threshold: 70 });
    const skills = engineWeights({ semantic: 60, skills: 60, location: 5, threshold: 70 });
    expect(rankPeople(people, now, false).map((p) => p.person.candidate_id)).toEqual([1, 2, 3]);
    expect(rankPeople(people, skills, false).map((p) => p.person.candidate_id)).toEqual([2, 3, 1]);
  });

  it("propozycja wymaga progu i trafionego „musi mieć”", () => {
    expect(proposalEligible(person(1, 1, 1, 1), 80, 70)).toBe(true);
    expect(proposalEligible(person(1, 1, 1, 1, 0), 80, 70)).toBe(false);
    expect(proposalEligible(person(1, 1, 1, 1), 69.9, 70)).toBe(false);
  });

  it("zaokrągla jak serwer (pół w górę)", () => {
    expect(displayScore(72.5)).toBe(73);
    expect(displayScore(-3)).toBe(0);
    expect(displayScore(104)).toBe(100);
  });
});

describe("„Przywróć” tylko dla wag ogólnych", () => {
  const base = {
    id: 1,
    created_at: "2026-10-21T10:00:00+02:00",
    actor_name: null,
    profile_id: 4,
    before: {},
    reason: null,
    measurement: null,
  };
  it("publikacja i edycja aktywnego profilu ogólnego", () => {
    expect(
      restorable({ ...base, kind: "publish", after: { panel: { semantic: 60, skills: 30, location: 5, threshold: 70 } } }),
    ).toBe(true);
    expect(restorable({ ...base, kind: "admin_edit", after: { weights: { semantic: 60 }, active: true } })).toBe(true);
  });
  it("nie dla profilu klienta, osoby, nieaktywnego ani usunięcia", () => {
    expect(restorable({ ...base, kind: "admin_edit", after: { weights: { semantic: 60 }, client_id: 42 } })).toBe(false);
    expect(restorable({ ...base, kind: "admin_edit", after: { weights: { semantic: 60 }, user_id: 7 } })).toBe(false);
    expect(restorable({ ...base, kind: "admin_edit", after: { weights: { semantic: 60 }, active: false } })).toBe(false);
    expect(restorable({ ...base, kind: "admin_edit", after: {} })).toBe(false);
  });
});
