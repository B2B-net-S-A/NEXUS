"use client";

/**
 * Treść, która zmienia miejsce na ekranie bez ponownego montowania
 * („Arkusz rozmowy”, 23.11.2026).
 *
 * Formularz screeningu w „Trybie rozmowy” przechodzi z prawej kolumny panelu
 * do lewej strefy. Zwykły portal do innego kontenera montuje treść od nowa —
 * a formularz trzyma niezapisane wpisy rekrutera w stanie RHF, więc
 * przełączenie trybu w trakcie rozmowy by je skasowało. Dlatego treść żyje
 * w jednym stałym elemencie DOM (portal zawsze do niego), a ten element
 * przenosimy między miejscami (`MovableSlot`). Zdarzenia React idą drzewem
 * komponentów, nie DOM, więc działają tak samo w obu miejscach.
 */

import { useCallback, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export interface MovableHost {
  /** Stały element, do którego trafia treść; `null` na serwerze. */
  node: HTMLElement | null;
  /** Treść w portalu (renderuj ją zawsze w tym samym miejscu drzewa). */
  render: (content: ReactNode) => ReactNode;
}

export function useMovableHost(className?: string): MovableHost {
  const [node] = useState<HTMLElement | null>(() => {
    if (typeof document === "undefined") return null;
    const el = document.createElement("div");
    el.dataset.movableHost = "";
    if (className) el.className = className;
    return el;
  });
  const render = useCallback(
    (content: ReactNode) => (node ? createPortal(content, node) : content),
    [node],
  );
  return { node, render };
}

/** Miejsce na ekranie, w którym ma stać treść hosta (pierwsze zamontowane wygrywa). */
export function MovableSlot({ host, className }: { host: MovableHost; className?: string }) {
  const attach = useCallback(
    (slot: HTMLDivElement | null) => {
      if (slot && host.node && host.node.parentElement !== slot) slot.appendChild(host.node);
    },
    [host.node],
  );
  if (!host.node) return null;
  return <div ref={attach} className={className} data-movable-slot="" />;
}
