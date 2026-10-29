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
 * klient, odpowiedź na wspólne pytanie): pole ruszone w tej rozmowie trafia
 * do każdej pary; nieruszone uzupełnia tylko pary, w których jest puste — nic,
 * co para już ma, nie znika bez ruchu rekrutera.
 *
 * Rzut liczy się od NAJŚWIEŻSZEGO stanu pary (ten sam, którego odcisk idzie
 * w zapisie): pole nieruszone bierze wartość serwera, ruszone — wartość
 * z rozmowy. Inaczej zapis po odświeżeniu w tle odesłałby wartości sprzed
 * otwarcia formularza ze świeżym odciskiem i po cichu cofnął cudzą zmianę
 * (tak samo pojedynczy formularz: `keepDirtyValues` + różnice od `baseState`).
 */

import type { RateUnit, ScreeningQuestion, ScreeningSkipReason } from "@/lib/api";
import type { NoteProposal } from "@/lib/api/recommendationCards";
import type { FormRate, ScreeningFormState } from "@/lib/api/screeningForm";
import {
  assessmentMissingForForward,
  editableCardKeys,
  formDefaultsFromState,
  formFieldLabel,
  formQuestions,
  minimumMissingForForward,
  missingAnswersForForward,
  rateFromValues,
  ratePrefill,
  sameRate,
  type ScreeningFullFormValues,
} from "@/lib/screening-form";

/** Warunki o samej osobie — wpisywane raz dla wszystkich rekrutacji. */
export const SHARED_TERMS_KEYS = ["availability", "location", "nationality", "english"] as const;
/**
 * Warunki per rekrutacja, w sekcji „Warunki” obok wspólnych: tryb pracy bywa
 * inny w każdym projekcie (1 dzień z biura w jednym, 2 w drugim — zgłoszenie
 * rekrutera 29.10.2026). Do tej daty był wspólny.
 */
export const PER_JOB_TERMS_KEYS = ["work_mode"] as const;
/** Pole o osobie w ocenie — wspólne (makieta B3: „Red flags są wspólne”). */
export const SHARED_ASSESSMENT_KEYS = ["red_flags"] as const;
/** Pole o kliencie — jedno na klienta, nie na rekrutację. */
export const CLIENT_KEY = "worked_at_client";

/**
 * Ile innych rekrutacji w jednej rozmowie: `GET /api/screening-form/question-groups`
 * przyjmuje 2–4 rekrutacje (kotwica + 3).
 */
export const JOINT_MAX_OTHERS = 3;

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
  /** Bliźniak kotwicy (0614) — stawka w budżecie, tryb pracy przy stawce. */
  twin?: boolean;
  /** „zdalnie”, „2 dni z biura”… — ten sam tryb = ta sama stawka. */
  workMode?: string;
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
  /** „Pomiń brakujące” — tylko pytania TEJ rekrutacji bez odpowiedzi. */
  skip_missing: boolean;
  skip_reason: ScreeningSkipReason | null;
  /** Dlaczego pomijasz — notatka wewnętrzna arkusza tej rekrutacji. */
  internal_note: string;
}

/**
 * Skąd jest wartość wpisana w tej rozmowie (notatka, zdanie z haseł,
 * wcześniejsza rozmowa) — klucz = ścieżka pola formularza wspólnego.
 * Pochodzenie trzyma się wartości: poprawka ręczna je zdejmuje (zdanie
 * z haseł — dopiero wyczyszczenie), jak w pojedynczym formularzu.
 */
export interface JointOrigin {
  value: string;
  origin: "note_ai" | "note_rule" | "phrased" | "note_import" | "reassign_suggested";
  keywords?: string | null;
}
export type JointOrigins = Readonly<Record<string, JointOrigin>>;

export function originHolds(origin: JointOrigin | undefined, value: string): origin is JointOrigin {
  if (!origin) return false;
  if (origin.origin === "phrased") return value.trim() !== "";
  return value.trim() === origin.value.trim();
}

/** Pochodzenie pola karty do zapisu (`card_origins`) albo `null`. */
function cardOrigin(origin: JointOrigin | undefined, value: string): ScreeningFullFormValues["card_origins"][string] {
  if (!originHolds(origin, value)) return null;
  if (origin.origin !== "note_ai" && origin.origin !== "note_rule" && origin.origin !== "phrased") return null;
  return origin.keywords ? { origin: origin.origin, keywords: origin.keywords } : { origin: origin.origin };
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
    jobs[jobKey(pair.jobId)] = {
      overall_fit: d.overall_fit,
      card: own,
      ...rateFields(rates[i]),
      skip_missing: Boolean(d.skip_missing),
      skip_reason: null,
      internal_note: d.internal_note ?? "",
    };
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

interface RateDirty {
  rate_amount?: boolean;
  rate_unit?: boolean;
  rate_currency?: boolean;
}

/** Pola ruszone w tej rozmowie (`formState.dirtyFields` RHF). */
export interface JointDirty {
  shared?: { card?: Record<string, boolean | undefined>; same_rate?: boolean } & RateDirty;
  clients?: Record<string, boolean | undefined>;
  answers?: Record<string, boolean | undefined>;
  hits?: Record<string, boolean | undefined>;
  jobs?: Record<
    string,
    | ({
        overall_fit?: boolean;
        card?: Record<string, boolean | undefined>;
        skip_missing?: boolean;
        skip_reason?: boolean;
        internal_note?: boolean;
      } & RateDirty)
    | undefined
  >;
}

const rateTouched = (dirty: RateDirty | undefined) =>
  Boolean(dirty?.rate_amount || dirty?.rate_unit || dirty?.rate_currency);

function overlay(base: string, value: string, touched: boolean): string {
  return fromJoint(base, touched) ? value : base;
}

/** Wartość pary pochodzi z formularza wspólnego (ruszona albo pusta w parze). */
function fromJoint(base: string, touched: boolean): boolean {
  return touched || !base.trim();
}

/**
 * Wartości pojedynczego formularza pary z formularza wspólnego. `pair.state`
 * ma być stanem, z którym pójdzie zapis (najświeższym z pamięci zapytań).
 */
export function projectPair(
  values: JointValues,
  pair: JointPair,
  groups: readonly JointGroup[],
  dirty: JointDirty = {},
  origins: JointOrigins = {},
): ScreeningFullFormValues {
  const d = formDefaultsFromState(pair.state);
  const editable = new Set(editableCardKeys(pair.state));
  const card = { ...d.card };
  const cardOrigins = { ...d.card_origins };
  // Wartość z formularza wspólnego niesie swoje pochodzenie (notatka, zdanie z haseł).
  const take = (key: string, path: string, value: string) => {
    card[key] = value;
    cardOrigins[key] = cardOrigin(origins[path], value);
  };
  for (const key of SHARED_KEYS) {
    if (!editable.has(key) || values.shared.card[key] === undefined) continue;
    if (fromJoint(d.card[key] ?? "", Boolean(dirty.shared?.card?.[key]))) {
      take(key, `shared.card.${key}`, values.shared.card[key] ?? "");
    }
  }
  if (editable.has(CLIENT_KEY)) {
    const key = clientKey(pair.clientId);
    if (values.clients[key] !== undefined && fromJoint(d.card[CLIENT_KEY] ?? "", Boolean(dirty.clients?.[key]))) {
      take(CLIENT_KEY, `clients.${key}`, values.clients[key] ?? "");
    }
  }
  const own = values.jobs[jobKey(pair.jobId)];
  const ownDirty = dirty.jobs?.[jobKey(pair.jobId)];
  for (const [key, value] of Object.entries(own?.card ?? {})) {
    if (editable.has(key) && ownDirty?.card?.[key]) take(key, `jobs.${jobKey(pair.jobId)}.card.${key}`, value);
  }

  const answers = { ...d.answers };
  for (const group of groups) {
    for (const member of group.members) {
      if (member.jobId !== pair.jobId || !answers[member.questionId]) continue;
      const before = answers[member.questionId];
      const response = overlay(before.response, values.answers[group.key] ?? "", Boolean(dirty.answers?.[group.key]));
      const hit = hitKey(pair.jobId, member.questionId);
      const unchanged = response.trim() === before.response.trim();
      const origin = origins[`answers.${group.key}`];
      // Pola karty z notatki („note_ai”/„note_rule”) to nie odpowiedzi.
      const held =
        !unchanged && originHolds(origin, response) && origin.origin !== "note_ai" && origin.origin !== "note_rule"
          ? { origin: origin.origin, keywords: origin.keywords }
          : null;
      answers[member.questionId] = {
        ...before,
        response,
        deal_breaker_hit: dirty.hits?.[hit] ? Boolean(values.hits[hit]) : before.deal_breaker_hit,
        // Odpowiedź z tej rozmowy jest odpowiedzią człowieka — chyba że przyszła
        // z notatki, zdania z haseł albo wcześniejszej rozmowy i nikt jej nie poprawił.
        origin: unchanged ? before.origin : (held?.origin ?? "manual"),
        keywords: unchanged ? before.keywords : (held?.keywords ?? null),
      };
    }
  }

  // Stawka: „Ta sama stawka” = kwota z pola wspólnego (ta, którą widać), gdy
  // rekruter ruszył stawkę albo przełącznik, i dla pary bez własnej stawki;
  // nieruszona — stawka startowa pary. Osobne stawki: ruszona albo startowa.
  const start = rateFields(initialRate(pair.state));
  const rate = values.shared.same_rate
    ? dirty.shared?.same_rate || rateTouched(dirty.shared) || !start.rate_amount.trim()
      ? values.shared
      : start
    : own && rateTouched(ownDirty)
      ? own
      : start;

  const skip = own && ownDirty?.skip_missing ? own.skip_missing : d.skip_missing;

  return {
    ...d,
    answers,
    overall_fit: own && ownDirty?.overall_fit ? own.overall_fit : d.overall_fit,
    skip_missing: skip,
    skip_reason: skip ? (own?.skip_reason ?? d.skip_reason) : null,
    internal_note: own && ownDirty?.internal_note ? own.internal_note : d.internal_note,
    card,
    card_origins: cardOrigins,
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
  // Minimum dla Delivery Leada (21.10.2026) — ta sama reguła co bramka serwera.
  for (const key of minimumMissingForForward(pair.state, questions, projected)) {
    out.push(`„${formFieldLabel(pair.state, key)}”`);
  }
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

/**
 * Notatka z rozmowy (odczyt dla JEDNEJ rekrutacji) → zmiany formularza
 * wspólnego. Jak w pojedynczym formularzu: tylko PUSTE miejsca — nic, co
 * rekruter już wpisał, nie znika. Odpowiedź trafia do grupy pytania tej
 * rekrutacji (wspólne pytanie wypełni się raz).
 */
export interface JointPatch {
  path: string;
  value: string;
  origin?: JointOrigin;
}

export function noteFillPatches(
  values: JointValues,
  pair: JointPair,
  groups: readonly JointGroup[],
  proposal: Pick<NoteProposal, "fields" | "answers">,
): JointPatch[] {
  const patches: JointPatch[] = [];
  const add = (path: string, value: string, origin?: Omit<JointOrigin, "value">) =>
    patches.push(origin ? { path, value, origin: { value, ...origin } } : { path, value });
  const empty = (value: string | undefined) => !(value ?? "").trim();
  const own = values.jobs[jobKey(pair.jobId)];
  const editable = new Set(editableCardKeys(pair.state));
  for (const field of proposal.fields ?? []) {
    const proposed = String(field.proposed ?? "").trim();
    if (!proposed) continue;
    if (field.key === "rate") {
      const rate = field.rate;
      if (!rate || !(rate.amount > 0) || !pair.state.can_edit_rate) continue;
      const prefix = values.shared.same_rate ? "shared" : `jobs.${jobKey(pair.jobId)}`;
      const current = values.shared.same_rate ? values.shared.rate_amount : own?.rate_amount;
      if (!empty(current)) continue;
      add(`${prefix}.rate_amount`, String(rate.amount));
      add(`${prefix}.rate_unit`, rate.unit);
      add(`${prefix}.rate_currency`, rate.currency || "PLN");
      continue;
    }
    if (!editable.has(field.key)) continue;
    const origin = { origin: field.origin };
    if (SHARED_KEYS.has(field.key)) {
      if (empty(values.shared.card[field.key])) add(`shared.card.${field.key}`, proposed, origin);
    } else if (field.key === CLIENT_KEY) {
      const key = clientKey(pair.clientId);
      if (empty(values.clients[key])) add(`clients.${key}`, proposed, origin);
    } else if (own && field.key in own.card && empty(own.card[field.key])) {
      add(`jobs.${jobKey(pair.jobId)}.card.${field.key}`, proposed, origin);
    }
  }
  for (const answer of proposal.answers ?? []) {
    const sentence = answer.sentence?.trim() || null;
    const keywords = String(answer.keywords ?? "").trim();
    const response = sentence ?? keywords;
    if (!response) continue;
    const group = groups.find((g) => g.members.some((m) => m.jobId === pair.jobId && m.questionId === answer.question_id));
    if (group && empty(values.answers[group.key])) {
      add(`answers.${group.key}`, response, { origin: sentence ? "phrased" : "note_import", keywords: keywords || null });
    }
  }
  return patches;
}

/**
 * Bliźniaki (0614, decyzja Artura 28.10.2026): stawka jedna, inna tylko przy
 * innym trybie pracy. Grupy rekrutacji o tym samym trybie, kotwica pierwsza.
 */
export function workModeGroups(pairs: readonly JointPair[]): JointPair[][] {
  const groups = new Map<string, JointPair[]>();
  const ordered = [...pairs].sort((a, b) => Number(b.anchor) - Number(a.anchor));
  for (const pair of ordered) {
    const key = pair.workMode ?? "";
    groups.set(key, [...(groups.get(key) ?? []), pair]);
  }
  return [...groups.values()];
}

/** Rozmowa z bliźniakiem: stawka ponad budżet którejś rekrutacji nie przejdzie. */
export function twinRateBlockers(
  pairs: readonly JointPair[],
  rateOf: (pair: JointPair) => FormRate | null,
): Array<{ title: string; items: string[] }> {
  if (!pairs.some((p) => p.twin)) return [];
  return pairs.flatMap((pair) => {
    const verdict = budgetVerdict(rateOf(pair), pair.budgetHourly);
    return verdict.tone === "over"
      ? [{ title: pair.title, items: [`stawka ${verdict.label} — najwyżej ${pair.budgetHourly} zł/h`] }]
      : [];
  });
}
