"use client";

import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/**
 * `false` na serwerze i w renderze hydratacji, `true` zaraz po niej. Przy
 * nawigacji po stronie klienta (bez hydratacji) od razu `true`.
 *
 * Dla ekranu, którego pierwszy render zależy od cache'u react-query: inny
 * komponent mógł wypełnić ten klucz, zanim React doszedł do ekranu, a serwer
 * zawsze renderuje z pustym cache'em — bez tej bramki hydratacja się rozjeżdża.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}
