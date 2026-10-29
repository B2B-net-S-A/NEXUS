/**
 * Pozycje wymagań do podglądu na tablicy i kroki procesu rekrutacji (czysta
 * logika). Do 28.10.2026 karmiły też 12 scen ról w hero strony rekrutacji —
 * sceny zastąpiły trzy szablony (`layouts/`), model został dla tablicy.
 */
import { instrumentalName } from "@/lib/career/format";

/** Najwięcej pozycji w podglądzie — szkic ma pięć miejsc. */
export const SCENE_MAX_ITEMS = 5;

export interface SceneItem {
  /** Stały klucz Reacta (nazwy wymagań mogą się powtarzać). */
  key: string;
  name: string;
  note: string | null;
  /** `nice` = mile widziane, dobrane, gdy wymagań jest mniej niż pięć. */
  kind: "must" | "nice";
}

export interface ProcessStep {
  title: string;
  note: string;
}

/**
 * Pozycje sceny: najpierw wymagania, potem mile widziane, razem najwyżej pięć.
 * Puste nazwy odpadają, bo przycisk bez etykiety byłby nie do odczytania.
 */
export function sceneItems(
  must: readonly { name: string; note: string | null }[],
  nice: readonly string[],
): SceneItem[] {
  const fromMust = must
    .filter((m) => m.name.trim())
    .map((m, i) => ({
      key: `m${i}`,
      name: m.name.trim(),
      note: m.note?.trim() || null,
      kind: "must" as const,
    }));
  const fromNice = nice
    .filter((n) => n.trim())
    .map((n, i) => ({ key: `n${i}`, name: n.trim(), note: null, kind: "nice" as const }));
  return [...fromMust, ...fromNice].slice(0, SCENE_MAX_ITEMS);
}

/** Cztery kroki procesu rekrutacji (sekcja „Jak wygląda proces” w układach). */
export function processSteps(recruiterFirstName: string, contract?: string | null): ProcessStep[] {
  const contractNote = contract?.trim()
    ? `umowa ${contract.trim().toLocaleLowerCase("pl-PL")}`
    : "umowa i wdrożenie";
  return [
    { title: `rozmowa z ${instrumentalName(recruiterFirstName)}`, note: "poznajemy się" },
    { title: "weryfikacja techniczna", note: "z ekspertem" },
    { title: "spotkanie z zespołem", note: "po stronie klienta" },
    { title: "decyzja i start", note: contractNote },
  ];
}
