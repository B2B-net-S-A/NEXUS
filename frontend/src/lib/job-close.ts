/**
 * Ostrzeżenie `POST /api/jobs/{id}/close` o osobach w toku (13.10.2026).
 *
 * Zamknięcie nie rusza kart: osoby w toku zostają w zamkniętej rekrutacji.
 * Serwer odpowiada 409 `active_cards_warning` z liczbami per kolumna Tablicy,
 * a okno zamykania pokazuje je i wysyła zamknięcie z potwierdzeniem.
 *
 * Od 28.10.2026 odpowiedź niesie też `recipients`: rekruterów osób od „CV
 * wysłane” w górę, którzy po zamknięciu dostaną dzwonek i mail
 * (`services/job_closed_notices.py`).
 */
import { BOARD_COLUMN_LABEL, BOARD_COLUMN_ORDER } from "@/lib/board-stages";

export interface ActiveCardsRecipient {
  userId: number;
  name: string;
  /** Ile osób tego rekrutera czeka. */
  people: number;
  /** „CV wysłane 2 · Rozmowa u klienta 1”. */
  breakdown: string;
}

export interface ActiveCardsWarning {
  /** Zdanie z serwera: ile osób i kiedy był ostatni ruch karty. */
  message: string;
  /** „Nowi 3 · Screening 2” — w kolejności kolumn Tablicy. */
  breakdown: string;
  /** Kto dostanie wiadomość po zamknięciu (bez osoby, która zamyka). */
  recipients: ActiveCardsRecipient[];
}

function columnsBreakdown(columns: unknown): string {
  const counts = (columns && typeof columns === "object" ? columns : {}) as Record<string, unknown>;
  return BOARD_COLUMN_ORDER.filter((key) => Number(counts[key]) > 0)
    .map((key) => `${BOARD_COLUMN_LABEL[key]} ${Number(counts[key])}`)
    .join(" · ");
}

function recipientsFrom(raw: unknown): ActiveCardsRecipient[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const { user_id, name, people, columns } = item as Record<string, unknown>;
    if (typeof user_id !== "number" || typeof name !== "string") return [];
    return [
      {
        userId: user_id,
        name,
        people: Number(people) || 0,
        breakdown: columnsBreakdown(columns),
      },
    ];
  });
}

export function activeCardsWarningFrom(error: unknown): ActiveCardsWarning | null {
  const detail = (error as { response?: { data?: { detail?: unknown } } } | null)?.response?.data
    ?.detail;
  if (!detail || typeof detail !== "object") return null;
  const { code, message, columns, recipients } = detail as {
    code?: unknown;
    message?: unknown;
    columns?: unknown;
    recipients?: unknown;
  };
  if (code !== "active_cards_warning") return null;
  return {
    message: typeof message === "string" ? message : "W tej rekrutacji są osoby w toku.",
    breakdown: columnsBreakdown(columns),
    recipients: recipientsFrom(recipients),
  };
}

/** „1 osobę”, „3 osoby”, „5 osób”, „12 osób”, „22 osoby”. */
export function peopleAccusative(count: number): string {
  if (count === 1) return "1 osobę";
  const lastTwo = count % 100;
  if (count % 10 >= 2 && count % 10 <= 4 && (lastTwo < 12 || lastTwo > 14)) {
    return `${count} osoby`;
  }
  return `${count} osób`;
}

/**
 * Napis przycisku po ostrzeżeniu: mówi, że zamknięcie powiadomi rekruterów,
 * albo — gdy nie ma kogo — że zamyka mimo osób w toku.
 */
export function closeAnywayLabel(warning: ActiveCardsWarning, base = "Zamknij"): string {
  const count = warning.recipients.length;
  return count > 0 ? `${base} i powiadom ${peopleAccusative(count)}` : `${base} mimo to`;
}
