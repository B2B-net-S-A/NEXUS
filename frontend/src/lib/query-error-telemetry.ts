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
 * timeoutu. Zapisy są raportowane deterministycznie; odczyty są próbkowane.
 * Wyjątki spoza axios w mutacjach mają osobną klasę klienta i zachowują
 * oczyszczone miejsca źródłowe; nie dowodzą błędu HTTP ani awarii backendu.
 */

import { defaultStackParser } from '@sentry/nextjs';
import { reactErrorCode, scrubSentryEvent } from './sentry-privacy';

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
  response?: { status?: number; headers?: Record<string, string> };
  config?: { url?: string; method?: string; baseURL?: string; headers?: Record<string, string> };
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
  path = path.replace(/(\/(?:public\/(?:cv-i|cv|champion-card|apply|engagement-declaration)|share-token|sign)\/)[^/]+/g, "$1:token");
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
  context: { tags: Record<string, string>; fingerprint: string[]; contexts: { correlation: Record<string, string> } },
) => void;

/** Rebuild only parsed, scrubbed source frames; raw stack text may contain PII. */
function privateMutationError(error: Error): Error {
  const code = reactErrorCode(error.message);
  const reported = new Error(`Client mutation failed${code ? ` (React error #${code})` : ''}`);
  const stack = error.stack ?? '';
  // Error.message can itself contain newlines that look like stack frames.
  // Remove the COMPLETE header before parsing, not just its first line.
  const messagePrefix = [`${error.name}: ${error.message}`, error.message].find(prefix =>
    prefix && (stack === prefix || stack.startsWith(`${prefix}\n`) || stack.startsWith(`${prefix}\r\n`)));
  // Safari/Firefox omit the message header. Accept their frame-first form;
  // an unknown header may contain a previous message after Error was edited.
  const headerless = /^(?:[^\r\n@]*@)?(?:https?|file|webpack(?:-internal)?):\/\//.test(stack)
    || /^\s*at (?:[^\r\n(]*\()?(?:https?|file|webpack(?:-internal)?):\/\//.test(stack);
  const sourceStack = messagePrefix ? stack.slice(messagePrefix.length) : headerless ? stack : '';
  const event = scrubSentryEvent({
    exception: { values: [{ stacktrace: { frames: defaultStackParser(sourceStack) } }] },
  });
  const frames = event.exception.values[0].stacktrace.frames;
  reported.stack = [
    `${reported.name}: ${reported.message}`,
    ...frames.slice().reverse().filter(frame => frame.filename).map(frame =>
      `    at ${frame.filename}:${frame.lineno ?? 0}:${frame.colno ?? 0}`),
  ].join('\n');
  return reported;
}

export function createQueryFailureReporter({
  capture,
  random = Math.random,
  now = Date.now,
}: {
  capture: CaptureFn;
  random?: () => number;
  now?: () => number;
}): (error: unknown, mutationIdentity?: object) => void {
  const lastReported = new Map<string, number>();
  const reportedWrites = new WeakSet<object>();
  return (error: unknown, mutationIdentity?: object) => {
    const failure = classifyQueryError(error);
    if (!failure) {
      if (!mutationIdentity || !(error instanceof Error) || (error as AxiosLikeError).isAxiosError) return;
      if (reportedWrites.has(mutationIdentity)) return;
      reportedWrites.add(mutationIdentity);
      const code = reactErrorCode(error.message);
      capture(privateMutationError(error), {
        contexts: { correlation: {} },
        tags: {
          terminal: 'true',
          operation: 'client-mutation',
          failure_kind: 'client',
          sampling_policy: 'all-terminal-writes',
          ...(code ? { react_error_code: code } : {}),
        },
        fingerprint: ['client-mutation-failure', '{{ default }}', ...(code ? [`react-${code}`] : [])],
      });
      return;
    }
    const err = error as AxiosLikeError;
    const write = !!mutationIdentity || !["GET", "HEAD", "OPTIONS"].includes(failure.method);
    const identity = mutationIdentity ?? err.config ?? err;
    if (write && reportedWrites.has(identity)) return;
    const key = `${failure.kind}|${failure.status ?? ""}|${failure.method}|${failure.path}`;
    const at = now();
    const previous = lastReported.get(key);
    if (!write) {
      if (previous !== undefined && at - previous < QUERY_FAILURE_DEDUPE_MS) return;
      if (random() >= QUERY_FAILURE_SAMPLE_RATE) return;
      for (const [oldKey, timestamp] of lastReported) {
        if (at - timestamp >= QUERY_FAILURE_DEDUPE_MS) lastReported.delete(oldKey);
      }
      lastReported.set(key, at);
    } else {
      reportedWrites.add(identity);
    }
    const correlation: Record<string, string> = {};
    const operationId = err.config?.headers?.["X-Operation-Id"];
    const requestId = err.response?.headers?.["x-request-id"];
    if (operationId && /^[0-9a-f-]{36}$/i.test(operationId)) correlation.operation_id = operationId;
    if (requestId && /^[0-9a-f-]{36}$/i.test(requestId)) correlation.request_id = requestId;
    const label = failure.status ? `${failure.kind} ${failure.status}` : failure.kind;
    capture(new Error(`API ${label}: ${failure.method} ${failure.path}`), {
      contexts: { correlation },
      tags: {
        terminal: "true",
        operation: `${failure.method} ${failure.path}`,
        failure_kind: failure.kind,
        sampling_policy: write ? "all-terminal-writes" : "reads-10pct-60s",
        api_failure: failure.kind,
        api_status: failure.status ? String(failure.status) : "none",
        api_method: failure.method,
        api_path: failure.path,
      },
      fingerprint: ["api-failure", failure.kind, failure.method, failure.path],
    });
  };
}
