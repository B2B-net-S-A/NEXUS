/**
 * Otwarcie Jarvisa z dowolnego miejsca aplikacji (paleta ⌘K, strona MINDY,
 * poranny dymek) bez wspólnego stanu: zdarzenie na `window`, które słucha
 * `JarvisRoot`. Opcjonalny `prompt` trafia od razu do pola wiadomości
 * (i jest wysyłany, gdy `send: true`).
 */

export const JARVIS_OPEN_EVENT = "nexus:jarvis-open";

export interface JarvisOpenDetail {
  prompt?: string;
  send?: boolean;
}

export function openJarvis(detail: JarvisOpenDetail = {}): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<JarvisOpenDetail>(JARVIS_OPEN_EVENT, { detail }));
}
