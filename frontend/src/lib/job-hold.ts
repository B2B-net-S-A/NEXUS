/**
 * Rekrutacja „Wstrzymana” (`on_hold`, decyzje Artura 26.11.2026) — czyste
 * reguły i typy. Lustro tras `backend/app/api/job_hold.py`:
 * `GET/PUT/DELETE /api/jobs/{id}/hold`, `POST …/hold/report`,
 * `GET /api/hold-checks`, `POST /api/jobs/{id}/hold-check`.
 *
 * Zgłoszenie z 26.11: rekruterka zaproponowała kandydatowi projekt i zrobiła
 * weryfikację, a dopiero potem DL powiedział, że klient go wstrzymał. Stąd
 * pas nad Tablicą, ostrzeżenie przy ruchu karty (ostrzega, nie blokuje)
 * i pytanie do DL „Czy te rekrutacje nadal trwają?”.
 */

import { formatDayMonthPl } from "@/lib/date-pl";
import { shortenPersonName } from "@/lib/job-header-subtitle";
import type { PipelineMovePayload } from "@/lib/pipeline-move-core";
import type { PriorityLevel } from "@/lib/request-priority";
import { STATE_LABEL, type VisibleState } from "@/lib/request-work-state";

/** Rekruter, który dostanie wiadomość przy wstrzymaniu (albo wznowieniu). */
export interface HoldRecipient {
  user_id: number;
  name: string;
  /** Ile osób ma w toku w tej rekrutacji. */
  people: number;
}

/** Odpowiedź `GET/PUT/DELETE /api/jobs/{id}/hold`. */
export interface JobHold {
  job_id: number;
  /** Widoczny stan pracy; `on_hold` = wstrzymana. */
  state: VisibleState | string;
  reason: string | null;
  /** „Sprawdzę z klientem” — data kalendarza firmy `RRRR-MM-DD`. */
  review_on: string | null;
  since: string | null;
  by_id: number | null;
  by_name: string | null;
  /** Patrzący może wstrzymać i wznowić (DL rekrutacji, HoR, admin). */
  can_manage: boolean;
  recipients: HoldRecipient[];
  /** Moje nieodpowiedziane zgłoszenie „klient wstrzymał?”. */
  my_open_report: { at: string; note: string } | null;
}

export type HoldSignalKind = "report" | "note" | "parked_still_working" | "dl_silent";

export interface HoldSignal {
  kind: HoldSignalKind;
  at: string | null;
  by_name?: string | null;
  text: string;
}

/** Wiersz `GET /api/hold-checks`. */
export interface HoldCheckItem {
  job_id: number;
  title: string;
  client_name: string | null;
  reference: string | null;
  priority: PriorityLevel | string | null;
  work_state: string;
  recruiter_moves_7d: number;
  recruiters_7d: number;
  signals: HoldSignal[];
}

export interface HoldChecksResponse {
  items: HoldCheckItem[];
  total: number;
}

/** Ciało `PUT /api/jobs/{id}/hold`. */
export interface HoldPayload {
  reason: string;
  review_on: string | null;
  notify: boolean;
}

export const HOLD_STATE = "on_hold";

function text(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

/**
 * Odpowiedź `GET/PUT/DELETE …/hold` na granicy: brakujące listy i pola
 * dostają bezpieczne wartości, a obcy kształt nie udaje wstrzymania.
 */
export function normalizeJobHold(raw: unknown, jobId: number): JobHold {
  const data = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const recipients = Array.isArray(data.recipients)
    ? data.recipients.filter(
        (r): r is HoldRecipient =>
          !!r && typeof r === "object" && typeof (r as HoldRecipient).user_id === "number",
      )
    : [];
  const report = data.my_open_report as { at?: unknown; note?: unknown } | null | undefined;
  return {
    job_id: typeof data.job_id === "number" ? data.job_id : jobId,
    state: typeof data.state === "string" ? data.state : "searching",
    reason: text(data.reason),
    review_on: text(data.review_on),
    since: text(data.since),
    by_id: typeof data.by_id === "number" ? data.by_id : null,
    by_name: text(data.by_name),
    can_manage: data.can_manage === true,
    recipients,
    my_open_report:
      report && typeof report === "object" && typeof report.at === "string"
        ? { at: report.at, note: typeof report.note === "string" ? report.note : "" }
        : null,
  };
}

/** Gotowe powody z makiety; „Inny…” otwiera pole tekstowe. */
export const HOLD_REASON_PRESETS = [
  "Klient wstrzymał budżet",
  "Zmiana zakresu",
  "Czeka na decyzję klienta",
] as const;

export const HOLD_REASON_MAX = 500;
export const HOLD_NOTE_MAX = 500;
/** „Sprawdzę z klientem” domyślnie za dwa tygodnie. */
export const HOLD_REVIEW_DEFAULT_DAYS = 14;
/** Serwer odmawia terminu dalszego niż 120 dni (422). */
export const HOLD_REVIEW_MAX_DAYS = 120;

export function isOnHold(state: unknown): boolean {
  return state === HOLD_STATE;
}

/** Data `RRRR-MM-DD` przesunięta o `days` dni kalendarza (bez strefy czasu). */
export function addDaysIso(iso: string, days: number): string {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day + days));
  return date.toISOString().slice(0, 10);
}

/** Dni kalendarza od `from` do `to` (obie `RRRR-MM-DD`). */
export function daysBetweenIso(from: string, to: string): number {
  return Math.round(
    (Date.parse(`${to.slice(0, 10)}T00:00:00Z`) - Date.parse(`${from.slice(0, 10)}T00:00:00Z`)) /
      86_400_000,
  );
}

export function defaultReviewOn(today: string): string {
  return addDaysIso(today, HOLD_REVIEW_DEFAULT_DAYS);
}

/** „(+2 tyg.)”, „(+10 dni)”, „(jutro)” — podpowiedź obok daty. */
export function reviewDistanceText(today: string, reviewOn: string): string | null {
  const days = daysBetweenIso(today, reviewOn);
  if (!Number.isFinite(days) || days < 0) return null;
  if (days === 0) return "dziś";
  if (days === 1) return "jutro";
  if (days % 7 === 0) return `+${days / 7} tyg.`;
  return `+${days} dni`;
}

export interface HoldFormErrors {
  reason?: string;
  reviewOn?: string;
}

/**
 * Walidacja okna „Wstrzymaj rekrutację” — ta sama granica co serwer:
 * powód 1–500 znaków po przycięciu, termin od dziś do 120 dni albo pusty.
 */
export function validateHoldForm(
  form: { reason: string; reviewOn: string | null },
  today: string,
): HoldFormErrors {
  const errors: HoldFormErrors = {};
  const reason = form.reason.trim();
  if (reason.length === 0) errors.reason = "Wybierz albo wpisz powód wstrzymania.";
  else if (reason.length > HOLD_REASON_MAX)
    errors.reason = `Powód może mieć najwyżej ${HOLD_REASON_MAX} znaków.`;
  const reviewOn = form.reviewOn?.trim() ?? "";
  if (reviewOn) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(reviewOn)) errors.reviewOn = "Podaj datę.";
    else if (reviewOn < today) errors.reviewOn = "Termin sprawdzenia nie może być w przeszłości.";
    else if (reviewOn > addDaysIso(today, HOLD_REVIEW_MAX_DAYS))
      errors.reviewOn = `Termin sprawdzenia najwyżej ${HOLD_REVIEW_MAX_DAYS} dni od dziś.`;
  }
  return errors;
}

export function hasHoldFormErrors(errors: HoldFormErrors): boolean {
  return Boolean(errors.reason || errors.reviewOn);
}

/** „Anna K.” z pełnego imienia i nazwiska. */
export function shortName(name: string | null | undefined): string | null {
  if (!name) return null;
  return shortenPersonName(name) ?? name;
}

/**
 * Co pokazują pas, dymek i ostrzeżenie: z `GET …/hold`, a do jego odpowiedzi
 * z pól rekrutacji (`hold_reason`, `hold_since`, `hold_by_name`,
 * `hold_review_on`) — pas stoi od pierwszego renderu.
 */
export interface HoldView {
  reason: string | null;
  since: string | null;
  byName: string | null;
  reviewOn: string | null;
}

export function holdViewOf(
  hold: Pick<JobHold, "state" | "reason" | "since" | "by_name" | "review_on"> | null | undefined,
  job?: {
    work_state?: unknown;
    hold_reason?: unknown;
    hold_since?: unknown;
    hold_by_name?: unknown;
    hold_review_on?: unknown;
  } | null,
): HoldView | null {
  if (hold) {
    if (!isOnHold(hold.state)) return null;
    return {
      reason: hold.reason,
      since: hold.since,
      byName: hold.by_name,
      reviewOn: hold.review_on,
    };
  }
  if (!job || !isOnHold(job.work_state)) return null;
  return {
    reason: text(job.hold_reason),
    since: text(job.hold_since),
    byName: text(job.hold_by_name),
    reviewOn: text(job.hold_review_on),
  };
}

/** „od 26.11 · ustawił(a) Jan N.” — nagłówek pasa i dymka. */
export function holdSinceText(view: HoldView): string {
  const parts: string[] = [];
  if (view.since) parts.push(`od ${formatDayMonthPl(view.since)}`);
  const by = shortName(view.byName);
  if (by) parts.push(`ustawił(a) ${by}`);
  return parts.join(" · ");
}

/** „DL sprawdzi z klientem 08.12.” albo nic. */
export function holdReviewText(view: HoldView): string | null {
  return view.reviewOn ? `DL sprawdzi z klientem ${formatDayMonthPl(view.reviewOn)}.` : null;
}

/**
 * Ruch karty, o który ostrzeżenie NIE pyta: odrzucenie i rezygnacja
 * (zamknięcie karty) w wstrzymanej rekrutacji są w porządku — to właśnie
 * porządkowanie listy.
 */
export function isHoldExemptMove(
  payload: Pick<
    PipelineMovePayload,
    "stage" | "rejection_reason_id" | "rejection_reason" | "ended_by"
  >,
): boolean {
  if (payload.stage === "rejected" || payload.stage === "withdrawn") return true;
  return Boolean(payload.rejection_reason_id || payload.rejection_reason || payload.ended_by);
}

/** Treść okna „Ta rekrutacja jest wstrzymana” przy ruchu karty. */
export function holdMoveWarning(
  view: HoldView,
  move: { candidateName?: string | null; targetLabel?: string | null; count?: number },
): { title: string; description: string } {
  const who =
    move.count && move.count > 1
      ? `${move.count} osoby`
      : (shortName(move.candidateName) ?? "tę osobę");
  const target = move.targetLabel ? ` do „${move.targetLabel}”` : "";
  const since = view.since ? ` ${formatDayMonthPl(view.since)}` : "";
  const by = shortName(view.byName);
  const reason = view.reason ? `: „${view.reason}”` : "";
  const review = view.reviewOn ? ` DL sprawdzi z klientem ${formatDayMonthPl(view.reviewOn)}.` : "";
  return {
    title: "Ta rekrutacja jest wstrzymana",
    description:
      `Chcesz przesunąć ${who}${target}. Klient wstrzymał rekrutację${since}` +
      `${by ? ` (ustawił(a) ${by})` : ""}${reason}. ` +
      `Jeśli zadzwonisz teraz, kandydat usłyszy o projekcie, którego na razie nie ma.${review}`,
  };
}

/** Jedno zdanie sygnału w panelu „Czy te rekrutacje nadal trwają?”. */
export function holdSignalText(signal: HoldSignal): string {
  if (signal.kind === "report") {
    const who = shortName(signal.by_name) ?? "Rekruter";
    const when = signal.at ? ` (${formatDayMonthPl(signal.at)})` : "";
    return signal.text ? `${who} pyta${when}: „${signal.text}”` : `${who} pyta${when}, czy klient wstrzymał`;
  }
  return signal.text;
}

export function recruiterMovesText(item: Pick<HoldCheckItem, "recruiter_moves_7d" | "recruiters_7d">): string | null {
  if (!item.recruiter_moves_7d) return null;
  const people = item.recruiters_7d === 1 ? "1 rekrutera" : `${item.recruiters_7d} rekruterów`;
  return `${item.recruiter_moves_7d} ruchów ${people} w 7 dni`;
}

export function stateLabelOf(state: unknown): string {
  return typeof state === "string" && state in STATE_LABEL
    ? STATE_LABEL[state as VisibleState]
    : "Szukamy kandydatów";
}
