/**
 * Ostrzeżenie `POST /api/jobs/{id}/close` o osobach w toku (13.10.2026).
 *
 * Zamknięcie nie rusza kart: osoby w toku zostają w zamkniętej rekrutacji.
 * Serwer odpowiada 409 `active_cards_warning` z liczbami per kolumna Tablicy,
 * a okno zamykania pokazuje je i wysyła zamknięcie z potwierdzeniem.
 */
import { BOARD_COLUMN_LABEL, BOARD_COLUMN_ORDER } from "@/lib/board-stages";

export interface ActiveCardsWarning {
  /** Zdanie z serwera: ile osób i kiedy był ostatni ruch karty. */
  message: string;
  /** „Nowi 3 · Screening 2” — w kolejności kolumn Tablicy. */
  breakdown: string;
}

export function activeCardsWarningFrom(error: unknown): ActiveCardsWarning | null {
  const detail = (error as { response?: { data?: { detail?: unknown } } } | null)?.response?.data
    ?.detail;
  if (!detail || typeof detail !== "object") return null;
  const { code, message, columns } = detail as {
    code?: unknown;
    message?: unknown;
    columns?: unknown;
  };
  if (code !== "active_cards_warning") return null;
  const counts = (columns && typeof columns === "object" ? columns : {}) as Record<string, unknown>;
  const breakdown = BOARD_COLUMN_ORDER.filter((key) => Number(counts[key]) > 0)
    .map((key) => `${BOARD_COLUMN_LABEL[key]} ${Number(counts[key])}`)
    .join(" · ");
  return {
    message: typeof message === "string" ? message : "W tej rekrutacji są osoby w toku.",
    breakdown,
  };
}
