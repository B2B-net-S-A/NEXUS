/**
 * Parser strumienia SSE z `POST /api/jarvis/chat` — czysty, bez sieci.
 *
 * Paczki z `fetch().body` tną zdarzenia w dowolnym miejscu (także w środku
 * znaku wielobajtowego — dlatego dekoder ze `stream: true`), więc parser
 * trzyma resztę bufora do następnej paczki. Linie `: ping` to heartbeat
 * serwera (co 10 s) i są pomijane.
 */

import type { JarvisStreamEvent } from "./types";

export interface SseParser {
  feed(chunk: Uint8Array | string): JarvisStreamEvent[];
  flush(): JarvisStreamEvent[];
}

function parseBlock(block: string): JarvisStreamEvent | null {
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (data.length === 0) return null;
  try {
    const parsed = JSON.parse(data.join("\n")) as JarvisStreamEvent;
    return parsed && typeof parsed === "object" && "type" in parsed ? parsed : null;
  } catch {
    return null;
  }
}

export function createSseParser(): SseParser {
  const decoder = new TextDecoder();
  let buffer = "";

  function drain(final: boolean): JarvisStreamEvent[] {
    const events: JarvisStreamEvent[] = [];
    const normalised = buffer.replace(/\r\n/g, "\n");
    const parts = normalised.split("\n\n");
    buffer = final ? "" : parts.pop() ?? "";
    for (const block of parts) {
      const event = parseBlock(block);
      if (event) events.push(event);
    }
    return events;
  }

  return {
    feed(chunk) {
      buffer += typeof chunk === "string" ? chunk : decoder.decode(chunk, { stream: true });
      return drain(false);
    },
    flush() {
      buffer += decoder.decode();
      return drain(true);
    },
  };
}
