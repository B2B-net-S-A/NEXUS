/**
 * „Screening dla” — jedna rozmowa pod kilka rekrutacji (14.10.2026, decyzje
 * Artura D3–D4, makiety B1–B3). Czysta logika bez zapytań.
 *
 * Formularz wspólny ma JEDEN stan (`JointValues`). Zapis idzie dalej osobno
 * do każdej pary (`PUT /api/screening-form`, `buildSavePayload` z jej stanu),
 * więc wersje, odcisk stanu, blokada 12 h i 409 działają jak w pojedynczym
 * formularzu. Tu: wartości startowe, rzut wspólnego stanu na parę i braki
 * przed „Zapisz i przekaż dalej”.
 *
 * Reguła pól wspólnych (warunki, red flags, „Czy pracował u Klienta” per
 * klient): pole ruszone w tej rozmowie trafia do każdej pary; nieruszone
 * uzupełnia tylko pary, w których jest puste — nic, co para już ma, nie
 * znika bez ruchu rekrutera.
 */

import type { RateUnit, ScreeningQuestion } from "@/lib/api";
import type { FormRate, ScreeningFormState } from "@/lib/api/screeningForm";
import {
  assessmentMissingForForward,
  editableCardKeys,
  formDefaultsFromState,
  formQuestions,
  missingAnswersForForward,
  rateFromValues,
  ratePrefill,
  sameRate,
  type ScreeningFullFormValues,
} from "@/lib/screening-form";

/** Warunki o samej osobie — wpisywane raz dla wszystkich rekrutacji. */
export const SHARED_TERMS_KEYS = ["availability", "work_mode", "location", "nationality", "english"] as const;
/** Pole o osobie w ocenie — wspólne (makieta B3: „Red flags są wspólne”). */
export const SHARED_ASSESSMENT_KEYS = ["red_flags"] as const;
/** Pole o kliencie — jedno na klienta, nie na rekrutację. */
export const CLIENT_KEY = "worked_at_client";

const SHARED_KEYS: ReadonlySet<string> = new Set<string>([...SHARED_TERMS_KEYS, ...SHARED_ASSESSMENT_KEYS]);

export interface JointPair {
  jobId: number;
  title: string;
  clientId: number | null;
  clientName: string | null;
  budgetHourly: number | null;
  /** Etap „Zweryfikowany” tej rekrutacji; `null` = przekazanie tylko z jej Tablicy. */
  verifiedStageDefId: number | null;
  /** Rekrutacja, z której otwarto panel. */
  anchor: boolean;
  state: ScreeningFormState;
}

export interface JointGroupMember {
  jobId: number;
  questionId: string;
}

/** Jedno pytanie do zadania w rozmowie — w jednej albo kilku rekrutacjach. */
export interface JointGroup {
  key: string;
  members: JointGroupMember[];
}

export interface JointJobValues {
  overall_fit: ScreeningFullFormValues["overall_fit"];
  /** Pola karty tej rekrutacji (ocena i warunki spoza wspólnych). */
  card: Record<string, string>;
  rate_amount: string;
  rate_unit: RateUnit;
  rate_currency: string;
}

export interface JointValues {
  shared: {
    card: Record<string, string>;
    same_rate: boolean;
    rate_amount: string;
    rate_unit: RateUnit;
    rate_currency: string;
  };
  /** `c<clientId>` → „Czy pracował u Klienta”. */
  clients: Record<string, string>;
  /** Klucz grupy → odpowiedź (jedna na grupę). */
  answers: Record<string, string>;
  /** `j<jobId>_<questionId>` → odpowiedź narusza deal-breaker TEJ rekrutacji. */
  hits: Record<string, boolean>;
  /** `j<jobId>` → wartości tej rekrutacji. */
  jobs: Record<string, JointJobValues>;
}

/** Ścieżki pól — pola RHF z kropkami muszą mieć klucze bez kropek. */
export const jobKey = (jobId: number) => `j${jobId}`;
export const clientKey = (clientId: number | null) => `c${clientId ?? 0}`;
export const hitKey = (jobId: number, questionId: string) => `j${jobId}_${questionId}`;

/** Grupy z serwera (identyfikatory) + pytania bez grupy — każde pytanie dokładnie raz. */
export function completeGroups(
  pairs: readonly JointPair[],
  serverGroups: ReadonlyArray<ReadonlyArray<{ job_id: number; question_id: string }>>,
): JointGroup[] {
  const known = new Set(pairs.map((p) => p.jobId));
  const seen = new Set<string>();
  const groups: JointGroup[] = [];
  for (const group of serverGroups) {
    const members = group
      .filter((m) => known.has(m.job_id) && !seen.has(hitKey(m.job_id, m.question_id)))
      .map((m) => ({ jobId: m.job_id, questionId: m.question_id }));
    if (members.length === 0) continue;
    members.forEach((m) => seen.add(hitKey(m.jobId, m.questionId)));
    groups.push({ key: `g${groups.length}`, members });
  }
  for (const pair of pairs) {
    for (const q of formQuestions(pair.state)) {
      if (seen.has(hitKey(pair.jobId, q.id))) continue;
      seen.add(hitKey(pair.jobId, q.id));
      groups.push({ key: `g${groups.length}`, members: [{ jobId: pair.jobId, questionId: q.id }] });
    }
  }
  return groups;
}

export function questionOf(pair: JointPair, questionId: string): ScreeningQuestion | undefined {
  return formQuestions(pair.state).find((q) => q.id === questionId);
}

/** Stawka, z którą para startuje: zapisana albo podpowiedziana (jak pojedynczy formularz). */
export function initialRate(state: ScreeningFormState): FormRate | null {
  const defaults = formDefaultsFromState(state);
  return rateFromValues(defaults) ?? ratePrefill(state)?.rate ?? null;
}

function rateFields(rate: FormRate | null): Pick<JointJobValues, "rate_amount" | "rate_unit" | "rate_currency"> {
  return {
    rate_amount: rate ? String(rate.amount) : "",
    rate_unit: rate?.unit ?? "hourly",
    rate_currency: rate?.currency ?? "PLN",
  };
}

function firstNonEmpty(values: ReadonlyArray<string | undefined>): string {
  return values.find((v) => (v ?? "").trim() !== "") ?? "";
}

/** Wartości startowe — kotwica pierwsza; puste pola wspólne biorą wartość z innej pary. */
export function jointDefaults(pairs: readonly JointPair[], groups: readonly JointGroup[]): JointValues {
  const ordered = [...pairs].sort((a, b) => Number(b.anchor) - Number(a.anchor));
  const defaults = new Map(ordered.map((p) => [p.jobId, formDefaultsFromState(p.state)]));
  const sharedCard: Record<string, string> = {};
  for (const key of SHARED_KEYS) {
    if (!ordered.some((p) => editableCardKeys(p.state).includes(key))) continue;
    sharedCard[key] = firstNonEmpty(ordered.map((p) => defaults.get(p.jobId)?.card?.[key]));
  }
  const clients: Record<string, string> = {};
  for (const pair of ordered) {
    if (!editableCardKeys(pair.state).includes(CLIENT_KEY)) continue;
    const key = clientKey(pair.clientId);
    if (!(clients[key] ?? "").trim()) clients[key] = defaults.get(pair.jobId)?.card?.[CLIENT_KEY] ?? "";
  }
  const answers: Record<string, string> = {};
  const hits: Record<string, boolean> = {};
  for (const group of groups) {
    answers[group.key] = firstNonEmpty(
      group.members.map((m) => defaults.get(m.jobId)?.answers?.[m.questionId]?.response),
    );
    for (const m of group.members) {
      hits[hitKey(m.jobId, m.questionId)] = Boolean(defaults.get(m.jobId)?.answers?.[m.questionId]?.deal_breaker_hit);
    }
  }
  const jobs: Record<string, JointJobValues> = {};
  const rates = ordered.map((p) => initialRate(p.state));
  for (const [i, pair] of ordered.entries()) {
    const d = defaults.get(pair.jobId)!;
    const own = Object.fromEntries(
      editableCardKeys(pair.state)
        .filter((key) => !SHARED_KEYS.has(key) && key !== CLIENT_KEY)
        .map((key) => [key, d.card?.[key] ?? ""]),
    );
    jobs[jobKey(pair.jobId)] = { overall_fit: d.overall_fit, card: own, ...rateFields(rates[i]) };
  }
  const known = rates.filter((r): r is FormRate => r != null);
  const sameRateEverywhere = known.every((r) => sameRate(r, known[0]));
  return {
    shared: { card: sharedCard, same_rate: sameRateEverywhere, ...rateFields(known[0] ?? null) },
    clients,
    answers,
    hits,
    jobs,
  };
}

/** Pola ruszone w tej rozmowie (`formState.dirtyFields` RHF). */
export interface JointDirty {
  shared?: { card?: Record<string, boolean | undefined>; rate_amount?: boolean; rate_unit?: boolean; rate_currency?: boolean };
  clients?: Record<string, boolean | undefined>;
}

function overlay(base: string, value: string, touched: boolean): string {
  if (touched) return value;
  return base.trim() ? base : value;
}

/** Wartości pojedynczego formularza pary z formularza wspólnego. */
export function projectPair(
  values: JointValues,
  pair: JointPair,
  groups: readonly JointGroup[],
  dirty: JointDirty = {},
): ScreeningFullFormValues {
  const d = formDefaultsFromState(pair.state);
  const editable = new Set(editableCardKeys(pair.state));
  const card = { ...d.card };
  for (const key of SHARED_KEYS) {
    if (!editable.has(key) || values.shared.card[key] === undefined) continue;
    card[key] = overlay(d.card[key] ?? "", values.shared.card[key] ?? "", Boolean(dirty.shared?.card?.[key]));
  }
  if (editable.has(CLIENT_KEY)) {
    const key = clientKey(pair.clientId);
    if (values.clients[key] !== undefined) {
      card[CLIENT_KEY] = overlay(d.card[CLIENT_KEY] ?? "", values.clients[key] ?? "", Boolean(dirty.clients?.[key]));
    }
  }
  const own = values.jobs[jobKey(pair.jobId)];
  for (const [key, value] of Object.entries(own?.card ?? {})) {
    if (editable.has(key)) card[key] = value;
  }

  const answers = { ...d.answers };
  for (const group of groups) {
    for (const member of group.members) {
      if (member.jobId !== pair.jobId || !answers[member.questionId]) continue;
      const before = answers[member.questionId];
      const response = values.answers[group.key] ?? before.response;
      answers[member.questionId] = {
        ...before,
        response,
        deal_breaker_hit: Boolean(values.hits[hitKey(pair.jobId, member.questionId)]),
        // Odpowiedź z tej rozmowy jest odpowiedzią człowieka.
        origin: response.trim() === before.response.trim() ? before.origin : "manual",
        keywords: response.trim() === before.response.trim() ? before.keywords : null,
      };
    }
  }

  const touchedRate = Boolean(dirty.shared?.rate_amount || dirty.shared?.rate_unit || dirty.shared?.rate_currency);
  const rate = values.shared.same_rate
    ? touchedRate
      ? values.shared
      : (own ?? values.shared)
    : (own ?? values.shared);

  return {
    ...d,
    answers,
    overall_fit: own?.overall_fit ?? d.overall_fit,
    card,
    rate_amount: rate.rate_amount,
    rate_unit: rate.rate_unit,
    rate_currency: rate.rate_currency,
  };
}

/** Czego brakuje parze przed „Zapisz i przekaż dalej” — pusta lista = można. */
export function forwardBlockers(pair: JointPair, projected: ScreeningFullFormValues): string[] {
  const questions = formQuestions(pair.state);
  const missing = missingAnswersForForward(questions, projected);
  const out: string[] = [];
  if (missing.length > 0) {
    out.push(missing.length === 1 ? "1 pytanie bez odpowiedzi" : `${missing.length} pytania bez odpowiedzi`);
  }
  if (assessmentMissingForForward(pair.state, questions, projected)) out.push("„Dlaczego ten kandydat”");
  return out;
}

/** Odpowiedź tej pary narusza deal-breaker — nie przekazujemy jej sami. */
export function dealBreakerHit(pair: JointPair, projected: ScreeningFullFormValues): boolean {
  return formQuestions(pair.state).some((q) => Boolean(projected.answers?.[q.id]?.deal_breaker_hit));
}

/** Porównanie stawki z budżetem rekrutacji (PLN/h; dzień ÷ 8, miesiąc ÷ 168) — jak pojedynczy formularz. */
export function budgetVerdict(
  rate: FormRate | null,
  budgetHourly: number | null,
): { tone: "ok" | "over" | "unknown"; label: string } {
  if (!rate || budgetHourly == null || budgetHourly <= 0 || rate.currency.toUpperCase() !== "PLN") {
    return { tone: "unknown", label: budgetHourly ? `budżet ${budgetHourly} zł/h` : "bez budżetu" };
  }
  const hourly = rate.unit === "daily" ? rate.amount / 8 : rate.unit === "monthly" ? rate.amount / 168 : rate.amount;
  if (hourly <= budgetHourly + 0.005) return { tone: "ok", label: `mieści się w ${budgetHourly} zł/h` };
  const over = Math.round(((hourly - budgetHourly) / budgetHourly) * 100);
  return { tone: "over", label: `ponad budżet ${budgetHourly} zł/h (+${over}%)` };
}
