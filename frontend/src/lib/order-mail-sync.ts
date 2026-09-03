/**
 * „Pobierz zamówienia z maila" — czekanie na wynik biegu i tekst wyniku.
 *
 * Bieg idzie w tle po stronie serwera, a przeglądarka odpytuje
 * `GET /api/order-mail/sync/status`. Koniec biegu poznajemy po ZMIANIE
 * znaczników z serwera (nowy `finished_at` różny od tego sprzed kliknięcia),
 * a nie po porównaniu z zegarem przeglądarki: przy przestawionym zegarze
 * użytkownika „koniec po kliknięciu" nigdy by nie nadszedł.
 */

import type { OrderMailLastRun, OrderMailSyncStatus } from "@/lib/api/orderMail";

/** Znaczniki z chwili kliknięcia — punkt odniesienia dla `checkOutcome`. */
export interface CheckBaseline {
  finishedAt: string | null;
  startedAt: string | null;
}

export type CheckOutcome = "pending" | "completed" | "interrupted";

export function baselineOf(status: OrderMailSyncStatus | null | undefined): CheckBaseline {
  return {
    finishedAt: status?.last_completed?.finished_at ?? null,
    startedAt: status?.started_at ?? null,
  };
}

/**
 * Czy bieg uruchomiony po `baseline` już się skończył.
 *
 * `interrupted` liczy się tylko dla biegu zaczętego PO kliknięciu (nowy
 * `started_at`): przerwany bieg sprzed kliknięcia to stan zastany, nie wynik
 * tego sprawdzenia.
 */
export function checkOutcome(status: OrderMailSyncStatus, baseline: CheckBaseline): CheckOutcome {
  if (status.running) return "pending";
  const finished = status.last_completed?.finished_at ?? null;
  if (finished && finished !== baseline.finishedAt) return "completed";
  if (status.interrupted && status.started_at && status.started_at !== baseline.startedAt) {
    return "interrupted";
  }
  return "pending";
}

/** Polska liczba mnoga: 1 nowa / 2 nowe / 5 nowych (12–14 zawsze „nowych"). */
export function plural(n: number, one: string, few: string, many: string): string {
  const abs = Math.abs(n);
  if (abs === 1) return one;
  const last = abs % 10;
  const lastTwo = abs % 100;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return few;
  return many;
}

/** Trzy liczby z ticketu zawsze; nierozpoznani klienci i błędy — gdy są. */
export function formatLastRunSummary(run: OrderMailLastRun): string {
  const parts = [
    `${run.new_messages} ${plural(run.new_messages, "nowa wiadomość", "nowe wiadomości", "nowych wiadomości")}`,
    `${run.auto_applied} ${plural(run.auto_applied, "zapisane automatycznie", "zapisane automatycznie", "zapisanych automatycznie")}`,
    `${run.needs_review} do weryfikacji`,
  ];
  if (run.unrecognized > 0) {
    parts.push(
      `${run.unrecognized} ${plural(run.unrecognized, "nierozpoznany klient", "nierozpoznanych klientów", "nierozpoznanych klientów")}`,
    );
  }
  if (run.failed > 0) {
    parts.push(`${run.failed} ${plural(run.failed, "błąd", "błędy", "błędów")}`);
  }
  return parts.join(" · ");
}

export function reasonLabel(reason: string | null | undefined): string {
  if (reason === "manual") return "ręcznie";
  if (reason === "scheduled") return "automatycznie";
  return reason ?? "—";
}

/** „12 min temu" — wiek liczy się tu bardziej niż data (jak w karcie Traffita). */
export function formatAge(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "nigdy";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "nieznany";
  const minutes = Math.floor((now - then) / 60_000);
  if (minutes < 1) return "przed chwilą";
  if (minutes < 60) return `${minutes} min temu`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h temu`;
  return `${Math.floor(hours / 24)} dni temu`;
}
