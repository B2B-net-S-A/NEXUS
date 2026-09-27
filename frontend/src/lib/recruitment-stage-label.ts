/**
 * Etap i źródło rekrutacji na profilu kandydata (Rekrutacje) — runda 10, F04.
 *
 * Ręczne przypisanie kładzie osobę na pierwszym etapie szablonu, który nazywa
 * się „Ogłoszenia". Profil pisał ten etap dosłownie, Tablica — „Nowi", a karta
 * dokładała „Z ogłoszenia", choć nikt nie aplikował z ogłoszenia. Profil
 * składa teraz etap w kolumnę Tablicy tą samą regułą (`placeStage`), a źródło
 * bierze z procesu (`entry_source`), nie z nazwy etapu.
 */
import { BOARD_COLUMN_LABEL, placeStage } from "@/lib/board-stages";

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

const ENTRY_SOURCE_LABEL: Record<string, string> = {
  added_manual: "Dodany ręcznie",
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
