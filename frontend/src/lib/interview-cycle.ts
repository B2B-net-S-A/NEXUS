/**
 * Cykl rozmowy u klienta — typy i czysta logika ekranu „Rozmowy u klienta”.
 *
 * Kalendarz na produkcji był kopią Outlooka: w NEXUSIE nikt nie umawiał
 * rozmów, bo zespół planuje tylko prep, drugi prep i musi znać termin rozmowy
 * kandydata u klienta, żeby zadzwonić ≤30 min po niej. Ekran prowadzi więc
 * jeden cykl per para (kandydat, rekrutacja):
 *
 *   Terminy od klienta (DL) → Wybór terminu (rekruter) → Prep → Prep 2
 *   → Rozmowa u klienta → Telefon po rozmowie → Debrief
 *
 * Kroki i listę „Do zrobienia” liczy SERWER (`services/interview_cycle.py`).
 * Tu jest tylko prezentacja: etykiety, grupowanie agendy po dniu i odliczanie.
 * Typy są lustrem `backend/app/api/interview_cycle.py`.
 */

export type CycleScope = "mine" | "jobs" | "all";
export type CycleView = "agenda" | "week" | "board";

export type StepKey =
  | "slots"
  | "choice"
  | "prep"
  | "prep2"
  | "interview"
  | "call"
  | "debrief";

export type StepState =
  | "done"
  | "current"
  | "scheduled"
  | "waiting"
  | "todo"
  | "overdue"
  | "skipped";

export interface CycleStep {
  key: StepKey;
  label: string;
  state: StepState;
  at: string | null;
  event_id: number | null;
  meta: string | null;
}

export interface SlotItem {
  start: string;
  end: string | null;
}

export type SlotRequestStatus =
  | "awaiting_recruiter"
  | "awaiting_dl"
  | "confirmed"
  | "cancelled";

export interface SlotRequest {
  id: number;
  status: SlotRequestStatus;
  slots: SlotItem[];
  chosen_index: number | null;
  respond_by: string | null;
  recruiter_id: number | null;
  created_by: number | null;
  duration_minutes: number;
  note: string | null;
  event_id: number | null;
}

export interface PairInfo {
  candidate_id: number;
  /** `null`, gdy rola nie czyta kandydatów — wtedy pokazujemy „Kandydat #id”. */
  candidate_name: string | null;
  /** Do zaproszenia na prep; `null` bez odczytu kandydatów. */
  candidate_email: string | null;
  job_id: number;
  job_title: string | null;
  client_id: number | null;
  client_name: string | null;
}

export type OfferAcceptance = "yes" | "likely" | "no" | "unknown";
export type DebriefOutcome = "good" | "medium" | "bad";

export interface CycleItem extends PairInfo {
  steps: CycleStep[];
  current_step: StepKey | null;
  latest_stage: string | null;
  slot_request: SlotRequest | null;
  interview_event_id: number | null;
  debrief: {
    id: number;
    overall_impression: number | null;
    offer_acceptance: OfferAcceptance | null;
    acceptance_condition: string | null;
  } | null;
}

export type AgendaKind = "prep" | "prep2" | "interview" | "call" | "tentative";

export interface AgendaEntry extends PairInfo {
  kind: AgendaKind;
  start: string;
  end: string | null;
  event_id: number | null;
  slot_request_id: number | null;
  online_meeting_url: string | null;
  done: boolean;
}

export type TodoKind =
  | "call_now"
  | "debrief_overdue"
  | "slots_pick"
  | "slots_confirm"
  | "prep_missing"
  | "prep2_missing"
  | "slots_missing";

export interface TodoEntry extends PairInfo {
  kind: TodoKind;
  priority: number;
  due: string | null;
  event_id: number | null;
  slot_request_id: number | null;
}

export interface CycleOverview {
  generated_at: string;
  scope: CycleScope;
  call_window_minutes: number;
  items: CycleItem[];
  agenda: AgendaEntry[];
  todos: TodoEntry[];
  truncated: boolean;
}

export interface Debrief {
  id: number;
  calendar_event_id: number;
  candidate_id: number;
  job_id: number | null;
  outcome: DebriefOutcome | null;
  candidate_comment: string | null;
  questions: string[];
  offer_acceptance: OfferAcceptance | null;
  acceptance_condition: string | null;
  /** Rekruter potwierdził, że klient nie zadawał pytań (bramka przed „Umową”). */
  no_client_questions: boolean;
  questions_saved: number;
}

export interface DebriefInput {
  outcome: DebriefOutcome;
  candidate_comment?: string | null;
  questions: string[];
  offer_acceptance: OfferAcceptance;
  acceptance_condition?: string | null;
  notify_dl: boolean;
  /** Pusta lista pytań wymaga jawnego „klient nie zadawał pytań” (422 bez tego). */
  no_client_questions?: boolean;
}

// ── Etykiety ──────────────────────────────────────────────────────────────────

export const STEP_ORDER: StepKey[] = [
  "slots",
  "choice",
  "prep",
  "prep2",
  "interview",
  "call",
  "debrief",
];

export const STEP_TITLES: Record<StepKey, string> = {
  slots: "Terminy od klienta",
  choice: "Wybór terminu",
  prep: "Prep",
  prep2: "Prep 2",
  interview: "Rozmowa u klienta",
  call: "Telefon ≤ 30 min",
  debrief: "Debrief",
};

/** Kto wykonuje krok — nagłówek kolumny na tablicy. */
export const STEP_OWNER: Record<StepKey, string> = {
  slots: "DL wpisuje terminy",
  choice: "rekruter ↔ kandydat",
  prep: "rekruter planuje",
  prep2: "rekruter planuje",
  interview: "kandydat u klienta",
  call: "rekruter dzwoni",
  debrief: "notatka dla DL",
};

export const AGENDA_LABELS: Record<AgendaKind, string> = {
  prep: "Prep",
  prep2: "Prep 2",
  interview: "Rozmowa u klienta",
  call: "Telefon po rozmowie",
  tentative: "Termin czeka na DL",
};

export const TODO_LABELS: Record<TodoKind, string> = {
  call_now: "Zadzwoń teraz",
  debrief_overdue: "Debrief zaległy",
  slots_pick: "Terminy czekają na kandydata",
  slots_confirm: "Potwierdź termin u klienta",
  prep_missing: "Prep bez terminu",
  prep2_missing: "Drugi prep bez terminu",
  slots_missing: "Brak terminów od klienta",
};

export const TODO_ACTIONS: Record<TodoKind, string> = {
  call_now: "Zapisz debrief",
  debrief_overdue: "Uzupełnij",
  slots_pick: "Wybierz termin",
  slots_confirm: "Potwierdź",
  prep_missing: "Zaplanuj prep",
  prep2_missing: "Zaplanuj prep 2",
  slots_missing: "Dodaj terminy",
};

export const OFFER_LABELS: Record<OfferAcceptance, string> = {
  yes: "Tak",
  likely: "Raczej tak",
  no: "Nie",
  unknown: "Nie wiadomo",
};

export const OUTCOME_LABELS: Record<DebriefOutcome, string> = {
  good: "Dobrze",
  medium: "Średnio",
  bad: "Źle",
};

export function candidateLabel(p: Pick<PairInfo, "candidate_id" | "candidate_name">): string {
  return p.candidate_name?.trim() || `Kandydat #${p.candidate_id}`;
}

export function pairContext(p: Pick<PairInfo, "client_name" | "job_title">): string {
  return [p.client_name, p.job_title].filter(Boolean).join(" · ") || "Rekrutacja bez nazwy";
}

export function pairKey(p: Pick<PairInfo, "candidate_id" | "job_id">): string {
  return `${p.candidate_id}-${p.job_id}`;
}

// ── Czas ──────────────────────────────────────────────────────────────────────

const TZ = "Europe/Warsaw";

function dayKey(date: Date): string {
  // en-CA daje RRRR-MM-DD — klucz dnia w strefie biznesowej, nie przeglądarki.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

export function formatTime(iso: string): string {
  return new Intl.DateTimeFormat("pl-PL", {
    timeZone: TZ,
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function formatDayLabel(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  const key = dayKey(d);
  const today = dayKey(now);
  const tomorrow = dayKey(new Date(now.getTime() + 86_400_000));
  const short = new Intl.DateTimeFormat("pl-PL", {
    timeZone: TZ,
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
  }).format(d);
  if (key === today) return `Dziś · ${short}`;
  if (key === tomorrow) return `Jutro · ${short}`;
  return short.charAt(0).toUpperCase() + short.slice(1);
}

/**
 * Debrief to zapis telefonu PO rozmowie u klienta — da się go zapisać dopiero
 * od jej rozpoczęcia (serwer odmawia wcześniej, `PUT …/debrief` → 422).
 */
export function debriefAvailable(interviewStart: string | null | undefined, now: Date = new Date()): boolean {
  if (!interviewStart) return true;
  return new Date(interviewStart).getTime() <= now.getTime();
}

/** Początek rozmowy u klienta `eventId` z migawki ekranu (krok „Rozmowa”
 * pary albo wpis agendy); `undefined` = nie wiadomo (okno zapyta serwer). */
export function interviewStartFor(
  data: CycleOverview | null | undefined,
  eventId: number,
): string | undefined {
  if (!data) return undefined;
  for (const item of data.items) {
    const step = item.steps.find((s) => s.key === "interview" && s.event_id === eventId);
    if (step?.at) return step.at;
  }
  const entry = data.agenda.find((a) => a.kind === "interview" && a.event_id === eventId);
  return entry?.start ?? undefined;
}

/** „Debrief po rozmowie — dostępny od 14:00” (inny dzień: „od jutra, 14:00”). */
export function debriefAvailableFromLabel(interviewStart: string, now: Date = new Date()): string {
  const time = formatTime(interviewStart);
  const key = dayKey(new Date(interviewStart));
  let when: string;
  if (key === dayKey(now)) when = time;
  else if (key === dayKey(new Date(now.getTime() + 86_400_000))) when = `jutra, ${time}`;
  else {
    const day = new Intl.DateTimeFormat("pl-PL", {
      timeZone: TZ,
      day: "2-digit",
      month: "2-digit",
    }).format(new Date(interviewStart));
    when = `${day}, ${time}`;
  }
  return `Debrief po rozmowie — dostępny od ${when}`;
}

export function formatSlot(slot: SlotItem): string {
  const start = new Date(slot.start);
  const day = new Intl.DateTimeFormat("pl-PL", {
    timeZone: TZ,
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
  }).format(start);
  const range = slot.end
    ? `${formatTime(slot.start)}–${formatTime(slot.end)}`
    : formatTime(slot.start);
  return `${day} ${range}`;
}

export interface AgendaDay {
  key: string;
  label: string;
  entries: AgendaEntry[];
}

/** Agenda pogrupowana po dniu (strefa Europe/Warsaw), dni chronologicznie. */
export function groupAgendaByDay(entries: AgendaEntry[], now: Date = new Date()): AgendaDay[] {
  const map = new Map<string, AgendaDay>();
  const sorted = [...entries].sort(
    (a, b) => new Date(a.start).getTime() - new Date(b.start).getTime(),
  );
  for (const e of sorted) {
    const key = dayKey(new Date(e.start));
    if (!map.has(key)) {
      map.set(key, { key, label: formatDayLabel(e.start, now), entries: [] });
    }
    map.get(key)!.entries.push(e);
  }
  return [...map.values()].sort((a, b) => a.key.localeCompare(b.key));
}

/** Agenda od dziś w przód (przeszłe dni tylko, gdy wisi na nich coś niezamkniętego). */
export function upcomingAgenda(entries: AgendaEntry[], now: Date = new Date()): AgendaEntry[] {
  const today = dayKey(now);
  return entries.filter((e) => dayKey(new Date(e.start)) >= today || (e.kind === "call" && !e.done));
}

/**
 * „zostało 18 min” / „po terminie 12 min” — odliczanie do końca okna
 * telefonu. Minuty w górę: „zostało 0 min” czytałoby się jak „już po”.
 */
export function countdownLabel(dueIso: string, now: Date = new Date()): string {
  const diffMs = new Date(dueIso).getTime() - now.getTime();
  const minutes = Math.ceil(Math.abs(diffMs) / 60_000);
  const text = minutes >= 120 ? `${Math.floor(minutes / 60)} h` : `${minutes} min`;
  return diffMs >= 0 ? `zostało ${text}` : `po terminie ${text}`;
}

export function relativeLabel(iso: string, now: Date = new Date()): string {
  const diffMs = new Date(iso).getTime() - now.getTime();
  const abs = Math.abs(diffMs);
  const minutes = Math.round(abs / 60_000);
  let text: string;
  if (minutes < 60) text = `${minutes} min`;
  else if (minutes < 60 * 24) {
    const rest = minutes % 60;
    text = rest ? `${Math.floor(minutes / 60)} h ${rest} min` : `${Math.floor(minutes / 60)} h`;
  }
  else text = `${Math.round(minutes / (60 * 24))} dni`;
  return diffMs >= 0 ? `za ${text}` : `${text} temu`;
}

/** Stan kroku → wariant wizualny (tokeny, nie kolory na sztywno). */
export function stepTone(state: StepState): "done" | "current" | "warn" | "danger" | "muted" {
  switch (state) {
    case "done":
      return "done";
    case "current":
    case "scheduled":
      return "current";
    case "waiting":
      return "warn";
    case "overdue":
      return "danger";
    default:
      return "muted";
  }
}

/**
 * Kolumna tablicy, w której stoi para: krok bieżący; para z zamkniętym
 * debriefem nie stoi nigdzie (cykl skończony).
 */
export function boardColumn(item: CycleItem): StepKey | null {
  return item.current_step;
}

/** Parsuje `?cycle=12-34` → para, żeby link z dzwonka otworzył kartę kandydata. */
export function parseCycleParam(raw: string | null): { candidateId: number; jobId: number } | null {
  if (!raw) return null;
  const m = /^(\d+)-(\d+)$/.exec(raw.trim());
  if (!m) return null;
  return { candidateId: Number(m[1]), jobId: Number(m[2]) };
}

export function parseView(raw: string | null, hasEventParam: boolean): CycleView {
  // Link do konkretnego wydarzenia (`?event=`) otwiera je w siatce tygodnia.
  if (hasEventParam) return "week";
  return raw === "week" || raw === "board" ? raw : "agenda";
}

export function parseScope(raw: string | null, fallback: CycleScope): CycleScope {
  return raw === "mine" || raw === "jobs" || raw === "all" ? raw : fallback;
}

// ── Akcje ─────────────────────────────────────────────────────────────────────

export type CycleAction =
  | { type: "debrief"; pair: PairInfo; eventId: number }
  | { type: "pick"; pair: PairInfo; request: SlotRequest }
  | { type: "confirm"; pair: PairInfo; request: SlotRequest }
  | { type: "plan_prep"; pair: PairInfo; second: boolean }
  | { type: "add_slots"; pair: PairInfo | null }
  | { type: "open_event"; eventId: number };

function pairOf(p: PairInfo): PairInfo {
  return {
    candidate_id: p.candidate_id,
    candidate_name: p.candidate_name,
    candidate_email: p.candidate_email,
    job_id: p.job_id,
    job_title: p.job_title,
    client_id: p.client_id,
    client_name: p.client_name,
  };
}

/** Pozycja „Do zrobienia” → akcja przycisku. `null` = pozycja tylko informuje. */
export function actionForTodo(todo: TodoEntry, items: CycleItem[]): CycleAction | null {
  const pair = pairOf(todo);
  const item = items.find((i) => i.candidate_id === todo.candidate_id && i.job_id === todo.job_id);
  switch (todo.kind) {
    case "call_now":
    case "debrief_overdue":
      return todo.event_id != null ? { type: "debrief", pair, eventId: todo.event_id } : null;
    case "slots_pick":
      return item?.slot_request ? { type: "pick", pair, request: item.slot_request } : null;
    case "slots_confirm":
      return item?.slot_request ? { type: "confirm", pair, request: item.slot_request } : null;
    case "prep_missing":
      return { type: "plan_prep", pair, second: false };
    case "prep2_missing":
      return { type: "plan_prep", pair, second: true };
    case "slots_missing":
      return { type: "add_slots", pair };
    default:
      return null;
  }
}

/**
 * Akcja kroku bieżącego pary (przycisk w stepperze i na karcie tablicy).
 * `canManageSlots` = rola DL/TAC/nadzór — tylko ona dodaje i potwierdza terminy.
 */
export function actionForItem(
  item: CycleItem,
  { canManageSlots }: { canManageSlots: boolean },
): { stepKey: StepKey; label: string; action: CycleAction } | null {
  const pair = pairOf(item);
  const req = item.slot_request;
  const current = item.steps.find((s) =>
    ["current", "overdue", "waiting"].includes(s.state),
  );
  if (!current) return null;
  switch (current.key) {
    case "slots":
      return canManageSlots
        ? { stepKey: "slots", label: "Dodaj terminy", action: { type: "add_slots", pair } }
        : null;
    case "choice":
      if (req?.status === "awaiting_recruiter") {
        return { stepKey: "choice", label: "Wybierz termin", action: { type: "pick", pair, request: req } };
      }
      if (req?.status === "awaiting_dl" && canManageSlots) {
        return { stepKey: "choice", label: "Potwierdź", action: { type: "confirm", pair, request: req } };
      }
      return null;
    case "prep":
    case "prep2":
      return {
        stepKey: current.key,
        label: "Zaplanuj",
        action: { type: "plan_prep", pair, second: current.key === "prep2" },
      };
    case "call":
    case "debrief":
      return item.interview_event_id != null
        ? {
            stepKey: current.key,
            label: current.key === "call" ? "Zapisz debrief" : "Uzupełnij",
            action: { type: "debrief", pair, eventId: item.interview_event_id },
          }
        : null;
    default:
      return null;
  }
}
