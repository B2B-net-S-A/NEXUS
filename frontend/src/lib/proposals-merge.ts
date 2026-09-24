/**
 * Segment „Propozycje z bazy": cztery źródła → JEDNA lista osób spoza rekrutacji.
 *
 * Czyste funkcje, bez Reacta i bez sieci. Trzy reguły, których łatwo nie
 * dopilnować w komponencie:
 *  - wynik dopasowania NIGDY nie jest zmyślany: nieznany = `null`. Kolumna
 *    „Dop." niesie WYŁĄCZNIE kanoniczne dopasowanie (żywy przegląd bazy
 *    i skrzynka propozycji); punktacja „z podobnych projektów"
 *    (`historical_score`) ani `total_score` rekomendacji do niej nie trafiają;
 *  - osoba już w pipeline'ie znika z listy niezależnie od źródła;
 *  - kolejność jest stabilna (dopasowanie ↓, nowe, nazwisko, id), żeby
 *    odświeżenie w tle nie przetasowywało tabeli pod kursorem.
 */

import type {
  HistoricalCandidate,
  MatchEligibility,
  ProposalCandidateItem,
  RateFit,
  WorkTimeFit,
} from "@/lib/api";
import type { CandidateSearchRow } from "@/lib/full-candidate-search-api";
import type {
  ProposalInboxItem,
  ProposalReassignFrom,
  ProposalTraineeHandover,
} from "@/lib/job-proposals-api";
import { SEARCH_AVAILABILITY_OPTIONS } from "@/lib/search-availability";
import {
  PROPOSAL_SOURCE_LABEL,
  type ProposalPersonRow,
  type ProposalSource,
} from "@/components/v2/recruitment/types";

/** Skąd wiersz trafił do scalenia — steruje telemetrią dodania i „Pomiń". */
export type ProposalOrigin = "inbox" | "run" | "similar" | "recommendation";

export type RequirementStatus = "met" | "unknown" | "not_met";

export interface ProposalRequirement {
  label: string;
  level: "must" | "nice";
  status: RequirementStatus;
  /** Potwierdzone w weryfikacji rekrutera (tylko z żywego przeglądu). */
  verified: boolean;
}

export interface ProposalSimilarProject {
  jobId: number;
  title: string;
  stage: string;
}

/** Wszystko, czego panel potrzebuje ponad wiersz tabeli — bez dociągania N+1. */
export interface ProposalDetail {
  candidateId: number;
  title: string | null;
  city: string | null;
  rateHourly: number | null;
  /** Rola bez odczytu finansów: „—" znaczy „ukryte", nie „brak danych". */
  rateRedacted: boolean;
  availabilityStatus: string | null;
  availabilityDate: string | null;
  requirements: ProposalRequirement[];
  eligibility: MatchEligibility | null;
  rateFit: RateFit | null;
  officeFit: string | null;
  /** Sprzeczny wymiar pracy (plakietka, nie ukrycie) — z żywego przeglądu. */
  workTimeFit?: WorkTimeFit | null;
  similarProjects: ProposalSimilarProject[];
  /** Ten sam klient już tę osobę rozważał / odrzucił (z podobnych projektów). */
  sameClient: boolean;
  rejectedBySameClient: boolean;
  origins: ProposalOrigin[];
  firstSeenAt: string | null;
  /** Podsumowanie AI osoby — niesie je wyłącznie wiersz żywego przeglądu bazy. */
  aiSummary: string | null;
  /**
   * Must-have BRAMKI dealbreakera (`match.missing_must`), których tej osobie
   * brakuje — węższe niż lista wymagań: bez nich osoba jest ukrywana na
   * pozostałych powierzchniach rankingu. Tylko z żywego przeglądu.
   */
  missingMustGate: string[];
  /** Przepięcie (0341): rekrutacja, w której osoba była już u klienta. */
  reassignFrom: ProposalReassignFrom | null;
  /** Praktykant przekazał osobę po rozmowie (0374). */
  traineeHandover?: ProposalTraineeHandover | null;
}

export interface ProposalEntry {
  row: ProposalPersonRow;
  detail: ProposalDetail;
}

export interface MergeProposalsInput {
  inbox?: readonly ProposalInboxItem[];
  /** Strona ŻYWEGO przeglądu użytkownika; tylko zakończonego i nieprzerwanego. */
  run?: { runId: string; rows: readonly CandidateSearchRow[] } | null;
  similar?: readonly HistoricalCandidate[];
  /**
   * `degraded` = ranking bez nogi semantycznej. Liczb rekomendacji i tak nie
   * pokazujemy (patrz niżej); flaga zostaje dla notki przy liście.
   */
  recommendations?: {
    items: readonly ProposalCandidateItem[];
    degraded: boolean;
  } | null;
  pipelineCandidateIds?: Iterable<number>;
  budgetHourly?: number | null;
}

const KNOWN_SOURCES = new Set<string>(Object.keys(PROPOSAL_SOURCE_LABEL));
const SOURCE_ORDER = Object.keys(PROPOSAL_SOURCE_LABEL) as ProposalSource[];

const AVAILABILITY_LABEL = new Map<string, string>(
  SEARCH_AVAILABILITY_OPTIONS.map((o) => [o.value, o.label]),
);

/** 0–100 albo `null`. Wartość spoza skali to błąd producenta, nie wynik. */
export function normalizeFitScore(raw: unknown): number | null {
  if (raw == null || raw === "" || typeof raw === "boolean") return null;
  const value = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isFinite(value) || value < 0 || value > 100) return null;
  return Math.round(value * 10) / 10;
}

export function proposalFullName(
  name: string | null | undefined,
  lastname: string | null | undefined,
  candidateId: number,
): string {
  return [name, lastname].filter(Boolean).join(" ").trim() || `Kandydat #${candidateId}`;
}

export function formatHourlyRate(value: number | null): string | null {
  if (value == null || !Number.isFinite(value) || value <= 0) return null;
  return `${Math.round(value)} zł/h`;
}

/** „Dostępny od razu" = aktywnie szuka bez daty albo data już minęła. */
export function isAvailableNow(
  status: string | null,
  date: string | null,
  now: Date = new Date(),
): boolean {
  if (date) {
    const parsed = new Date(date);
    if (!Number.isNaN(parsed.getTime())) return parsed.getTime() <= now.getTime();
  }
  return status === "actively_looking";
}

export function availabilityLabel(
  status: string | null,
  date: string | null,
  now: Date = new Date(),
): string | null {
  if (date) {
    const parsed = new Date(date);
    if (!Number.isNaN(parsed.getTime())) {
      if (parsed.getTime() <= now.getTime()) return "od razu";
      return `od ${parsed.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit" })}`;
    }
  }
  if (!status || status === "unknown") return null;
  return AVAILABILITY_LABEL.get(status) ?? null;
}

interface Draft {
  candidateId: number;
  name: string | null;
  lastname: string | null;
  sources: Set<ProposalSource>;
  origins: Set<ProposalOrigin>;
  scores: number[];
  /** Powody w kolejności bogactwa: przegląd → podobny projekt → rekomendacja → inbox. */
  reasons: Partial<Record<ProposalOrigin, string>>;
  isNew: boolean;
  previouslyDismissed: boolean;
  runId: string | null;
  detail: ProposalDetail;
}

function emptyDetail(candidateId: number): ProposalDetail {
  return {
    candidateId,
    title: null,
    city: null,
    rateHourly: null,
    rateRedacted: false,
    availabilityStatus: null,
    availabilityDate: null,
    requirements: [],
    eligibility: null,
    rateFit: null,
    officeFit: null,
    workTimeFit: null,
    similarProjects: [],
    sameClient: false,
    rejectedBySameClient: false,
    origins: [],
    firstSeenAt: null,
    aiSummary: null,
    missingMustGate: [],
    reassignFrom: null,
    traineeHandover: null,
  };
}

/** „Od praktykanta: Ola Kamińska · 24.09". Notatka idzie osobną linią. */
export function traineeHandoverReason(handover: ProposalTraineeHandover): string {
  const who = handover.by_name?.trim() || "praktykant";
  const day = handover.at ? handover.at.slice(0, 10).split("-") : null;
  const when = day && day.length === 3 ? ` · ${day[2]}.${day[1]}` : "";
  return `Od praktykanta: ${who}${when}`;
}

/** „Wysłany do PKO BP · Senior Java Developer · 26.08.2026". */
export function reassignReason(from: ProposalReassignFrom): string {
  const where = [from.client_name, from.title].filter(Boolean).join(" · ");
  const when = from.sent_at
    ? ` · ${from.sent_at.split("-").reverse().join(".")}`
    : "";
  return `Wysłany do klienta: ${where}${when}`;
}

function reqStatus(raw: string | undefined): RequirementStatus {
  return raw === "met" ? "met" : raw === "not_met" ? "not_met" : "unknown";
}

function reasonFromRequirements(reqs: ProposalRequirement[]): string | null {
  const met = reqs.filter((r) => r.status === "met");
  if (met.length === 0) return null;
  const must = met.filter((r) => r.level === "must").map((r) => r.label);
  const nice = met.filter((r) => r.level === "nice").map((r) => r.label);
  const parts: string[] = [];
  if (must.length) parts.push(`Spełnia: ${must.slice(0, 4).join(", ")}`);
  if (nice.length) parts.push(`${must.length ? "dodatkowo" : "Dodatkowo"}: ${nice.slice(0, 3).join(", ")}`);
  return parts.join(" · ");
}

function inboxRequirements(item: ProposalInboxItem): ProposalRequirement[] {
  const evidence = item.evidence;
  if (!evidence) return [];
  const out: ProposalRequirement[] = [];
  for (const r of evidence.requirements ?? []) {
    const label = r.name ?? r.any_of?.join(" lub ") ?? r.key;
    if (!label || (r.level !== "must" && r.level !== "nice")) continue;
    out.push({ label, level: r.level, status: reqStatus(r.status), verified: false });
  }
  if (out.length > 0) return out;
  // Starszy kształt dowodu: same listy nazw, bez statusów per wymaganie.
  const push = (names: string[] | undefined, level: "must" | "nice", status: RequirementStatus) =>
    (names ?? []).forEach((label) => out.push({ label, level, status, verified: false }));
  push(evidence.matched_must, "must", "met");
  push(evidence.missing_must, "must", "not_met");
  push(evidence.matched_nice, "nice", "met");
  push(evidence.missing_nice, "nice", "not_met");
  return out;
}

export function mergeProposals(input: MergeProposalsInput): ProposalEntry[] {
  const inPipeline = new Set<number>(input.pipelineCandidateIds ?? []);
  const drafts = new Map<number, Draft>();
  const draft = (id: number, name?: string | null, lastname?: string | null): Draft => {
    let d = drafts.get(id);
    if (!d) {
      d = {
        candidateId: id,
        name: null,
        lastname: null,
        sources: new Set(),
        origins: new Set(),
        scores: [],
        reasons: {},
        isNew: false,
        previouslyDismissed: false,
        runId: null,
        detail: emptyDetail(id),
      };
      drafts.set(id, d);
    }
    d.name ??= name ?? null;
    d.lastname ??= lastname ?? null;
    return d;
  };
  const addScore = (d: Draft, raw: unknown) => {
    const score = normalizeFitScore(raw);
    if (score !== null) d.scores.push(score);
  };

  for (const item of input.inbox ?? []) {
    const c = item.candidate;
    if (inPipeline.has(c.id)) continue;
    const d = draft(c.id, c.name, c.lastname);
    d.origins.add("inbox");
    for (const s of item.sources) if (KNOWN_SOURCES.has(s)) d.sources.add(s as ProposalSource);
    addScore(d, item.score);
    d.isNew ||= item.is_new;
    d.previouslyDismissed ||= item.evidence?.previously_dismissed === true;
    d.detail.title ??= c.title;
    d.detail.city ??= c.city;
    d.detail.rateHourly ??= c.expected_rate_hourly;
    d.detail.rateRedacted ||= c.expected_rate_redacted;
    d.detail.availabilityStatus ??= c.availability_status;
    d.detail.availabilityDate ??= c.availability_date;
    d.detail.eligibility ??= item.eligibility;
    d.detail.firstSeenAt ??= item.first_seen_at;
    // Przegląd, który tę osobę zaproponował — telemetria dodania (żywy
    // przegląd użytkownika, jeśli jest, nadpisze go niżej).
    d.runId ??= item.run_id ?? null;
    const reqs = inboxRequirements(item);
    if (d.detail.requirements.length === 0) d.detail.requirements = reqs;
    const reason = reasonFromRequirements(reqs);
    if (reason) d.reasons.inbox = reason;
    if (item.trainee_handover) {
      d.detail.traineeHandover ??= item.trainee_handover;
      d.reasons.inbox = traineeHandoverReason(item.trainee_handover);
    }
    if (item.reassign_from) {
      d.detail.reassignFrom ??= item.reassign_from;
      d.reasons.inbox = reassignReason(item.reassign_from);
    }
  }

  if (input.run) {
    for (const row of input.run.rows) {
      const c = row.candidate;
      if (inPipeline.has(c.id)) continue;
      const d = draft(c.id, c.name, c.lastname);
      d.origins.add("run");
      d.sources.add("full_base");
      d.runId = input.run.runId;
      addScore(d, row.fit_score);
      d.detail.city ??= c.location ?? row.match?.candidate.location ?? null;
      d.detail.title ??= row.match?.candidate.current_title ?? null;
      d.detail.availabilityStatus ??= c.availability_status;
      const rate = row.match?.candidate.expected_rate_hourly;
      const pln = (row.match?.candidate.expected_rate_currency ?? "PLN").toUpperCase() === "PLN";
      if (rate != null && pln) d.detail.rateHourly ??= rate;
      // Żywy przegląd jest świeższy niż zapis w skrzynce — nadpisuje plakietkę.
      if (row.eligibility) d.detail.eligibility = row.eligibility;
      d.detail.rateFit = row.match?.rate_fit ?? d.detail.rateFit;
      d.detail.officeFit = row.match?.office_fit ?? d.detail.officeFit;
      d.detail.workTimeFit = row.match?.work_time_fit ?? d.detail.workTimeFit;
      const summary = row.match?.candidate.ai_summary?.trim();
      if (summary) d.detail.aiSummary = summary;
      d.detail.missingMustGate = (row.match?.missing_must ?? []).filter(Boolean);
      const reqs: ProposalRequirement[] = row.requirements
        .filter((r) => r.level === "must" || r.level === "nice")
        .map((r) => ({
          label: r.any_of.join(" lub "),
          level: r.level as "must" | "nice",
          status: r.status,
          verified: r.evidence_basis === "reviewed" || Boolean(r.verified_at),
        }));
      if (reqs.length > 0) d.detail.requirements = reqs;
      const reason = reasonFromRequirements(reqs);
      if (reason) d.reasons.run = reason;
    }
  }

  for (const h of input.similar ?? []) {
    if (inPipeline.has(h.candidate_id)) continue;
    const d = draft(h.candidate_id, h.name, h.lastname);
    d.origins.add("similar");
    d.sources.add("similar_projects");
    // `historical_score` celowo pominięty — to nie jest dopasowanie 0–100.
    d.detail.eligibility ??= h.eligibility ?? null;
    d.detail.sameClient ||= h.same_client;
    d.detail.rejectedBySameClient ||= h.rejected_by_same_client;
    d.detail.similarProjects = h.sources
      .slice(0, 5)
      .map((s) => ({ jobId: s.job_id, title: s.job_title, stage: s.stage }));
    const best = h.sources[0];
    if (best) {
      const more = h.sources.length > 1 ? ` (+${h.sources.length - 1})` : "";
      d.reasons.similar = `Był(a) w podobnym projekcie: ${best.job_title}${more}`;
    }
  }

  for (const item of input.recommendations?.items ?? []) {
    const c = item.candidate;
    if (inPipeline.has(c.id)) continue;
    const d = draft(c.id, c.name, c.lastname);
    d.origins.add("recommendation");
    d.sources.add("recommendation");
    // `total_score` migawki rekomendacji to INNA skala niż kanoniczne
    // dopasowanie z przeglądu bazy — do kolumny „Dop." nie trafia nigdy
    // (dwie liczby pod jedną nazwą to gorsze niż brak liczby).
    d.detail.city ??= c.location;
    d.detail.eligibility ??= item.eligibility ?? null;
  }

  const budget = input.budgetHourly ?? null;
  const entries: ProposalEntry[] = [];
  for (const d of drafts.values()) {
    // Źródło spoza słownika (nowy producent) — osoba zostaje, kolumna pusta
    // byłaby myląca, więc traktujemy ją jak propozycję z przeglądu bazy.
    if (d.sources.size === 0) d.sources.add("full_base");
    const detail = { ...d.detail, origins: Array.from(d.origins) };
    const warnings: string[] = [];
    if (detail.eligibility) {
      warnings.push(
        detail.eligibility.assignment_allowed === false
          ? "hm_veto"
          : detail.eligibility.reason_code,
      );
    }
    // Zgoda na ofertę poniżej minimum nie zmienia faktu: stawka jest ponad budżetem.
    const overBudget =
      detail.rateFit === "over_budget" ||
      detail.rateFit === "below_min_consented" ||
      (detail.rateFit == null && budget != null && detail.rateHourly != null && detail.rateHourly > budget);
    if (overBudget) warnings.push("over_budget");
    if (detail.rejectedBySameClient) warnings.push("rejected_by_same_client");
    if (detail.workTimeFit === "part_time_only" || detail.workTimeFit === "full_time_only") {
      warnings.push(detail.workTimeFit);
    }
    const handoverNote = detail.traineeHandover?.note?.trim() || null;
    entries.push({
      row: {
        kind: "proposal",
        key: `proposal:${d.candidateId}`,
        candidateId: d.candidateId,
        fullName: proposalFullName(d.name, d.lastname, d.candidateId),
        rateLabel: formatHourlyRate(detail.rateHourly),
        availabilityLabel: availabilityLabel(detail.availabilityStatus, detail.availabilityDate),
        fitScore: d.scores.length ? Math.max(...d.scores) : null,
        warnings,
        sources: SOURCE_ORDER.filter((s) => d.sources.has(s)),
        // Przepięcie tłumaczy się samo — „był już u klienta" bije resztę powodów;
        // przekazanie od praktykanta (po rozmowie) — zaraz za nim.
        reason:
          detail.reassignFrom || detail.traineeHandover
            ? (d.reasons.inbox ?? null)
            : (d.reasons.run ?? d.reasons.similar ?? d.reasons.recommendation ?? d.reasons.inbox ?? null),
        isNew: d.isNew,
        previouslyDismissed: d.previouslyDismissed,
        runId: d.runId,
        ...(handoverNote ? { handoverNote } : {}),
      },
      detail,
    });
  }
  return entries.sort(compareProposals);
}

/** Etykiety plakietki sprzecznego wymiaru pracy (tylko przypadki ostrzegawcze,
 *  decyzja 24.09.2026: plakietka, nie ukrycie). Klucz = kod ostrzeżenia wiersza. */
export const WORK_TIME_FIT_WARNING_PL: Partial<Record<WorkTimeFit, string>> = {
  part_time_only: "Szuka części etatu",
  full_time_only: "Tylko pełny etat",
};

export function compareProposals(a: ProposalEntry, b: ProposalEntry): number {
  // Przepięcia (osoby już wysłane do klienta) zawsze na górze kolejki.
  const ra = a.row.sources.includes("reassign");
  const rb = b.row.sources.includes("reassign");
  if (ra !== rb) return ra ? -1 : 1;
  // Zaraz za nimi osoby przekazane przez praktykanta — po rozmowie, świeże dane.
  const ta = a.row.sources.includes("trainee");
  const tb = b.row.sources.includes("trainee");
  if (ta !== tb) return ta ? -1 : 1;
  const sa = a.row.fitScore;
  const sb = b.row.fitScore;
  if (sa !== sb) {
    if (sa === null) return 1;
    if (sb === null) return -1;
    return sb - sa;
  }
  if (a.row.isNew !== b.row.isNew) return a.row.isNew ? -1 : 1;
  return (
    a.row.fullName.localeCompare(b.row.fullName, "pl") ||
    a.row.candidateId - b.row.candidateId
  );
}

// ── Filtry widoku (działają na scalonej liście, nie uruchamiają skanu) ───────

export type ProposalSourceFilter = "all" | ProposalSource;
export type ProposalRateFilter = "all" | "in" | "over" | "unknown";

export interface ProposalViewFilters {
  source: ProposalSourceFilter;
  onlyNew: boolean;
  /** Chip „W budżecie": odsiewa stawki PONAD budżet, nieznane zostają. */
  inBudget: boolean;
  availableNow: boolean;
  minScore: number;
  rate: ProposalRateFilter;
  location: string;
  skill: string | null;
}

export const DEFAULT_PROPOSAL_FILTERS: ProposalViewFilters = {
  source: "all",
  onlyNew: false,
  inBudget: false,
  availableNow: false,
  minScore: 0,
  rate: "all",
  location: "",
  skill: null,
};

export function proposalRateFit(
  detail: ProposalDetail,
  budgetHourly: number | null,
): "in" | "over" | "unknown" {
  if (detail.rateFit === "ok") return "in";
  if (detail.rateFit === "over_budget" || detail.rateFit === "below_min_consented") return "over";
  if (detail.rateHourly == null || budgetHourly == null) return "unknown";
  return detail.rateHourly > budgetHourly ? "over" : "in";
}

const fold = (value: string) =>
  value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ł/g, "l")
    .replace(/Ł/g, "L")
    .toLowerCase()
    .trim();

export function filterProposals(
  entries: readonly ProposalEntry[],
  filters: ProposalViewFilters,
  ctx: { budgetHourly: number | null; now?: Date },
): ProposalEntry[] {
  const location = fold(filters.location);
  const skill = filters.skill ? fold(filters.skill) : null;
  return entries.filter(({ row, detail }) => {
    if (filters.source !== "all" && !row.sources.includes(filters.source)) return false;
    if (filters.onlyNew && !row.isNew) return false;
    // Próg NIE usuwa ocen niepełnych: „nie policzono" to nie „zero".
    if (filters.minScore > 0 && row.fitScore !== null && row.fitScore < filters.minScore) return false;
    const fit = proposalRateFit(detail, ctx.budgetHourly);
    // Chip „W budżecie" przepuszcza stawki NIEZNANE: brak stawki w profilu to
    // nie „ponad budżet", a takich osób jest w bazie większość.
    if (filters.inBudget && fit === "over") return false;
    if (filters.rate !== "all" && fit !== filters.rate) return false;
    if (filters.availableNow && !isAvailableNow(detail.availabilityStatus, detail.availabilityDate, ctx.now)) return false;
    if (location && !fold(detail.city ?? "").includes(location)) return false;
    if (skill && !detail.requirements.some((r) => r.status === "met" && fold(r.label).includes(skill))) return false;
    return true;
  });
}

export function countBySource(
  entries: readonly ProposalEntry[],
): Record<ProposalSourceFilter, number> {
  const counts = { all: entries.length } as Record<ProposalSourceFilter, number>;
  for (const s of SOURCE_ORDER) counts[s] = 0;
  for (const { row } of entries) for (const s of row.sources) counts[s] += 1;
  return counts;
}
