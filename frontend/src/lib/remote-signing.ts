"use client";

/**
 * Podpis w NEXUSIE u dostawcy w chmurze (kierunek K1, 22.11.2026): wspólne
 * kawałki strony kontraktora i panelu reprezentanta.
 *
 * Po powrocie od dostawcy (`?remote={session_id}`) ekran pyta co ok. 2 s o stan
 * sesji, aż dostanie `done`, `failed` albo `cancelled`. Po 3 minutach przestaje
 * i mówi, że odpowiedzi jeszcze nie ma, zamiast kręcić się bez końca.
 * Reguły: `docs/claude/kontrakty/podpis-umowy-b2b-w-nexusie.md`.
 */

import { useEffect, useRef, useState } from "react";

import type { RemoteSigningState } from "@/lib/api/b2bEsign";

export const REMOTE_POLL_MS = 2_000;
export const REMOTE_POLL_LIMIT_MS = 180_000;
/** Tyle nieudanych zapytań z rzędu (np. chwilowy brak sieci), zanim ekran pokaże błąd. */
const MAX_FAILURES_IN_A_ROW = 3;

const FINAL_STATES: ReadonlySet<RemoteSigningState> = new Set(["done", "failed", "cancelled"]);

export const REMOTE_POLL_FAILED = "Nie udało się sprawdzić stanu podpisu. Spróbuj ponownie za chwilę.";

/** Błąd zapytania o stan; `fatal` = nie ma sensu pytać dalej (np. 404 sesji). */
export class RemotePollError extends Error {
  constructor(
    message: string,
    readonly fatal = false,
  ) {
    super(message);
    this.name = "RemotePollError";
  }
}

export type RemotePoll<T> =
  | { phase: "polling"; result: T | null }
  | { phase: "finished"; result: T }
  | { phase: "timeout"; result: T | null }
  | { phase: "error"; message: string };

/**
 * Pyta `poll(sessionId)` do stanu końcowego. Bez `sessionId` nic nie robi.
 * `retry` zaczyna od nowa (nowe 3 minuty), np. po „Sprawdź jeszcze raz”.
 */
export function useRemoteSigningPoll<T extends { state: RemoteSigningState }>(
  sessionId: string | null,
  poll: (sessionId: string) => Promise<T>,
): { status: RemotePoll<T>; retry: () => void } {
  const [status, setStatus] = useState<RemotePoll<T>>({ phase: "polling", result: null });
  const [attempt, setAttempt] = useState(0);
  const pollRef = useRef(poll);
  useEffect(() => {
    pollRef.current = poll;
  });

  useEffect(() => {
    if (!sessionId) return undefined;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    let last: T | null = null;
    const deadline = Date.now() + REMOTE_POLL_LIMIT_MS;
    setStatus({ phase: "polling", result: null });

    const tick = async () => {
      try {
        const result = await pollRef.current(sessionId);
        if (stopped) return;
        failures = 0;
        last = result;
        if (FINAL_STATES.has(result.state)) {
          setStatus({ phase: "finished", result });
          return;
        }
        setStatus({ phase: "polling", result });
      } catch (error) {
        if (stopped) return;
        failures += 1;
        const fatal = error instanceof RemotePollError && error.fatal;
        if (fatal || failures >= MAX_FAILURES_IN_A_ROW) {
          setStatus({
            phase: "error",
            message: error instanceof RemotePollError ? error.message : REMOTE_POLL_FAILED,
          });
          return;
        }
      }
      if (Date.now() >= deadline) {
        setStatus({ phase: "timeout", result: last });
        return;
      }
      timer = setTimeout(() => void tick(), REMOTE_POLL_MS);
    };
    void tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [sessionId, attempt]);

  return { status, retry: () => setAttempt((n) => n + 1) };
}

/**
 * Przejście do strony dostawcy podpisu. Adres przychodzi z serwera, ale
 * sprawdzamy, że to http(s): `javascript:` z błędnej odpowiedzi nie wykona się.
 */
export function leaveForProvider(url: string): void {
  let parsed: URL;
  try {
    parsed = new URL(url, window.location.href);
  } catch {
    throw new Error("Nieprawidłowy adres dostawcy podpisu.");
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    throw new Error("Nieprawidłowy adres dostawcy podpisu.");
  }
  window.location.assign(parsed.toString());
}

/** Zdejmuje `?remote=` z adresu, żeby F5 po wyniku nie pytało o starą sesję. */
export function dropRemoteParam(): void {
  const url = new URL(window.location.href);
  if (!url.searchParams.has("remote")) return;
  url.searchParams.delete("remote");
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}
