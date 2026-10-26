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
/**
 * Dwa widoki ekranu: Tablica (domyślna — 7 kroków, kto na czym stoi, co
 * zrobić) i Tydzień (siatka). Zakładka „Agenda” zniknęła 24.09.2026 (decyzja
 * Artura) — jej zadania, kroki kandydata i linki Teams są w panelu karty.
 */
export type CycleView = "week" | "board";

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
  /** 0370: jakość odbytego prepu (ocena z transkryptu Teams). */
  quality?: PrepQuality | null;
}

export type PrepQuality = "good" | "ok" | "weak" | "unrecorded" | "pending";

export interface SlotItem {
  start: string;
  end: string | null;
  /** Okno klienta („piątek 9–12”, 20.10.2026): koniec okna; godzinę wybiera rekruter. */
  window_end?: string | null;
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
  /** 0487: rozmowa wpisana przy wyborze rekrutera — DL ma odpisać klientowi. */
  client_reply_pending?: boolean;
  client_replied_at?: string | null;
  /** Tylko w odpowiedzi na wybór z potwierdzeniem: blokada w Outlooku rekrutera. */
  outlook?: string | null;
  /** Tylko w odpowiedzi na utworzenie wniosku: karta pojechała na „Rozmowę u klienta”. */
  moved_to_client_interview?: boolean;
  /** Runda 10 (F09): dlaczego karta została (`cv_not_sent` — CV nie wysłane). */
  move_skipped_reason?: string | null;
}

/** Komunikat po zapisaniu terminów od klienta (runda 10, F09). */
export function slotsCreatedMessage(res: Pick<SlotRequest, "move_skipped_reason">): string {
  if (res.move_skipped_reason === "cv_not_sent") {
    return (
      "Terminy wysłane rekruterowi. Karta kandydata została na swoim etapie — " +
      "CV nie zostało jeszcze wysłane do klienta. Przesuń ją na tablicy rekrutacji " +
      "(QC CV → CV wysłane)."
    );
  }
  if (res.move_skipped_reason) {
    return (
      "Terminy wysłane rekruterowi. Karta kandydata została na swoim etapie — " +
      "przesunięcie wymaga decyzji na tablicy rekrutacji."
    );
  }
  return "Terminy wysłane rekruterowi — ustali termin z kandydatem.";
}

/** Stan blokady przełożonej rozmowy w Outlooku rekrutera (lustro
 *  `interview_slots._cancel_outlook_copy`, runda 7 audytu). */
export type SupersededOutlook = "none" | "cancelled" | "not_connected" | "failed";

/** Toast po potwierdzeniu terminu. Blokada, której nie udało się zdjąć z
 *  Outlooka, jest ostrzeżeniem — do rundy 7 okno mówiło „odwołany”, choć
 *  blokada zostawała w kalendarzu rekrutera. */
export function slotConfirmedMessage(res: {
  outlook?: string | null;
  cancelled_event_id?: number | null;
  superseded_outlook?: SupersededOutlook | string | null;
}): { tone: "success" | "error"; message: string } {
  const base =
    res.outlook === "added"
      ? "Termin potwierdzony — rozmowa jest w kalendarzu rekrutera i w jego Outlooku."
      : "Termin potwierdzony — rozmowa jest w kalendarzu rekrutera w NEXUSIE.";
  if (!res.cancelled_event_id) return { tone: "success", message: base };
  if (res.superseded_outlook === "failed" || res.superseded_outlook === "not_connected") {
    const why =
      res.superseded_outlook === "failed"
        ? "nie udało się jej usunąć z Outlooka rekrutera"
        : "skrzynka rekrutera nie jest połączona z NEXUSEM";
    return {
      tone: "error",
      message: `${base} Poprzedni termin odwołany w NEXUSIE, ale jego blokada została w Outlooku (${why}) — usuń ją ręcznie.`,
    };
  }
  return { tone: "success", message: `${base} Poprzedni termin odwołany.` };
}

export interface PairInfo {
  candidate_id: number;
  /** `null`, gdy rola nie czyta kandydatów — wtedy pokazujemy „Kandydat #id”. */
  candidate_name: string | null;
  /** Do zaproszenia na prep; `null` bez odczytu kandydatów. */
  candidate_email: string | null;
  /** Do umawiania terminów (nagłówek panelu); `null` bez odczytu kandydatów, brak = starszy serwer. */
  candidate_phone?: string | null;
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
  /**
   * Termin rozmowy, który czeka jeszcze na wybór albo potwierdzenie (wybrany
   * z kandydatem albo najwcześniejsza propozycja klienta). Okno „Zaplanuj
   * prep” liczy względem niego podpowiedź i ostrzeżenie.
   */
  tentative_interview_at?: string | null;
  interview_event_id: number | null;
  debrief: DebriefSummary | null;
  /** 0482: czy rozmowę da się zapisać jako „bez Prepu 2”; starszy serwer = brak. */
  prep2_skip_status?: Prep2SkipStatus;
  prep2_skip?: Prep2Skip | null;
  /** Punkty klienta, których Prep 1 nie omówił — do telefonu przed rozmową. */
  prep1_remaining?: string[];
}

/**
 * Rozmowa bez Prepu 2 (0482, decyzja Artura 20.10.2026) — wyjątek, nie wybór.
 * Lustro `prep2_skip_status` w `backend/app/services/interview_cycle.py`.
 */
export type Prep2SkipStatus =
  | "allowed"
  | "skipped"
  | "not_needed"
  | "prep1_missing"
  | "prep1_weak"
  | "too_early";

export type Prep2SkipReason = "no_slot" | "short_notice" | "prep1_covered" | "other";

export interface Prep2Skip {
  id: number;
  interview_event_id: number;
  reason: Prep2SkipReason;
  reason_note: string | null;
  /** Telefon do kandydata przed rozmową (zamiast Prepu 2). */
  call_at: string;
  call_done_at: string | null;
  call_note: string | null;
  created_by: number | null;
  created_by_name: string | null;
  created_at: string;
}

/** Wybór w oknie „Rozmowa bez Prepu 2”. */
export const PREP2_SKIP_REASON_OPTIONS: Record<Prep2SkipReason, string> = {
  no_slot: "Kandydat nie ma wolnego terminu przed rozmową",
  short_notice: "Klient wyznaczył rozmowę z dnia na dzień",
  prep1_covered: "Prep 1 był niedawno i omówił całą listę klienta",
  other: "Inny powód (opisz)",
};

/** Powód w zdaniu — lustro `PREP2_SKIP_REASON_LABELS` z serwera. */
export const PREP2_SKIP_REASON_LABELS: Record<Prep2SkipReason, string> = {
  no_slot: "kandydat nie miał wolnego terminu",
  short_notice: "rozmowa umówiona z dnia na dzień",
  prep1_covered: "Prep 1 omówił całą listę klienta",
  other: "inny powód",
};

export function prep2SkipReasonText(skip: Pick<Prep2Skip, "reason" | "reason_note">): string {
  if (skip.reason === "other" && skip.reason_note) return skip.reason_note;
  return PREP2_SKIP_REASON_LABELS[skip.reason] ?? skip.reason;
}

/** Podpowiedź pod krokiem Prep 2 — dlaczego przycisk jest albo go nie ma. */
export function prep2SkipHint(status: Prep2SkipStatus | undefined): string | null {
  switch (status) {
    case "allowed":
      return "Do rozmowy został mniej niż dzień roboczy. Jeśli kandydat nie znajdzie czasu na Prep 2, zapisz powód i zadzwoń do niego przed rozmową.";
    case "too_early":
      return "Do rozmowy jest więcej niż dzień roboczy — jest czas na Prep 2.";
    case "prep1_weak":
      return "Prep 1 był słaby albo bez nagrania — przed tą rozmową Prep 2 jest obowiązkowy.";
    default:
      return null;
  }
}

/**
 * Podpowiedź terminu telefonu przed rozmową (pole `datetime-local`): za godzinę,
 * a gdy rozmowa jest bliżej — najbliższy kwadrans, zawsze przed rozmową.
 */
export function defaultPrecallAt(interviewAt: string | null, now: Date = new Date()): string {
  const quarter = (d: Date) => {
    const out = new Date(d);
    const rest = out.getMinutes() % 15;
    if (rest || out.getSeconds() || out.getMilliseconds()) {
      out.setMinutes(out.getMinutes() + (15 - rest), 0, 0);
    }
    return out;
  };
  let at = quarter(new Date(now.getTime() + 60 * 60_000));
  if (interviewAt) {
    const latest = new Date(new Date(interviewAt).getTime() - 15 * 60_000);
    if (at > latest) at = quarter(now) <= latest ? quarter(now) : now;
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

/**
 * Skrót zapisanego debriefu (ekran „Rozmowy u klienta” i odznaka karty na
 * Tablicy). Do 04.10.2026 zapisany debrief nie był nigdzie widoczny — warunek
 * kandydata („chce jednak 125 zł/h”) czytał tylko Jarvis.
 */
export interface DebriefSummary {
  id: number;
  overall_impression: number | null;
  outcome?: DebriefOutcome | null;
  offer_acceptance: OfferAcceptance | null;
  acceptance_condition: string | null;
  candidate_comment?: string | null;
  questions_count?: number;
  no_client_questions?: boolean;
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
  /** 0370: prep założony z NEXUSA (Teams) — ma transkrypt i ocenę. */
  from_nexus?: boolean;
  prep_quality?: PrepQuality | null;
  prep_meta?: string | null;
  /** Prep zaplanowany po rozmowie u klienta, do której miał przygotować. */
  late?: boolean;
  /** Wydarzenie moje albo osoby, którą zastępuję — z tego okienko „Rozmowy” liczy „Teraz”. */
  mine?: boolean;
}

export type TodoKind =
  | "call_now"
  | "debrief_overdue"
  /** Para w „Rozmowie z klientem” bez terminu w NEXUSIE i bez pytań (20.10.2026). */
  | "questions_missing"
  | "slots_pick"
  | "slots_confirm"
  /** 0487: rozmowa już w kalendarzu z wyboru rekrutera — DL odpisuje klientowi. */
  | "slots_reply"
  | "prep_missing"
  | "prep2_missing"
  | "prep_late"
  | "prep_weak"
  | "prep_unrecorded"
  | "slots_missing"
  /** 0482: rozmowa bez Prepu 2 — telefon do kandydata przed rozmową. */
  | "precall_due";

export interface TodoEntry extends PairInfo {
  kind: TodoKind;
  priority: number;
  due: string | null;
  event_id: number | null;
  slot_request_id: number | null;
  /** Brak prepu na dobę przed rozmową u klienta. */
  urgent?: boolean;
  /** Zadanie czeka na mnie; ekran pokazuje wszystkie z zakresu, okienko „Rozmowy” tylko te. */
  mine?: boolean;
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
  /** 0418: bieżąca stawka kandydata w tej rekrutacji („Bez zmian (110 zł/h)”). */
  current_rate_label?: string | null;
  current_rate_hourly?: string | number | null;
  /** 0418: zmiana stawki zapisana tym debriefem. */
  rate_change?: {
    id: number;
    status: string;
    requires_decision: boolean;
    previous: string | null;
    requested: string;
    requested_amount: string;
    requested_unit: string;
    negotiable: "no" | "maybe" | "unknown" | null;
    note: string | null;
  } | null;
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
  /** 0418: kandydat podał inną stawkę (brak = bez zmian). */
  rate_change?: {
    amount: string;
    unit?: "hourly" | "daily" | "monthly";
    negotiable?: "no" | "maybe" | "unknown" | null;
    note?: string | null;
  } | null;
}

/**
 * Pytania z rozmowy bez wskazania wydarzenia (20.10.2026): bez rozmowy
 * w kalendarzu serwer zakłada odbytą z `held_on` (dzień, `YYYY-MM-DD`)
 * i opcjonalną godziną `held_at` (`HH:MM`, czas firmy).
 */
export interface PairDebriefInput extends DebriefInput {
  held_on?: string | null;
  held_at?: string | null;
}

// ── Pytania klienta w debriefie ───────────────────────────────────────────────

/** Lustro ``api.interview_cycle.MAX_DEBRIEF_QUESTIONS`` (decyzja 04.10.2026). */
export const MAX_DEBRIEF_QUESTIONS = 30;

const QUESTION_PREFIX = /^\s*(?:\d+\s*[.)]|[-–—•*·])\s*/;

/**
 * Wklejona lista pytań → osobne pytania. Rekruterzy wklejają notatki z rozmowy
 * („1. …”, „- …”, „• …”), a do 04.10.2026 cała lista lądowała w jednym polu.
 */
export function splitPastedQuestions(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.replace(QUESTION_PREFIX, "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

/**
 * Dokleja pytania do listy: pomija powtórzenia (bez wielkości liter i białych
 * znaków — jak serwer) i przycina do limitu. ``dropped`` = ile nie weszło
 * z powodu limitu.
 */
export function mergeQuestions(
  current: string[],
  added: string[],
  max: number = MAX_DEBRIEF_QUESTIONS,
): { questions: string[]; dropped: number } {
  const key = (q: string) => q.replace(/\s+/g, " ").trim().toLowerCase();
  const seen = new Set<string>();
  const out: string[] = [];
  let dropped = 0;
  for (const raw of [...current, ...added]) {
    const text = raw.replace(/\s+/g, " ").trim();
    if (!text || seen.has(key(text))) continue;
    if (out.length >= max) {
      dropped += 1;
      continue;
    }
    seen.add(key(text));
    out.push(text);
  }
  return { questions: out, dropped };
}

/** Jedno zdanie o zapisanym debriefie: „dobrze · raczej przyjmie · 4 pytania klienta”. */
export function debriefSummaryLine(d: DebriefSummary): string {
  const parts: string[] = [];
  if (d.outcome) parts.push(OUTCOME_LABELS[d.outcome].toLowerCase());
  if (d.offer_acceptance) parts.push(OFFER_SHORT[d.offer_acceptance]);
  const count = d.questions_count ?? 0;
  if (count > 0) parts.push(questionsCountLabel(count));
  else if (d.no_client_questions) parts.push("klient nie zadawał pytań");
  return parts.join(" · ");
}

const OFFER_SHORT: Record<OfferAcceptance, string> = {
  yes: "przyjmie ofertę",
  likely: "raczej przyjmie",
  no: "nie przyjmie",
  unknown: "nie wiadomo, czy przyjmie",
};

export function questionsCountLabel(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  const word =
    count === 1
      ? "pytanie"
      : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)
        ? "pytania"
        : "pytań";
  return `${count} ${word} klienta`;
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
  call: "Telefon po rozmowie",
  debrief: "Debrief",
};

/** Kto wykonuje krok — nagłówek kolumny na tablicy. */
export const STEP_OWNER: Record<StepKey, string> = {
  slots: "DL wpisuje terminy",
  choice: "rekruter ↔ kandydat",
  prep: "prowadzi DL",
  prep2: "prowadzi rekruter",
  interview: "kandydat u klienta",
  call: "rekruter dzwoni do 30 min po",
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
  questions_missing: "Uzupełnij pytania z rozmowy u klienta",
  slots_pick: "Terminy czekają na kandydata",
  slots_confirm: "Potwierdź termin u klienta",
  slots_reply: "Odpisz klientowi",
  prep_missing: "Prep 1 bez terminu",
  prep2_missing: "Prep 2 bez terminu",
  prep_late: "Prep po rozmowie u klienta — przełóż",
  prep_weak: "Prep słaby — popraw przed rozmową",
  prep_unrecorded: "Prep bez nagrania",
  slots_missing: "Brak terminów od klienta",
  precall_due: "Telefon przed rozmową (bez Prepu 2)",
};

export const TODO_ACTIONS: Record<TodoKind, string> = {
  call_now: "Zapisz debrief",
  debrief_overdue: "Uzupełnij",
  questions_missing: "Uzupełnij",
  slots_pick: "Wybierz termin",
  slots_confirm: "Potwierdź",
  slots_reply: "Odpisz",
  prep_missing: "Zaplanuj Prep 1",
  prep2_missing: "Zaplanuj Prep 2",
  prep_late: "Przełóż",
  prep_weak: "Zobacz ocenę",
  prep_unrecorded: "Szczegóły",
  slots_missing: "Dodaj terminy",
  precall_due: "Zrobione",
};

export const PREP_QUALITY_LABELS: Record<PrepQuality, string> = {
  good: "Prep dobry",
  ok: "Prep OK",
  weak: "Prep słaby",
  unrecorded: "Bez nagrania",
  pending: "Czeka na transkrypt",
};

/** Jakość prepu → wariant plakietki (tokeny). */
export function prepQualityTone(quality: PrepQuality): "done" | "warn" | "danger" | "muted" {
  switch (quality) {
    case "good":
      return "done";
    case "ok":
      return "muted";
    case "weak":
      return "danger";
    case "unrecorded":
      return "warn";
    default:
      return "muted";
  }
}

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
  eventId: number | null,
): string | undefined {
  if (!data || eventId == null) return undefined;
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
  // `?view=agenda` żyje w zapisanych powiadomieniach (interview_slots.py do
  // 24.09.2026) — prowadzi teraz na Tablicę, tak jak brak parametru.
  return raw === "week" ? "week" : "board";
}

/** Trzy grupy kroków nad kolumnami Tablicy (kolor = faza, nie stan). */
export const STEP_GROUPS: ReadonlyArray<{
  key: "arrange" | "prepare" | "interview";
  label: string;
  steps: StepKey[];
}> = [
  { key: "arrange", label: "Umawianie · DL i klient", steps: ["slots", "choice"] },
  { key: "prepare", label: "Przygotowanie", steps: ["prep", "prep2"] },
  { key: "interview", label: "Rozmowa i po rozmowie", steps: ["interview", "call", "debrief"] },
];

/** Zadania „Do zrobienia” per para, od najpilniejszego (priorytet serwera). */
export function todosByPair(todos: readonly TodoEntry[]): Map<string, TodoEntry[]> {
  const map = new Map<string, TodoEntry[]>();
  for (const t of todos) {
    const key = pairKey(t);
    const list = map.get(key);
    if (list) list.push(t);
    else map.set(key, [t]);
  }
  for (const list of map.values()) list.sort((a, b) => a.priority - b.priority);
  return map;
}

/** Wydarzenia agendy jednej pary od dziś w przód (+ niezamknięty telefon). */
export function pairAgenda(
  agenda: readonly AgendaEntry[],
  key: string,
  now: Date = new Date(),
): AgendaEntry[] {
  return upcomingAgenda(
    agenda.filter((e) => pairKey(e) === key),
    now,
  ).sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime());
}

export function parseScope(raw: string | null, fallback: CycleScope): CycleScope {
  return raw === "mine" || raw === "jobs" || raw === "all" ? raw : fallback;
}

// ── Akcje ─────────────────────────────────────────────────────────────────────

export type CycleAction =
  /** `eventId = null` — rozmowy nie ma w kalendarzu; okno pyta, kiedy była. */
  | { type: "debrief"; pair: PairInfo; eventId: number | null }
  | { type: "pick"; pair: PairInfo; request: SlotRequest }
  | { type: "confirm"; pair: PairInfo; request: SlotRequest }
  /** 0487: odpowiedź do klienta po wyborze rekrutera (rozmowa już w kalendarzu). */
  | { type: "reply"; pair: PairInfo; request: SlotRequest }
  | { type: "plan_prep"; pair: PairInfo; second: boolean }
  | { type: "prep_review"; pair: PairInfo; eventId: number; tab?: "score" | "summary" | "transcript" }
  | { type: "add_slots"; pair: PairInfo | null }
  /** Prep zaplanowany po rozmowie u klienta: nowy termin TEGO spotkania. */
  | {
      type: "reschedule_prep";
      pair: PairInfo;
      eventId: number;
      prepNo: 1 | 2;
      /** Brak = „late” (prep po rozmowie u klienta); „edit”/„cancel” z wiersza prepu (17.10.2026). */
      mode?: "late" | "edit" | "cancel";
    }
  | { type: "open_event"; eventId: number }
  /** 0482: telefon przed rozmową bez Prepu 2 odbyty. */
  | { type: "precall_done"; pair: PairInfo; skip: Prep2Skip };

function pairOf(p: PairInfo): PairInfo {
  return {
    candidate_id: p.candidate_id,
    candidate_name: p.candidate_name,
    candidate_email: p.candidate_email,
    candidate_phone: p.candidate_phone,
    job_id: p.job_id,
    job_title: p.job_title,
    client_id: p.client_id,
    client_name: p.client_name,
  };
}

/**
 * Przycisk z maila (26.10.2026): `?cycle=<para>&do=<krok>` otwiera okno
 * bieżącego kroku pary — tylko gdy para naprawdę na nim stoi. Okno jest
 * potwierdzeniem; sam link niczego nie zapisuje (Safe Links w M365 otwiera
 * linki z maila, zanim zrobi to człowiek). `null` = krok już zrobiony albo
 * czeka na kogoś innego — ekran pokazuje wtedy samą parę.
 */
export function linkedStepAction(
  item: CycleItem,
  step: string | null,
  { canManageSlots }: { canManageSlots: boolean },
): CycleAction | null {
  if (!step) return null;
  const current = actionForItem(item, { canManageSlots });
  return current?.action.type === step ? current.action : null;
}

/**
 * `?choose=N` (od 1) → indeks terminu z wniosku albo `null`, gdy nie ma takiego.
 * `?req=<id>` to wniosek, z którego mail wziął terminy: przy innym (klient
 * przysłał nowe terminy po mailu) „termin N” znaczyłby inną godzinę — bez zaznaczenia.
 */
export function chosenSlotIndex(
  raw: string | null,
  request: SlotRequest | null,
  requestParam: string | null = null,
): number | null {
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 1 || !request || n > request.slots.length) return null;
  if (requestParam != null && Number(requestParam) !== request.id) return null;
  return n - 1;
}

/** Pozycja „Do zrobienia” → akcja przycisku. `null` = pozycja tylko informuje. */
export function actionForTodo(todo: TodoEntry, items: CycleItem[]): CycleAction | null {
  const pair = pairOf(todo);
  const item = items.find((i) => i.candidate_id === todo.candidate_id && i.job_id === todo.job_id);
  switch (todo.kind) {
    case "call_now":
    case "debrief_overdue":
      return todo.event_id != null ? { type: "debrief", pair, eventId: todo.event_id } : null;
    case "questions_missing":
      return { type: "debrief", pair, eventId: null };
    case "slots_pick":
      return item?.slot_request ? { type: "pick", pair, request: item.slot_request } : null;
    case "slots_confirm":
      return item?.slot_request ? { type: "confirm", pair, request: item.slot_request } : null;
    case "slots_reply":
      return item?.slot_request ? { type: "reply", pair, request: item.slot_request } : null;
    case "prep_missing":
      return { type: "plan_prep", pair, second: false };
    case "prep2_missing":
      return { type: "plan_prep", pair, second: true };
    case "prep_late": {
      // Prep już jest w kalendarzu organizatora i kandydata — przekładamy go,
      // nie zakładamy drugiego. Do 04.10.2026 przycisk prowadził na widok
      // Tydzień, a klik w siatkę otwierał tam „Nowe wydarzenie”.
      if (todo.event_id == null) return null;
      const step = item?.steps.find((s) => s.event_id === todo.event_id);
      return {
        type: "reschedule_prep",
        pair,
        eventId: todo.event_id,
        prepNo: step?.key === "prep2" ? 2 : 1,
      };
    }
    case "prep_weak":
    case "prep_unrecorded":
      return todo.event_id != null ? { type: "prep_review", pair, eventId: todo.event_id } : null;
    case "slots_missing":
      return { type: "add_slots", pair };
    case "precall_due":
      return item?.prep2_skip ? { type: "precall_done", pair, skip: item.prep2_skip } : null;
    default:
      return null;
  }
}

/**
 * Akcja kroku bieżącego pary (przycisk w stepperze i na karcie tablicy).
 * `canManageSlots` = rola DL/nadzór — tylko ona dodaje i potwierdza terminy.
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
      // „Po terminie” z wydarzeniem = prep zaplanowany po rozmowie u klienta.
      if (current.state === "overdue" && current.event_id != null) {
        return {
          stepKey: current.key,
          label: "Przełóż",
          action: {
            type: "reschedule_prep",
            pair,
            eventId: current.event_id,
            prepNo: current.key === "prep2" ? 2 : 1,
          },
        };
      }
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
