/**
 * Shape + summariser for the cached hybrid-score breakdown (SEARCH-P1-03).
 * The backend stores this per (candidate, job) and the search-scores endpoint
 * returns it read-only, so the row detail panel can show WHY a candidate ranks
 * (per-layer points + matched / missing skills).
 */

export interface MatchLayer {
  points: number;
  max: number;
  reason?: string;
  status?: "scored" | "unknown" | "not_comparable" | string;
}

export interface MatchBreakdown {
  total?: number;
  semantic?: MatchLayer;
  skills?: MatchLayer;
  salary?: MatchLayer;
  location?: MatchLayer;
  availability?: MatchLayer;
  champion_fit?: MatchLayer;
  matching_must?: string[];
  gap_must?: string[];
  matching_nice?: string[];
  gap_nice?: string[];
}

export interface BreakdownLayer {
  key: string;
  label: string;
  points: number;
  max: number;
  status?: MatchLayer["status"];
  reason?: string;
}

export interface BreakdownSummary {
  layers: BreakdownLayer[];
  matchedMust: string[];
  gapMust: string[];
  matchedNice: string[];
  gapNice: string[];
}

const LAYER_LABELS: Array<[keyof MatchBreakdown, string]> = [
  ["skills", "Umiejętności"],
  ["semantic", "Semantyczne"],
  ["location", "Lokalizacja"],
  ["availability", "Dyspozycyjność"],
  ["salary", "Stawka B2B"],
  ["champion_fit", "Champion"],
];

function strList(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

/**
 * Reduce a raw breakdown into a render-ready summary: only layers that are in
 * play (``max > 0``), plus matched/missing must & nice skills.
 */
export function summarizeBreakdown(
  raw: MatchBreakdown | null | undefined,
): BreakdownSummary {
  const layers: BreakdownLayer[] = [];
  if (raw) {
    for (const [key, label] of LAYER_LABELS) {
      const layer = raw[key] as MatchLayer | undefined;
      if (layer && typeof layer.max === "number" && layer.max > 0) {
        layers.push({
          key,
          label,
          points: Math.round(layer.points ?? 0),
          max: Math.round(layer.max),
          status: layer.status,
          reason: layer.reason,
        });
      }
    }
  }
  return {
    layers,
    matchedMust: strList(raw?.matching_must),
    gapMust: strList(raw?.gap_must),
    matchedNice: strList(raw?.matching_nice),
    gapNice: strList(raw?.gap_nice),
  };
}

export type CompareStatus = "matched" | "gap" | "na";

export interface SkillCompareRow {
  skill: string;
  /** candidate_id → whether they matched this skill, are missing it, or it's
   * not a requirement for them (na). */
  status: Record<number, CompareStatus>;
}

/**
 * Build the request-aware compare rows for one skill kind (must / nice): the
 * union of all skills across the selected candidates, each row marking every
 * candidate as matched / gap / na (SEARCH-P1-06). Rows are sorted so the most
 * widely-required skills surface first, then alphabetically.
 */
export function compareSkillRows(
  candidateIds: number[],
  breakdowns: Record<string, MatchBreakdown | undefined>,
  kind: "must" | "nice",
): SkillCompareRow[] {
  const summaries = new Map<number, BreakdownSummary>();
  const skills = new Set<string>();
  for (const cid of candidateIds) {
    const s = summarizeBreakdown(breakdowns[String(cid)]);
    summaries.set(cid, s);
    const matched = kind === "must" ? s.matchedMust : s.matchedNice;
    const gap = kind === "must" ? s.gapMust : s.gapNice;
    for (const t of [...matched, ...gap]) skills.add(t);
  }

  const rows: SkillCompareRow[] = [];
  for (const skill of skills) {
    const status: Record<number, CompareStatus> = {};
    for (const cid of candidateIds) {
      const s = summaries.get(cid)!;
      const matched = kind === "must" ? s.matchedMust : s.matchedNice;
      const gap = kind === "must" ? s.gapMust : s.gapNice;
      status[cid] = matched.includes(skill)
        ? "matched"
        : gap.includes(skill)
          ? "gap"
          : "na";
    }
    rows.push({ skill, status });
  }

  const matchedCount = (r: SkillCompareRow) =>
    Object.values(r.status).filter((v) => v === "matched").length;
  rows.sort(
    (a, b) => matchedCount(b) - matchedCount(a) || a.skill.localeCompare(b.skill),
  );
  return rows;
}

/** True when a breakdown has anything worth showing in the detail panel. */
export function hasBreakdownDetail(raw: MatchBreakdown | null | undefined): boolean {
  const s = summarizeBreakdown(raw);
  return (
    s.layers.length > 0 ||
    s.matchedMust.length > 0 ||
    s.gapMust.length > 0 ||
    s.matchedNice.length > 0 ||
    s.gapNice.length > 0
  );
}
