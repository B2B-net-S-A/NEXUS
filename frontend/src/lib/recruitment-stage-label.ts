/**
 * Etap i źródło rekrutacji na profilu kandydata (Rekrutacje) — runda 10, F04.
 *
 * Ręczne przypisanie kładzie osobę na pierwszym etapie szablonu, który nazywa
 * się „Ogłoszenia". Profil pisał ten etap dosłownie, Tablica — „Nowi", a karta
 * dokładała „Z ogłoszenia", choć nikt nie aplikował z ogłoszenia. Profil
 * składa teraz etap w kolumnę Tablicy tą samą regułą (`placeStage`), a źródło
 * bierze z procesu (`entry_source`), nie z nazwy etapu.
 */
import {
  BOARD_COLUMN_LABEL,
  BOARD_COLUMN_ORDER,
  placeStage,
} from "@/lib/board-stages";

export function recruitmentStageLabel(
  stage: string | null | undefined,
  stageName: string | null | undefined,
  fallbackLabel: (stage: string | null | undefined) => string,
): string {
  if (!stage) return fallbackLabel(stage);
  const { column } = placeStage({ stage, name: stageName ?? null });
  // Zamknięci: „Odrzucony" / „Wycofany" mówią więcej niż „Zamknięci".
  if (column === "closed") return fallbackLabel(stage);
  return BOARD_COLUMN_LABEL[column];
}

// Ticket 11 (30.09.2026): bez etykiety „Dodany ręcznie” w całym NEXUSIE —
// ręczne dodanie to zwykła droga, a nie wyjątek wart plakietki.
const ENTRY_SOURCE_LABEL: Record<string, string> = {
  application: "Z ogłoszenia",
  proposal: "Z propozycji",
  reassign: "Przepięcie z podobnej rekrutacji",
  auto_match: "Z automatu",
  import: "Import z Traffita",
};

/** Etykieta źródła wejścia; `null` = źródło nieznane (proces sprzed 0352). */
export function entrySourceLabel(source: string | null | undefined): string | null {
  if (!source) return null;
  return ENTRY_SOURCE_LABEL[source] ?? null;
}

export interface RecruitmentStageMove {
  stage?: string | null;
  stage_name?: string | null;
  moved_at?: string | null;
}

/**
 * Ścieżka etapów osoby w jednej rekrutacji (profil → Rekrutacje): od
 * najstarszego ruchu, a kolejne ruchy, które dają tę samą etykietę, raz.
 * Backend oddaje ruchy od najnowszego i po jednym wierszu na ruch, więc
 * profil pokazywał „Zatrudniony, Zatrudniony, Umowa, Rozmowa u klienta,
 * Rozmowa u klienta” (przegląd 04.10.2026).
 */
export function recruitmentStagePath(
  stages: RecruitmentStageMove[] | null | undefined,
  fallbackLabel: (stage: string | null | undefined) => string,
): string[] {
  const ordered = [...(Array.isArray(stages) ? stages : [])].sort((a, b) => {
    const at = a.moved_at ? Date.parse(a.moved_at) : 0;
    const bt = b.moved_at ? Date.parse(b.moved_at) : 0;
    return at - bt;
  });
  const path: string[] = [];
  for (const move of ordered) {
    const label = recruitmentStageLabel(move.stage, move.stage_name, fallbackLabel);
    if (path[path.length - 1] !== label) path.push(label);
  }
  return path;
}

/**
 * Najdalsza kolumna Tablicy, do której osoba doszła w tej rekrutacji
 * (zamknięci się nie liczą). `null` = żaden ruch nie mieści się w kolumnach.
 */
export function furthestBoardColumnLabel(
  stages: RecruitmentStageMove[] | null | undefined,
): string | null {
  let best = -1;
  for (const move of Array.isArray(stages) ? stages : []) {
    if (!move.stage) continue;
    const { column } = placeStage({ stage: move.stage, name: move.stage_name ?? null });
    if (column === "closed") continue;
    best = Math.max(best, BOARD_COLUMN_ORDER.indexOf(column));
  }
  return best < 0 ? null : BOARD_COLUMN_LABEL[BOARD_COLUMN_ORDER[best]];
}

export type RecruitmentOutcomeTone = "success" | "neutral" | "danger" | "warning";

/** Wynik zakończonego procesu w tabeli „Zakończone”. */
export function recruitmentOutcome(item: {
  latest_stage?: string | null;
  job_status?: string | null;
}): { label: string; tone: RecruitmentOutcomeTone } {
  switch (item.latest_stage) {
    case "hired":
    case "onboarding":
      return { label: "Zatrudniony", tone: "success" };
    case "rejected":
      return { label: "Odrzucony", tone: "danger" };
    case "withdrawn":
      return { label: "Zrezygnował", tone: "warning" };
    default:
      return { label: "Rekrutacja zamknięta", tone: "neutral" };
  }
}
