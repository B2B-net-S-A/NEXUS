/**
 * Pamięć rozmowy screeningowej (16.10.2026, decyzje Artura D1 A, D2 A, D3 B).
 * Czysta logika bez zapytań i bez pamięci przeglądarki.
 *
 * Do tej daty formularz wspólny („Screening dla”) był przypięty do zestawu
 * zaznaczonych rekrutacji: każda zmiana zestawu — odznaczenie, dołożenie,
 * „+ Dodaj i dołącz”, przejście między formularzem pojedynczym a wspólnym —
 * wczytywała go od nowa i kasowała wszystkie niezapisane wpisy, także
 * w rekrutacjach, które zostały (zgłoszenie rekrutera z 16.10.2026).
 *
 * Teraz każdy wpis rekrutera ląduje w pamięci pod adresem, który nie zależy
 * od zaznaczenia: odpowiedź = rekrutacja + pytanie, pola o osobie raz,
 * „Czy pracował u Klienta” per klient, ocena i stawka per rekrutacja.
 * Formularz (pojedynczy albo wspólny, dowolny zestaw) przy starcie bierze
 * z pamięci to, co dotyczy jego rekrutacji, jako zmiany rekrutera.
 *
 * W pamięci jest tylko to, co rekruter ruszył i co różni się od stanu
 * serwera danej pary — wartości startowe (stawka z notatki, odpowiedź innej
 * rekrutacji na wspólne pytanie) i to, co już zapisane, się nie liczą.
 * Wpis z pamięci równy wartości startowej formularza (np. „Tak” wpisane
 * w kotwicy, gdy inna rekrutacja ma już „Tak”) nie jest dla formularza
 * „ruszony”, więc zostaje dzięki temu, że był w pamięci wcześniej.
 * Zapis czyści pamięć (D2 A): rekrutacje odznaczone tracą wpisy, para,
 * której zapis się nie udał, zachowuje swoje.
 */

import type { RateUnit, ScreeningSkipReason } from "@/lib/api";
import type { ScreeningFormState } from "@/lib/api/screeningForm";
import {
  CLIENT_KEY,
  SHARED_ASSESSMENT_KEYS,
  SHARED_TERMS_KEYS,
  clientKey,
  hitKey,
  jobKey,
  originHolds,
  type JointDirty,
  type JointGroup,
  type JointOrigin,
  type JointPair,
  type JointValues,
} from "@/lib/joint-screening";
import {
  editableCardKeys,
  formDefaultsFromState,
  formQuestions,
  rateFromValues,
  sameRate,
  type NoteImport,
  type ScreeningFullFormValues,
} from "@/lib/screening-form";

const SHARED_KEYS: ReadonlySet<string> = new Set<string>([...SHARED_TERMS_KEYS, ...SHARED_ASSESSMENT_KEYS]);
const CARD_ORIGINS: ReadonlySet<string> = new Set(["note_ai", "note_rule", "phrased"]);
const ANSWER_ORIGINS: ReadonlySet<string> = new Set(["phrased", "note_import", "reassign_suggested"]);

export interface MemoryRate {
  rate_amount: string;
  rate_unit: RateUnit;
  rate_currency: string;
}

/** Wpisy jednej rekrutacji (pary osoba–rekrutacja). */
export interface ScreeningMemoryPair {
  /**
   * Kiedy rekrutacja ostatnio była w rozmowie — przy wspólnym pytaniu wygrywa
   * odpowiedź z rekrutacji, która była zaznaczona najpóźniej.
   */
  touchedAt: number;
  /** Id pytania → odpowiedź. */
  answers?: Record<string, string>;
  /** Id pytania → „odpowiedź narusza deal-breaker”. */
  hits?: Record<string, boolean>;
  overall_fit?: ScreeningFullFormValues["overall_fit"];
  /** Pola karty tej rekrutacji (ocena i warunki spoza wspólnych). */
  card?: Record<string, string>;
  /** Stawka tej rekrutacji, gdy „Ta sama stawka we wszystkich” odznaczone. */
  rate?: MemoryRate;
  skip_missing?: boolean;
  skip_reason?: ScreeningSkipReason | null;
  internal_note?: string;
}

export interface ScreeningMemory {
  v: 1;
  /** Ostatnia zmiana — po 12 h bez zmian pamięć wygasa (lib/screening-memory-storage.ts). */
  updatedAt: number;
  /** Tablica, z której prowadzono rozmowę — zaznaczenie wraca tylko na niej. */
  anchorJobId: number;
  /** Inne zaznaczone rekrutacje (bez kotwicy). */
  selected: number[];
  /** `job_id` → wpisy tej rekrutacji. */
  pairs: Record<string, ScreeningMemoryPair>;
  /** Pola o osobie (dostępność, tryb pracy, …, red flags) i wspólna stawka. */
  shared: { card?: Record<string, string>; same_rate?: boolean; rate?: MemoryRate };
  /** `c<clientId>` → „Czy pracował u Klienta”. */
  clients: Record<string, string>;
  /**
   * Pochodzenie wartości (notatka, zdanie z haseł, podpowiedź Luny) pod stałymi
   * kluczami: `shared.card.<pole>`, `clients.c<id>`, `jobs.j<id>.card.<pole>`,
   * `answers.j<id>.<pytanie>` — niezależnie od grup pytań bieżącego zestawu.
   */
  origins: Record<string, JointOrigin>;
  /** Notatka z rozmowy („Uzupełnij z notatki”) — zapis zakłada ją raz. */
  note: { source: NoteImport; filled: number } | null;
}

/** Dostęp formularza do pamięci jego rozmowy (daje go panel osoby). */
export interface ScreeningMemoryLink {
  read: () => ScreeningMemory | null;
  write: (update: (prev: ScreeningMemory | null) => ScreeningMemory | null) => void;
  /** Klient kotwicy — „Czy pracował u Klienta” z rozmowy wspólnej w formularzu pojedynczym. */
  clientId?: number | null;
}

/** Wpis odznaczonej rekrutacji, który przepadnie przy zapisie (D2 A). */
export interface PendingMemoryItem {
  jobId: number;
  title: string;
  answers: number;
  /** Można ją zaznaczyć z powrotem (do wyboru i jest miejsce). */
  canReselect: boolean;
}

export const memoryAnswerPath = (jobId: number, questionId: string) => `answers.${jobKey(jobId)}.${questionId}`;

export function emptyMemory(anchorJobId: number, now: number): ScreeningMemory {
  return { v: 1, updatedAt: now, anchorJobId, selected: [], pairs: {}, shared: {}, clients: {}, origins: {}, note: null };
}

function cloneMemory(memory: ScreeningMemory): ScreeningMemory {
  return {
    ...memory,
    selected: [...memory.selected],
    pairs: { ...memory.pairs },
    shared: { ...memory.shared, card: { ...(memory.shared.card ?? {}) } },
    clients: { ...memory.clients },
    origins: { ...memory.origins },
  };
}

const hasKeys = (record: object | undefined) => record != null && Object.keys(record).length > 0;

/** Serwer zapisuje tekst bez skrajnych odstępów — „Tak ” to już zapisane „Tak”. */
const sameText = (a: string | null | undefined, b: string | null | undefined) => (a ?? "").trim() === (b ?? "").trim();

function pairHasEntries(pair: ScreeningMemoryPair | undefined): boolean {
  if (!pair) return false;
  return (
    hasKeys(pair.answers) ||
    hasKeys(pair.hits) ||
    hasKeys(pair.card) ||
    pair.overall_fit !== undefined ||
    pair.rate !== undefined ||
    pair.skip_missing !== undefined ||
    pair.internal_note !== undefined
  );
}

export function memoryHasEntries(memory: ScreeningMemory | null | undefined): memory is ScreeningMemory {
  if (!memory) return false;
  return (
    Object.values(memory.pairs).some(pairHasEntries) ||
    hasKeys(memory.shared.card) ||
    memory.shared.same_rate !== undefined ||
    memory.shared.rate !== undefined ||
    hasKeys(memory.clients) ||
    memory.note != null
  );
}

/** Puste rekrutacje i pochodzenia bez wartości znikają; nic do pamiętania = `null`. */
function prune(memory: ScreeningMemory): ScreeningMemory | null {
  for (const [id, pair] of Object.entries(memory.pairs)) {
    if (!pairHasEntries(pair)) delete memory.pairs[id];
  }
  if (!hasKeys(memory.shared.card)) delete memory.shared.card;
  return memoryHasEntries(memory) ? memory : null;
}

/** Co pamięć trzyma dla rekrutacji: liczba odpowiedzi i czy jest cokolwiek. */
export function memoryPairSummary(memory: ScreeningMemory | null | undefined, jobId: number): { answers: number; any: boolean } {
  const pair = memory?.pairs[String(jobId)];
  if (!pair) return { answers: 0, any: false };
  const answers = Object.values(pair.answers ?? {}).filter((v) => v.trim() !== "").length;
  return { answers, any: pairHasEntries(pair) };
}

const rateOf = (values: MemoryRate): MemoryRate => ({
  rate_amount: values.rate_amount,
  rate_unit: values.rate_unit,
  rate_currency: values.rate_currency,
});

const rateTouched = (dirty: { rate_amount?: boolean; rate_unit?: boolean; rate_currency?: boolean } | undefined) =>
  Boolean(dirty?.rate_amount || dirty?.rate_unit || dirty?.rate_currency);

function keepOrigin(origins: Record<string, JointOrigin>, path: string, origin: JointOrigin | undefined, value: string) {
  if (originHolds(origin, value)) origins[path] = { ...origin, value };
  else delete origins[path];
}

// ── Formularz wspólny ───────────────────────────────────────────────────

export interface JointMemoryInput {
  anchorJobId: number;
  /** Zaznaczone pary ze stanem, z którym pójdzie zapis (najświeższym). */
  pairs: readonly JointPair[];
  groups: readonly JointGroup[];
  values: JointValues;
  dirty: JointDirty;
  /** Pochodzenie z formularza (klucz = ścieżka pola formularza wspólnego). */
  origins: Readonly<Record<string, JointOrigin>>;
  note: { source: NoteImport; filled: number } | null;
  now: number;
}

/**
 * Pamięć po zmianie w formularzu wspólnym. Wpisy zaznaczonych rekrutacji
 * liczą się od nowa, odznaczonych zostają bez zmian.
 */
export function memoryFromJoint(prev: ScreeningMemory | null, input: JointMemoryInput): ScreeningMemory | null {
  const { pairs, groups, values, dirty, origins, now } = input;
  // Pole ruszone w tym formularzu albo przywrócone z pamięci z tą samą wartością.
  const heldText = (held: string | undefined, value: string) => held !== undefined && sameText(held, value);
  const heldRate = (held: MemoryRate | undefined, value: MemoryRate) =>
    held !== undefined && sameRate(rateFromValues(held), rateFromValues(value));
  const next = prev ? cloneMemory(prev) : emptyMemory(input.anchorJobId, now);
  next.anchorJobId = input.anchorJobId;
  next.selected = pairs.filter((p) => !p.anchor).map((p) => p.jobId);
  const defaults = new Map(pairs.map((p) => [p.jobId, formDefaultsFromState(p.state)]));

  for (const pair of pairs) {
    const d = defaults.get(pair.jobId)!;
    const key = jobKey(pair.jobId);
    const out: ScreeningMemoryPair = { touchedAt: now };
    const answers: Record<string, string> = {};
    const hits: Record<string, boolean> = {};
    for (const group of groups) {
      for (const member of group.members) {
        if (member.jobId !== pair.jobId) continue;
        const path = memoryAnswerPath(pair.jobId, member.questionId);
        const value = values.answers[group.key] ?? "";
        const server = d.answers[member.questionId]?.response ?? "";
        const held = prev?.pairs[String(pair.jobId)]?.answers?.[member.questionId];
        if ((dirty.answers?.[group.key] || heldText(held, value)) && !sameText(value, server)) {
          answers[member.questionId] = value;
          keepOrigin(next.origins, path, origins[`answers.${group.key}`], value);
        } else {
          delete next.origins[path];
        }
        const hk = hitKey(pair.jobId, member.questionId);
        const hit = Boolean(values.hits[hk]);
        if (dirty.hits?.[hk] && hit !== Boolean(d.answers[member.questionId]?.deal_breaker_hit)) {
          hits[member.questionId] = hit;
        }
      }
    }
    if (hasKeys(answers)) out.answers = answers;
    if (hasKeys(hits)) out.hits = hits;

    const own = values.jobs[key];
    const ownDirty = dirty.jobs?.[key];
    if (own) {
      if (ownDirty?.overall_fit && own.overall_fit !== d.overall_fit) out.overall_fit = own.overall_fit;
      const card: Record<string, string> = {};
      for (const [cardKey, value] of Object.entries(own.card)) {
        const path = `jobs.${key}.card.${cardKey}`;
        if (ownDirty?.card?.[cardKey] && !sameText(value, d.card[cardKey])) {
          card[cardKey] = value;
          keepOrigin(next.origins, path, origins[path], value);
        } else {
          delete next.origins[path];
        }
      }
      if (hasKeys(card)) out.card = card;
      const ownRateHeld = heldRate(prev?.pairs[String(pair.jobId)]?.rate, own);
      if ((rateTouched(ownDirty) || ownRateHeld) && !sameRate(rateFromValues(own), rateFromValues(d))) out.rate = rateOf(own);
      if (ownDirty?.skip_missing && own.skip_missing !== Boolean(d.skip_missing)) {
        out.skip_missing = own.skip_missing;
        out.skip_reason = own.skip_reason;
      }
      if (ownDirty?.internal_note && !sameText(own.internal_note, d.internal_note)) out.internal_note = own.internal_note;
    }
    next.pairs[String(pair.jobId)] = out;
  }

  // Pola o osobie: ruszone i inne niż zapisane w którejś zaznaczonej parze.
  const sharedCard = { ...(next.shared.card ?? {}) };
  for (const [cardKey, value] of Object.entries(values.shared.card)) {
    const path = `shared.card.${cardKey}`;
    const differs = pairs.some(
      (p) => editableCardKeys(p.state).includes(cardKey) && !sameText(defaults.get(p.jobId)!.card[cardKey], value),
    );
    if ((dirty.shared?.card?.[cardKey] || heldText(prev?.shared.card?.[cardKey], value)) && differs) {
      sharedCard[cardKey] = value;
      keepOrigin(next.origins, path, origins[path], value);
    } else {
      delete sharedCard[cardKey];
      delete next.origins[path];
    }
  }
  next.shared.card = sharedCard;
  for (const [key, value] of Object.entries(values.clients)) {
    const path = `clients.${key}`;
    const withClient = pairs.filter((p) => clientKey(p.clientId) === key && editableCardKeys(p.state).includes(CLIENT_KEY));
    const differs = withClient.some((p) => !sameText(defaults.get(p.jobId)!.card[CLIENT_KEY], value));
    const held =
      prev?.clients[key] ?? withClient.map((p) => prev?.pairs[String(p.jobId)]?.card?.[CLIENT_KEY]).find((v) => v !== undefined);
    if ((dirty.clients?.[key] || heldText(held, value)) && differs) {
      next.clients[key] = value;
      keepOrigin(next.origins, path, origins[path], value);
    } else {
      delete next.clients[key];
      delete next.origins[path];
    }
  }
  // Kotwica dostaje kopię przy sobie: formularz pojedynczy przywraca ją bez
  // znajomości klienta (ten przychodzi z listy „Screening dla” później).
  const anchorPair = pairs.find((p) => p.anchor);
  const anchorClient = anchorPair ? next.clients[clientKey(anchorPair.clientId)] : undefined;
  if (anchorPair && anchorClient !== undefined && editableCardKeys(anchorPair.state).includes(CLIENT_KEY)) {
    const out = next.pairs[String(anchorPair.jobId)];
    out.card = { ...(out.card ?? {}), [CLIENT_KEY]: anchorClient };
  }

  const sharedRate = rateFromValues(values.shared);
  const sharedRateHeld = heldRate(prev?.shared.rate, values.shared);
  if (
    (rateTouched(dirty.shared) || sharedRateHeld) &&
    pairs.some((p) => !sameRate(sharedRate, rateFromValues(defaults.get(p.jobId)!)))
  ) {
    next.shared.rate = rateOf(values.shared);
  } else {
    delete next.shared.rate;
  }
  // Zapamiętana stawka idzie z trybem („ta sama” / osobno), w którym ją wpisano —
  // formularz wspólny startuje z trybem zależnym od stawek par na start.
  const rateRemembered = next.shared.rate !== undefined || Object.values(next.pairs).some((p) => p.rate !== undefined);
  if (dirty.shared?.same_rate || rateRemembered || prev?.shared.same_rate === values.shared.same_rate) {
    next.shared.same_rate = values.shared.same_rate;
  } else {
    delete next.shared.same_rate;
  }

  next.note = input.note;
  next.updatedAt = now;
  return prune(next);
}

export interface JointRestore {
  patches: Array<{ path: string; value: unknown }>;
  /** Pochodzenie pod ścieżkami formularza wspólnego. */
  origins: Record<string, JointOrigin>;
  note: { source: NoteImport; filled: number } | null;
}

/**
 * Co formularz wspólny ma wpisać z pamięci przy starcie (jako zmiany
 * rekrutera). Wspólne pytanie bierze odpowiedź z rekrutacji, która była
 * w rozmowie najpóźniej (remis — kotwica, potem kolejność par).
 */
export function jointRestore(
  memory: ScreeningMemory | null,
  pairs: readonly JointPair[],
  groups: readonly JointGroup[],
  values: JointValues,
): JointRestore {
  const out: JointRestore = { patches: [], origins: {}, note: memory?.note ?? null };
  if (!memory) return out;
  const add = (path: string, value: unknown, origin?: JointOrigin) => {
    out.patches.push({ path, value });
    if (origin && typeof value === "string" && originHolds(origin, value)) out.origins[path] = origin;
  };

  for (const [cardKey, value] of Object.entries(memory.shared.card ?? {})) {
    if (values.shared.card[cardKey] !== undefined) add(`shared.card.${cardKey}`, value, memory.origins[`shared.card.${cardKey}`]);
  }
  for (const key of Object.keys(values.clients)) {
    // Wpis przy samej parze zostawia tylko formularz pojedynczy, a wspólny go
    // przenosi do klienta — więc jeśli jest, jest nowszy.
    const fromSingle = pairs
      .filter((p) => clientKey(p.clientId) === key)
      .map((p) => memory.pairs[String(p.jobId)]?.card?.[CLIENT_KEY])
      .find((v) => v !== undefined);
    const value = fromSingle ?? memory.clients[key];
    if (value !== undefined) add(`clients.${key}`, value, memory.origins[`clients.${key}`]);
  }
  // Stawka wraca tam, gdzie ją widać: w trybie „ta sama” do pola wspólnego,
  // osobno — do pola rekrutacji (stawka z formularza pojedynczego jest kotwicy).
  const sameRateNow = memory.shared.same_rate ?? values.shared.same_rate;
  if (memory.shared.same_rate !== undefined) add("shared.same_rate", memory.shared.same_rate);
  const anchorPair = pairs.find((p) => p.anchor);
  const sharedRate =
    memory.shared.rate ??
    (sameRateNow
      ? ((anchorPair ? memory.pairs[String(anchorPair.jobId)]?.rate : undefined) ??
        pairs.map((p) => memory.pairs[String(p.jobId)]?.rate).find((r) => r !== undefined))
      : undefined);
  if (sharedRate) {
    add("shared.rate_amount", sharedRate.rate_amount);
    add("shared.rate_unit", sharedRate.rate_unit);
    add("shared.rate_currency", sharedRate.rate_currency);
  }

  for (const pair of pairs) {
    const saved = memory.pairs[String(pair.jobId)];
    const key = jobKey(pair.jobId);
    const own = values.jobs[key];
    if (!saved || !own) continue;
    if (saved.overall_fit !== undefined) add(`jobs.${key}.overall_fit`, saved.overall_fit);
    for (const [cardKey, value] of Object.entries(saved.card ?? {})) {
      if (own.card[cardKey] !== undefined) add(`jobs.${key}.card.${cardKey}`, value, memory.origins[`jobs.${key}.card.${cardKey}`]);
    }
    const ownRate = saved.rate ?? (pair.anchor && !sameRateNow ? memory.shared.rate : undefined);
    if (ownRate) {
      add(`jobs.${key}.rate_amount`, ownRate.rate_amount);
      add(`jobs.${key}.rate_unit`, ownRate.rate_unit);
      add(`jobs.${key}.rate_currency`, ownRate.rate_currency);
    }
    if (saved.skip_missing !== undefined) {
      add(`jobs.${key}.skip_missing`, saved.skip_missing);
      add(`jobs.${key}.skip_reason`, saved.skip_reason ?? null);
    }
    if (saved.internal_note !== undefined) add(`jobs.${key}.internal_note`, saved.internal_note);
    for (const [questionId, hit] of Object.entries(saved.hits ?? {})) {
      const hk = hitKey(pair.jobId, questionId);
      if (values.hits[hk] !== undefined) add(`hits.${hk}`, hit);
    }
  }

  const order = new Map(pairs.map((p, i) => [p.jobId, p.anchor ? -1 : i]));
  for (const group of groups) {
    const candidates = group.members
      .map((m) => ({ member: m, value: memory.pairs[String(m.jobId)]?.answers?.[m.questionId] }))
      .filter((c): c is { member: typeof c.member; value: string } => c.value !== undefined)
      .sort(
        (a, b) =>
          (memory.pairs[String(b.member.jobId)]?.touchedAt ?? 0) - (memory.pairs[String(a.member.jobId)]?.touchedAt ?? 0) ||
          (order.get(a.member.jobId) ?? 0) - (order.get(b.member.jobId) ?? 0),
      );
    const pick = candidates[0];
    if (!pick) continue;
    out.patches.push({ path: `answers.${group.key}`, value: pick.value });
    const origin = memory.origins[memoryAnswerPath(pick.member.jobId, pick.member.questionId)];
    if (originHolds(origin, pick.value)) out.origins[`answers.${group.key}`] = origin;
  }
  return out;
}

// ── Formularz pojedynczy ────────────────────────────────────────────────

/** Ruszone pola pojedynczego formularza (`formState.dirtyFields` RHF). */
export interface SingleDirty {
  answers?: Record<string, { response?: boolean; deal_breaker_hit?: boolean } | undefined>;
  card?: Record<string, boolean | undefined>;
  overall_fit?: boolean;
  skip_missing?: boolean;
  internal_note?: boolean;
}

export interface SingleMemoryInput {
  anchorJobId: number;
  state: ScreeningFormState;
  values: ScreeningFullFormValues;
  dirty: SingleDirty;
  /** Rekruter sam ruszył stawkę (stawka na start z notatki/karty się nie liczy). */
  rateTouched: boolean;
  note: { source: NoteImport; filled: number } | null;
  now: number;
}

/**
 * Stawka z formularza pojedynczego jest stawką tej rekrutacji — do pola
 * wspólnego idzie tylko wtedy, gdy rozmowa była w trybie „ta sama stawka”.
 */
function sharedRateMode(memory: ScreeningMemory): boolean {
  return memory.shared.same_rate === true;
}

export function memoryFromSingle(prev: ScreeningMemory | null, input: SingleMemoryInput): ScreeningMemory | null {
  const { state, values, dirty, now } = input;
  const next = prev ? cloneMemory(prev) : emptyMemory(input.anchorJobId, now);
  const d = formDefaultsFromState(state);
  const jobId = state.job_id;
  const key = jobKey(jobId);
  const out: ScreeningMemoryPair = { touchedAt: now };

  const answers: Record<string, string> = {};
  const hits: Record<string, boolean> = {};
  for (const [questionId, answer] of Object.entries(values.answers ?? {})) {
    const path = memoryAnswerPath(jobId, questionId);
    const before = d.answers[questionId];
    const response = answer?.response ?? "";
    if (dirty.answers?.[questionId]?.response && !sameText(response, before?.response)) {
      answers[questionId] = response;
      const origin = answer?.origin;
      if (origin && ANSWER_ORIGINS.has(origin)) {
        next.origins[path] = { value: response, origin: origin as JointOrigin["origin"], keywords: answer?.keywords ?? null };
      } else {
        delete next.origins[path];
      }
    } else {
      delete next.origins[path];
    }
    const hit = Boolean(answer?.deal_breaker_hit);
    if (dirty.answers?.[questionId]?.deal_breaker_hit && hit !== Boolean(before?.deal_breaker_hit)) hits[questionId] = hit;
  }
  if (hasKeys(answers)) out.answers = answers;
  if (hasKeys(hits)) out.hits = hits;

  const card: Record<string, string> = {};
  const sharedCard = { ...(next.shared.card ?? {}) };
  for (const [cardKey, value] of Object.entries(values.card ?? {})) {
    const touched = Boolean(dirty.card?.[cardKey]) && !sameText(value, d.card[cardKey]);
    const origin = values.card_origins?.[cardKey];
    const held: JointOrigin | undefined =
      origin && CARD_ORIGINS.has(origin.origin) ? { value, origin: origin.origin, keywords: origin.keywords ?? null } : undefined;
    const path = SHARED_KEYS.has(cardKey) ? `shared.card.${cardKey}` : `jobs.${key}.card.${cardKey}`;
    if (SHARED_KEYS.has(cardKey)) {
      if (touched) sharedCard[cardKey] = value;
      else delete sharedCard[cardKey];
    } else if (touched) {
      card[cardKey] = value;
    }
    if (touched && held) next.origins[path] = held;
    else delete next.origins[path];
  }
  next.shared.card = sharedCard;
  if (hasKeys(card)) out.card = card;

  const rateChanged = input.rateTouched && !sameRate(rateFromValues(values), rateFromValues(d));
  if (sharedRateMode(next)) {
    if (rateChanged) next.shared.rate = rateOf(values);
    else delete next.shared.rate;
  } else {
    delete next.shared.rate;
    if (rateChanged) out.rate = rateOf(values);
  }

  if (dirty.overall_fit && values.overall_fit !== d.overall_fit) out.overall_fit = values.overall_fit;
  if (dirty.skip_missing && Boolean(values.skip_missing) !== Boolean(d.skip_missing)) {
    out.skip_missing = Boolean(values.skip_missing);
    out.skip_reason = values.skip_reason ?? null;
  }
  if (dirty.internal_note && !sameText(values.internal_note, d.internal_note)) {
    out.internal_note = values.internal_note ?? "";
  }
  next.pairs[String(jobId)] = out;
  next.note = input.note;
  next.updatedAt = now;
  return prune(next);
}

export interface SingleRestore {
  patches: Array<[string, unknown]>;
  /** Stawka przyszła z pamięci — formularz nie wpisze stawki na start. */
  rateTouched: boolean;
  note: { source: NoteImport; filled: number } | null;
}

/** Co pojedynczy formularz pary ma wpisać z pamięci przy starcie. */
export function singleRestore(
  memory: ScreeningMemory | null,
  state: ScreeningFormState,
  clientId?: number | null,
): SingleRestore {
  const out: SingleRestore = { patches: [], rateTouched: false, note: memory?.note ?? null };
  if (!memory) return out;
  const jobId = state.job_id;
  const key = jobKey(jobId);
  const saved = memory.pairs[String(jobId)];
  const questionIds = new Set(formQuestions(state).map((q) => q.id));

  for (const [questionId, response] of Object.entries(saved?.answers ?? {})) {
    if (!questionIds.has(questionId)) continue;
    out.patches.push([`answers.${questionId}.response`, response]);
    const origin = memory.origins[memoryAnswerPath(jobId, questionId)];
    if (originHolds(origin, response) && ANSWER_ORIGINS.has(origin.origin)) {
      out.patches.push([`answers.${questionId}.origin`, origin.origin]);
      out.patches.push([`answers.${questionId}.keywords`, origin.keywords ?? null]);
    } else {
      out.patches.push([`answers.${questionId}.origin`, "manual"]);
    }
  }
  for (const [questionId, hit] of Object.entries(saved?.hits ?? {})) {
    if (questionIds.has(questionId)) out.patches.push([`answers.${questionId}.deal_breaker_hit`, hit]);
  }

  for (const cardKey of editableCardKeys(state)) {
    let value: string | undefined;
    let path: string;
    if (SHARED_KEYS.has(cardKey)) {
      value = memory.shared.card?.[cardKey];
      path = `shared.card.${cardKey}`;
    } else if (cardKey === CLIENT_KEY && saved?.card?.[cardKey] === undefined && clientId !== undefined) {
      value = memory.clients[clientKey(clientId)];
      path = `clients.${clientKey(clientId)}`;
    } else {
      value = saved?.card?.[cardKey];
      path = `jobs.${key}.card.${cardKey}`;
    }
    if (value === undefined) continue;
    out.patches.push([`card.${cardKey}`, value]);
    const origin = memory.origins[path];
    if (originHolds(origin, value) && CARD_ORIGINS.has(origin.origin)) {
      out.patches.push([
        `card_origins.${cardKey}`,
        origin.keywords ? { origin: origin.origin, keywords: origin.keywords } : { origin: origin.origin },
      ]);
    }
  }

  const rate = sharedRateMode(memory) ? (memory.shared.rate ?? saved?.rate) : (saved?.rate ?? memory.shared.rate);
  if (rate) {
    out.patches.push(["rate_amount", rate.rate_amount], ["rate_unit", rate.rate_unit], ["rate_currency", rate.rate_currency]);
    out.rateTouched = true;
  }
  if (saved?.overall_fit !== undefined) out.patches.push(["overall_fit", saved.overall_fit]);
  if (saved?.skip_missing !== undefined) {
    out.patches.push(["skip_missing", saved.skip_missing], ["skip_reason", saved.skip_reason ?? null]);
  }
  if (saved?.internal_note !== undefined) out.patches.push(["internal_note", saved.internal_note]);
  return out;
}

// ── Zapis, zaznaczenie ──────────────────────────────────────────────────

/**
 * Po zapisie (D2 A): udany zapis czyści pamięć całej rozmowy, także wpisy
 * odznaczonych rekrutacji. Para, której zapis się nie udał (cudza rezerwacja,
 * konflikt wersji), zachowuje swoje wpisy, pola o osobie i notatkę.
 */
export function memoryAfterSave(
  memory: ScreeningMemory | null,
  failedJobIds: readonly number[],
  now: number,
): ScreeningMemory | null {
  if (!memory || failedJobIds.length === 0) return null;
  const next = cloneMemory(memory);
  const keep = new Set(failedJobIds.map(String));
  for (const id of Object.keys(next.pairs)) {
    if (keep.has(id)) continue;
    delete next.pairs[id];
    for (const path of Object.keys(next.origins)) {
      if (path.startsWith(`answers.j${id}.`) || path.startsWith(`jobs.j${id}.`)) delete next.origins[path];
    }
  }
  next.updatedAt = now;
  return prune(next);
}

/** Zaznaczenie „Screening dla” — zapamiętane tylko przy rozmowie, która coś już ma. */
export function memoryWithSelection(
  memory: ScreeningMemory | null,
  anchorJobId: number,
  selected: readonly number[],
  now: number,
): ScreeningMemory | null {
  if (!memory) return null;
  return { ...cloneMemory(memory), anchorJobId, selected: [...selected], updatedAt: now };
}
