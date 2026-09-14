/**
 * Telemetria końcowych błędów zapytań i mutacji react-query.
 *
 * Powód (reaudyt 14.09.2026, R07): błąd zapytania obsłużony przez react-query
 * kończy się stanem `error` w komponencie i NIGDY nie trafia do Sentry — nie
 * jest nieobsłużonym wyjątkiem ani nie przechodzi przez granicę błędów.
 * Zmiana filtra Sentry z 13.09 nie miała więc czego filtrować dla typowych
 * awarii: 503 z proxy, timeoutu czy 500 widzianych na ekranach z danymi.
 *
 * Raportujemy wyłącznie klasy świadczące o awarii po naszej stronie:
 * brak odpowiedzi (sieć / proxy bez CORS), timeout przeglądarki i 5xx.
 * 4xx to stany aplikacji (brak uprawnień, walidacja), nie awarie.
 *
 * Zdarzenie jest SYNTETYCZNE (nowy `Error` z tagami), nie oryginalny błąd
 * axios: nie niesie treści odpowiedzi, nagłówków ani parametrów zapytania
 * (dane kandydatów, tokeny), a filtr `beforeSend` nie odrzuca go jako
 * timeoutu. Próbkowanie i deduplikacja chronią limit 5k zdarzeń/mc.
 */

export type QueryFailureKind = "network" | "timeout" | "server";

export interface QueryFailure {
  kind: QueryFailureKind;
  status: number | null;
  method: string;
  path: string;
}

/** Ułamek zgłaszanych awarii. */
export const QUERY_FAILURE_SAMPLE_RATE = 0.1;
/** Ta sama awaria (klasa + trasa) nie jest zgłaszana częściej niż raz na okno. */
export const QUERY_FAILURE_DEDUPE_MS = 60_000;

interface AxiosLikeError {
  isAxiosError?: boolean;
  code?: string;
  name?: string;
  response?: { status?: number };
  config?: { url?: string; method?: string; baseURL?: string };
}

/** Ścieżka API bez originu, query stringu i identyfikatorów. */
export function normalizeApiPath(url: string | undefined): string {
  if (!url) return "unknown";
  let path = url;
  try {
    path = new URL(url, "http://placeholder").pathname;
  } catch {
    path = url.split("?")[0] ?? url;
  }
  return (
    path
      .split("/")
      .map((segment) => {
        if (/^\d+$/.test(segment)) return ":id";
        if (/^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(segment)) return ":uuid";
        // Tokeny udostępniania i inne długie identyfikatory w ścieżce.
        if (segment.length >= 20 && /^[A-Za-z0-9_\-$.]+$/.test(segment)) return ":token";
        return segment;
      })
      .join("/")
      .slice(0, 160) || "/"
  );
}

export function classifyQueryError(error: unknown): QueryFailure | null {
  const err = error as AxiosLikeError | null;
  if (!err || typeof err !== "object" || !err.isAxiosError) return null;
  if (err.code === "ERR_CANCELED" || err.name === "CanceledError") return null;
  const method = (err.config?.method ?? "get").toUpperCase();
  const path = normalizeApiPath(err.config?.url);
  if (err.code === "ECONNABORTED" || err.code === "ETIMEDOUT") {
    return { kind: "timeout", status: null, method, path };
  }
  const status = err.response?.status;
  if (status === undefined) {
    return { kind: "network", status: null, method, path };
  }
  if (status >= 500) return { kind: "server", status, method, path };
  return null;
}

export type CaptureFn = (
  error: Error,
  context: { tags: Record<string, string>; fingerprint: string[] },
) => void;

export function createQueryFailureReporter({
  capture,
  random = Math.random,
  now = Date.now,
}: {
  capture: CaptureFn;
  random?: () => number;
  now?: () => number;
}): (error: unknown) => void {
  const lastReported = new Map<string, number>();
  return (error: unknown) => {
    const failure = classifyQueryError(error);
    if (!failure) return;
    const key = `${failure.kind}|${failure.status ?? ""}|${failure.method}|${failure.path}`;
    const at = now();
    const previous = lastReported.get(key);
    if (previous !== undefined && at - previous < QUERY_FAILURE_DEDUPE_MS) return;
    lastReported.set(key, at);
    if (random() >= QUERY_FAILURE_SAMPLE_RATE) return;
    const label = failure.status ? `${failure.kind} ${failure.status}` : failure.kind;
    capture(new Error(`API ${label}: ${failure.method} ${failure.path}`), {
      tags: {
        api_failure: failure.kind,
        api_status: failure.status ? String(failure.status) : "none",
        api_method: failure.method,
        api_path: failure.path,
      },
      fingerprint: ["api-failure", failure.kind, failure.method, failure.path],
    });
  };
}
