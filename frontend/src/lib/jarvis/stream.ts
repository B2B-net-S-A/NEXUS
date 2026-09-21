/**
 * Strumień tury Jarvisa: `POST /api/jarvis/chat` → zdarzenia SSE.
 *
 * Natywny `fetch`, bo axios nie czyta strumieni w przeglądarce. Omija więc
 * interceptory `lib/api.ts` — nagłówki bierzemy z `getAuthenticatedRequestHeaders`
 * (token + znacznik podglądu), a 401 obsługujemy sami tym samym wylogowaniem.
 * Błąd przed strumieniem (409 „jeszcze odpowiadam”, 503 wyłączony) przychodzi
 * jako `JarvisHttpError` z polskim komunikatem z serwera.
 */

import { apiErrorMessage } from "@/lib/api-error";
import { getAuthenticatedRequestHeaders } from "@/lib/session";
import { createSseParser } from "./sse";
import type { JarvisScreen, JarvisStreamEvent } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class JarvisHttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "JarvisHttpError";
  }
}

export interface JarvisChatBody {
  message: string;
  conversation_id?: string | null;
  screen?: JarvisScreen | null;
  /** Przełącznik „Szukaj w internecie” — tylko ta jedna tura. */
  web?: boolean;
}

export interface StreamOptions {
  signal?: AbortSignal;
  onEvent: (event: JarvisStreamEvent) => void;
  /** Wstrzykiwalne w testach. */
  fetchImpl?: typeof fetch;
  onUnauthorized?: () => void;
}

export async function streamJarvisChat(body: JarvisChatBody, options: StreamOptions): Promise<void> {
  const doFetch = options.fetchImpl ?? fetch;
  const response = await doFetch(`${API_BASE}/api/jarvis/chat`, {
    method: "POST",
    headers: getAuthenticatedRequestHeaders({
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    }),
    body: JSON.stringify(body),
    signal: options.signal,
  });

  if (!response.ok) {
    if (response.status === 401) options.onUnauthorized?.();
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    const message = apiErrorMessage(
      { response: { status: response.status, data: payload } },
      response.status === 409
        ? "Jarvis jeszcze odpowiada na poprzednie pytanie — poczekaj chwilę."
        : "Jarvis jest chwilowo niedostępny.",
    );
    throw new JarvisHttpError(response.status, message);
  }
  if (!response.body) throw new JarvisHttpError(0, "Przeglądarka nie obsługuje strumienia odpowiedzi.");

  const reader = response.body.getReader();
  const parser = createSseParser();
  let sawDone = false;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const event of parser.feed(value)) {
      if (event.type === "done") sawDone = true;
      options.onEvent(event);
    }
  }
  for (const event of parser.flush()) {
    if (event.type === "done") sawDone = true;
    options.onEvent(event);
  }
  if (!sawDone) {
    // Strumień urwany (deploy, sieć). Tura po stronie serwera dokończy się
    // i zapisze w historii — mówimy to wprost zamiast udawać sukces.
    options.onEvent({
      type: "error",
      code: "interrupted",
      message: "Połączenie przerwane. Odpowiedź może pojawić się w historii rozmowy — odśwież ją za chwilę.",
    });
  }
}
