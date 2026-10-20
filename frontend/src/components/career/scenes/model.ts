/**
 * Sceny ról w hero strony kariery (po 0478, makiety
 * https://claude.ai/artifact/TFqDt54DUg4qRdyJXnu6wm, strona „Najczęstsze role —
 * interaktywne”). Czysta logika: co jest do zaznaczenia i jak brzmi wynik.
 *
 * Wynik „x z 5” liczy się WYŁĄCZNIE w przeglądarce (decyzja Artura 19.10.2026):
 * nic nie zapisujemy i nic nie wysyłamy, a przycisk „Aplikuj” działa zawsze.
 */
import { instrumentalName } from "@/lib/career/format";

import type { CareerThemeId } from "../themes";

/**
 * Szablony, które mają już scenę (`CareerScene.tsx`). Lista żyje tu, a nie
 * w module klienckim, bo czyta ją też komponent serwerowy strony.
 */
export const CAREER_SCENE_IDS: readonly CareerThemeId[] = [
  "terminal",
  "sekwencja",
  "glitch",
  "konstelacja",
  "c4",
  "topologia",
  "tablica",
  "plan",
  "papier",
  "radar",
  "horyzont",
  "szafa",
];

export function hasCareerScene(theme: CareerThemeId): boolean {
  return CAREER_SCENE_IDS.includes(theme);
}

/** Najwięcej pozycji w scenie — makiety mają pięć miejsc. */
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

/** Mile widziane, które nie weszły do sceny — sceny pokazują je jako ozdobę. */
export function leftoverNice(nice: readonly string[], items: readonly SceneItem[]): string[] {
  const used = items.filter((i) => i.kind === "nice").length;
  return nice.filter((n) => n.trim()).slice(used).map((n) => n.trim());
}

/** Cztery kroki procesu — te same co w `ProcessSteps`. */
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

/** Zaznaczenie albo odznaczenie pozycji; kolejność wyboru zostaje (konstelacja ją rysuje). */
export function toggleInOrder(order: readonly number[], index: number): number[] {
  return order.includes(index) ? order.filter((i) => i !== index) : [...order, index];
}

/** Zdanie pod wynikiem. Poniżej kompletu zawsze zachęta (decyzja Artura 19.10.2026). */
export function scoreNote(count: number, total: number): string {
  if (total > 0 && count >= total) return "Pełne dopasowanie — czekamy na Ciebie.";
  return "Nie musisz mieć wszystkiego — aplikuj.";
}

/** Napis na przycisku „Aplikuj”. */
export function ctaLabel(count: number, total: number): string {
  if (count <= 0) return "Aplikuj — 2 minuty";
  return `Aplikuj — masz ${count} z ${total}`;
}

/** Nazwa wymagania jako wywołanie metody: „Spring Boot” → springBoot(). */
export function methodName(name: string): string {
  const words = name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ł/g, "l")
    .replace(/Ł/g, "L")
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean);
  if (words.length === 0) return "wymaganie";
  const [first, ...rest] = words;
  const head = /^[A-Z0-9]+$/.test(first) ? first.toLowerCase() : first[0].toLowerCase() + first.slice(1);
  const camel = head + rest.map((w) => w[0].toUpperCase() + w.slice(1)).join("");
  return /^[0-9]/.test(camel) ? `_${camel}` : camel;
}
