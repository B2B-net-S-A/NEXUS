/**
 * Podział kolumn kanbana na kroki 07 „Rozmowy i decyzja" i 08 „Umowa".
 *
 * Osobny moduł, a nie funkcje lokalne w zakładkach, z tego samego powodu co
 * `kanban-terminal.ts`: test ma wiązać się z TĄ SAMĄ funkcją, której używają
 * komponenty. Moduł nie importuje niczego z `KanbanBoardV2` ani z zakładek,
 * więc cyklu nie ma.
 *
 * Skąd te dwa zbiory:
 *
 * - **Krok 08** rozpoznajemy po NAZWACH etapów podpisu — dokładnie tych,
 *   których używa hook podpisu po stronie serwera
 *   (`backend/app/services/signing/pipeline_hook.py`: `STAGE_SENT`,
 *   `STAGE_SIGNED`, `STAGE_HIRED`). To nie jest nowa heurystyka: „Umowa
 *   wysłana" i „Umowa podpisana" NIE MAJĄ `legacy_enum_value`, więc backend
 *   raportuje dla nich `stage: "new"` i po `stage` ich nie da się poznać.
 *   Nazwa jest jedynym identyfikatorem, jaki system dla nich ma — po obu
 *   stronach tak samo. Dokładamy do tego terminal `hired` (po `terminalOf`,
 *   nie po nazwie) i legacy `onboarding`.
 * - **Krok 07** to reszta etapów `external`, które nie należą do kroku 08
 *   i nie są terminalne. Dla szablonu „Default B2B" wychodzi z tego Interview
 *   Klient · Akceptacja · Negocjacje — czyli te, na których kandydat jest
 *   „u klienta".
 *
 * Ograniczenie jest świadome i wspólne z backendem: szablon, który nazwie
 * etapy podpisu inaczej, pokaże je w kroku 07 — tak samo, jak hook podpisu
 * nie przeniesie na nie kandydata. Jedno źródło nazw, jeden tryb awarii.
 */

import { terminalOf, type TerminalAwareColumn } from "@/lib/kanban-terminal";

/** Lustro `STAGE_SENT` / `STAGE_SIGNED` z `services/signing/pipeline_hook.py`. */
export const CONTRACT_STAGE_NAMES: readonly string[] = [
  "Umowa wysłana",
  "Umowa podpisana",
];

export interface FlowColumn extends TerminalAwareColumn {
  category?: "internal" | "external" | "terminal";
  name?: string | null;
}

function normalizedName(col: FlowColumn): string {
  return (col.name ?? "").trim().toLocaleLowerCase("pl-PL");
}

/** Etap należy do kroku 08 „Umowa" (podpis → zatrudnienie → onboarding). */
export function isContractStage(col: FlowColumn): boolean {
  if (terminalOf(col) === "hired") return true;
  if (col.stage === "onboarding") return true;
  const name = normalizedName(col);
  return CONTRACT_STAGE_NAMES.some(
    (candidate) => candidate.toLocaleLowerCase("pl-PL") === name,
  );
}

/** Etap należy do kroku 07 „Rozmowy i decyzja" (kandydat jest u klienta). */
export function isInterviewStage(col: FlowColumn): boolean {
  if (terminalOf(col) !== null) return false;
  if (isContractStage(col)) return false;
  return col.category === "external";
}
