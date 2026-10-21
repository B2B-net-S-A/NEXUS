/**
 * „Dop.” w przeglądarce — lustro `ranking_weights.engine_weights` i
 * `ranking_lab.score` z backendu. Podgląd na żywo przelicza kolejność ze
 * składników oceny bez AI i bez kolejnych zapytań. Zgodność z silnikiem
 * pilnuje wspólny plik `lib/__fixtures__/ranking-score-cases.json`
 * (wygenerowany z prawdziwego silnika; czytają go oba testy).
 */
import type {
  RankingComponents,
  RankingLayer,
  RankingPanelWeights,
  RankingPreviewPerson,
} from "@/lib/api";

export const BASE_LAYERS: RankingLayer[] = [
  "semantic",
  "skills",
  "salary",
  "location",
  "availability",
];

/** Ważność stawki w skali panelu (zablokowana, decyzja D2). */
export const FIXED_SALARY = 15;
export const FIXED_AVAILABILITY = 0;
const CHAMPION_RESERVE = 10;
const BASE_BUDGET = 100 - CHAMPION_RESERVE;

export type LayerWeights = Record<RankingLayer, number>;

const round4 = (value: number) => Math.round(value * 10_000) / 10_000;

/** Wagi profilu w bazie (bez warstwy screeningu) — jak `engine_weights`. */
export function engineWeights(panel: RankingPanelWeights): LayerWeights {
  const importance: LayerWeights = {
    semantic: panel.semantic,
    skills: panel.skills,
    location: panel.location,
    salary: FIXED_SALARY,
    availability: FIXED_AVAILABILITY,
  };
  const total = BASE_LAYERS.reduce((acc, name) => acc + importance[name], 0);
  const scale = BASE_BUDGET / total;
  return Object.fromEntries(
    BASE_LAYERS.map((name) => [name, round4(importance[name] * scale)]),
  ) as LayerWeights;
}

/** Wagi przeliczone do 100 — jak `base_fit_profile`. */
export function normalized(weights: LayerWeights): LayerWeights {
  const total = BASE_LAYERS.reduce((acc, name) => acc + (weights[name] ?? 0), 0);
  if (total <= 0) throw new Error("co najmniej jedna waga musi być większa od zera");
  return Object.fromEntries(
    BASE_LAYERS.map((name) => [name, ((weights[name] ?? 0) * 100) / total]),
  ) as LayerWeights;
}

/** Udział warstw w „Dop.” (%) dla ważności z panelu. */
export function panelShares(panel: RankingPanelWeights): LayerWeights {
  return normalized(engineWeights(panel));
}

function composite(
  c: RankingComponents,
  weights: LayerWeights,
  renormalize: boolean,
): number {
  let earned = 0;
  let available = 0;
  let plain = 0;
  for (const name of BASE_LAYERS) {
    const [fraction, share, scored] = c.layers[name];
    const maxPoints = share * weights[name];
    const points = fraction * maxPoints;
    plain += points;
    if (scored) {
      earned += points;
      available += maxPoints;
    }
  }
  if (renormalize) {
    if (c.extra) {
      earned += c.extra[0];
      available += c.extra[1];
    }
    return available > 0 ? (earned / available) * 100 : 0;
  }
  if (c.extra) return ((plain + c.extra[0]) * 100) / (100 + c.extra[1]);
  return plain;
}

/** „Dop.” osoby dla podanych wag (dowolna skala — przeliczane do 100). */
export function score(
  c: RankingComponents,
  weights: LayerWeights,
  renormalize: boolean,
): number {
  const total = composite(c, normalized(weights), renormalize);
  return total > 0 ? total * c.factor : total;
}

/** Jak `auto_match_rules.is_good_match`: próg + ≥ 1 trafione „musi mieć”. */
export function proposalEligible(c: RankingComponents, value: number, threshold: number) {
  return value >= threshold && (c.must_total === 0 || c.matched_must > 0);
}

export interface RankedPerson {
  person: RankingPreviewPerson;
  value: number;
  rank: number;
}

/** Kolejność „Dop.” malejąco; remis — kolejność wektora (jak na serwerze). */
export function rankPeople(
  people: RankingPreviewPerson[],
  weights: LayerWeights,
  renormalize: boolean,
): RankedPerson[] {
  return people
    .map((person) => ({ person, value: score(person, weights, renormalize) }))
    .sort((a, b) => b.value - a.value || a.person.vector_rank - b.person.vector_rank)
    .map((item, index) => ({ ...item, rank: index + 1 }));
}

/** Badge „Dop.” — zaokrąglenie jak `display_score` na serwerze. */
export function displayScore(value: number): number {
  return Math.floor(Math.min(Math.max(value, 0), 100) + 0.5);
}

export function sameWeights(a: RankingPanelWeights, b: RankingPanelWeights): boolean {
  return (
    a.semantic === b.semantic &&
    a.skills === b.skills &&
    a.location === b.location &&
    a.threshold === b.threshold
  );
}
