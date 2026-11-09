/**
 * Osoby zalogowanego rekrutera, które czekają w zamkniętej rekrutacji
 * (28.10.2026). Lustro `services/job_closed_notices.py`: te same kolumny
 * Tablicy („CV wysłane”, „Rozmowa u klienta”, „Akceptacja i umowa”) i ta
 * sama osoba karty — przypisana „Prowadzi”, potem pierwszy weryfikujący,
 * potem ta, która dodała. Dlatego nie filtr „Kto dodał” (ten nie liczy
 * weryfikującego). Po ponownym otwarciu (05.11.2026) — tylko karty ruszone
 * od otwarcia, jak `waiting_cards(since=…)` na serwerze.
 */
import { placeStage, type BoardColumnKey, type StageLike } from "@/lib/board-stages";

export const WAITING_COLUMNS: readonly BoardColumnKey[] = ["cv_sent", "client_interview", "contract"];

export interface WaitingItem {
  candidate_id: number;
  owner_user_id?: number | null;
  verified_by_id?: number | null;
  added_to_job_by_id?: number | null;
  moved_at?: string | null;
}

export interface WaitingColumn<T extends WaitingItem> extends StageLike {
  items: readonly T[];
}

export function cardPersonId(item: WaitingItem): number | null {
  return item.owner_user_id ?? item.verified_by_id ?? item.added_to_job_by_id ?? null;
}

export function myWaitingItems<T extends WaitingItem>(
  columns: readonly WaitingColumn<T>[],
  userId: number | null | undefined,
  openingStartedAt: string | null = null,
): T[] {
  if (userId == null) return [];
  const since = openingStartedAt ? new Date(openingStartedAt).getTime() : null;
  const inOpening = (item: T) =>
    since == null || !item.moved_at || new Date(item.moved_at).getTime() >= since;
  return columns
    .filter((col) => WAITING_COLUMNS.includes(placeStage(col).column))
    .flatMap((col) => col.items.filter((item) => cardPersonId(item) === userId && inOpening(item)));
}

const DAY_MONTH = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  timeZone: "Europe/Warsaw",
});

/** „19.10” z `closed_at` (kalendarz firmy), `null` bez daty. */
export function closedOnLabel(closedAt: string | null | undefined): string | null {
  if (!closedAt) return null;
  const date = new Date(closedAt);
  return Number.isNaN(date.getTime()) ? null : DAY_MONTH.format(date);
}
