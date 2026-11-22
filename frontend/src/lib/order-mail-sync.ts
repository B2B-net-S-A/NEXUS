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

export type MailboxTone = "neutral" | "info" | "success" | "warning" | "danger";

export interface MailboxSentence {
  tone: MailboxTone;
  /** Stan skrzynki — pierwsza część zdania. */
  title: string;
  /** Wynik ostatniego sprawdzenia (albo co dalej) — druga część zdania. */
  detail: string;
  /** Szczegół mówi o błędzie biegu — czerwony tekst. */
  detailIsError: boolean;
}

/**
 * Stan skrzynki jednym zdaniem nad kolejką (przebudowa 20.11.2026, wariant A).
 *
 * Bez nazw zmiennych środowiskowych — do tej daty wyłączona skrzynka mówiła
 * „ORDER_MAIL_INGEST_ENABLED=false”. Liczby opisują OSTATNIE sprawdzenie,
 * nie bieżące zaległości (UAT B75: „0 do weryfikacji” obok „(2)” na zakładce),
 * a Delivery Lead (`scoped`) dowiaduje się, że zakładki liczą jego portfel.
 */
export function mailboxSentence(
  status: OrderMailSyncStatus | null,
  opts: { statusError: boolean; checking: boolean; scoped?: boolean },
): MailboxSentence {
  const busy = opts.checking || Boolean(status?.running);
  const last = status?.last_completed ?? null;
  if (opts.statusError) {
    return {
      tone: "warning",
      title: "Nie udało się pobrać stanu skrzynki.",
      detail: "Kolejka niżej działa — nie wiadomo tylko, jak jest świeża.",
      detailIsError: false,
    };
  }
  if (!status) return { tone: "neutral", title: "Sprawdzam stan skrzynki…", detail: "", detailIsError: false };
  const interrupted =
    status.interrupted && !busy
      ? " Poprzednie sprawdzenie zostało przerwane (restart aplikacji) — następne uruchomi się samo."
      : "";
  if (!status.enabled) {
    return {
      tone: "neutral",
      title: "Pobieranie zamówień z maila jest wyłączone.",
      detail: `Skrzynka zamowienia@ nie jest teraz sprawdzana — włącza ją administrator.${
        last ? ` Ostatnie sprawdzenie: ${formatAge(last.finished_at)}.` : ""
      }`,
      detailIsError: false,
    };
  }
  if (busy) {
    return {
      tone: "info",
      title: "Sprawdzam skrzynkę zamowienia@…",
      detail: "Nowe wiadomości pojawią się w kolejce po zakończeniu sprawdzania.",
      detailIsError: false,
    };
  }
  if (!last) {
    return {
      tone: "success",
      title: `Skrzynka sprawdzana automatycznie co ${status.interval_minutes} min, jeszcze nie sprawdzana.`,
      detail: `Pierwsze sprawdzenie uruchomi się samo albo po kliknięciu przycisku.${interrupted}`,
      detailIsError: false,
    };
  }
  const title = `Skrzynka sprawdzana automatycznie co ${status.interval_minutes} min, ostatnio ${formatAge(last.finished_at)} (${reasonLabel(last.reason)}).`;
  if (last.status === "error") {
    return {
      tone: "danger",
      title,
      detail: `Sprawdzenie nie powiodło się: ${last.error ?? "błąd bez opisu"}.${interrupted}`,
      detailIsError: true,
    };
  }
  const partial = last.status === "partial" && last.error ? ` · ${last.error}` : "";
  const scope = opts.scoped ? " Zakładki niżej liczą Twój portfel klientów." : "";
  return {
    tone: "success",
    title,
    detail: `W ostatnim sprawdzeniu: ${formatLastRunSummary(last)}${partial}.${scope}${interrupted}`,
    detailIsError: false,
  };
}

/**
 * Tekst powodu bez reprezentacji wyjątku Pythona.
 *
 * Do 09.2026 writer zapisywał `repr(exc)`, więc dokumenty z kolejki mają
 * w bazie „Nie udało się zapisać zamówienia: ValueError('W bazie jest…')".
 * Nowe wpisy niosą samo zdanie; stare zostają w bazie i są czyszczone przy
 * wyświetleniu.
 */
export function withoutExceptionRepr(text: string): string {
  return text.replace(
    /\b[A-Z][A-Za-z]*(?:Error|Exception)\((['"])([\s\S]*?)\1\)/g,
    (_m, _q, inner: string) => inner,
  );
}

/** Powód z kolejki bez prefiksu writera — do porównania z `error`. */
function reasonCore(text: string): string {
  return withoutExceptionRepr(text)
    .replace(/^Nie udało się zapisać zamówienia:\s*/u, "")
    .trim();
}

/**
 * Czy czerwony „Błąd:" pod „Dlaczego do weryfikacji" wnosi coś nowego.
 *
 * Writer zapisuje nieudany zapis W DWA miejsca naraz: do `gate_reasons`
 * („Nie udało się zapisać zamówienia: …") i do `error` (samo zdanie). Kolejka
 * pokazywała więc ten sam komunikat dwa razy (UAT B49). „Błąd:" renderuje się
 * tylko wtedy, gdy jego treść NIE jest już wśród powodów — awaria innego
 * kroku (np. odczytu PDF-a) nadal ma swoje miejsce.
 */
export function errorOutsideReasons(
  error: string | null | undefined,
  reasons: readonly string[] | null | undefined,
): string | null {
  if (!error) return null;
  const core = reasonCore(error);
  if (!core) return null;
  const covered = (reasons ?? []).some((r) => {
    const rc = reasonCore(r);
    return rc === core || rc.includes(core);
  });
  return covered ? null : withoutExceptionRepr(error);
}
