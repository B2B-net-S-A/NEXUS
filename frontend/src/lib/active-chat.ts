import { useEffect } from "react";

export type ChatKind = "job" | "candidate";

/**
 * Który czat jest teraz otwarty na ekranie (zamontowana zakładka czatu).
 *
 * Dymek o nowej wiadomości nie ma sensu, gdy odbiorca właśnie patrzy na tę
 * rozmowę — zakładka czatu sama ją dociąga i oznacza jako przeczytaną.
 * Stan modułu, nie store: jedna karta przeglądarki ma naraz jeden otwarty czat.
 */
let active: { kind: ChatKind; entityId: number } | null = null;

export function useActiveChat(kind: ChatKind, entityId: number): void {
  useEffect(() => {
    active = { kind, entityId };
    return () => {
      if (active?.kind === kind && active.entityId === entityId) active = null;
    };
  }, [kind, entityId]);
}

export function isChatOnScreen(kind: ChatKind, entityId: number): boolean {
  return (
    active?.kind === kind &&
    active.entityId === entityId &&
    typeof document !== "undefined" &&
    document.visibilityState === "visible"
  );
}
