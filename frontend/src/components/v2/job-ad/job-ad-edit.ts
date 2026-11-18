// Edycja treści ogłoszenia — czyste funkcje (bez Reacta i bez sieci).
//
// Okno pokazuje teksty policzone przez serwer (`rendered`), a poprawia pola
// `content`. Tu jest mapa między nimi: które pole ogłoszenia stoi za kartą
// portalu, jaki tekst trafia do edytora i jak z niego powstaje nowa treść.

import { removeExcerpt } from "@/components/v2/career-share/share-utils";
import {
  linesToItems,
  type AdContent,
  type AdFinding,
  type AdListKey,
  type AdTechItem,
  type AdTechLevel,
  type AdTextKey,
} from "@/lib/api/jobAd";

export const LIST_KEYS: readonly AdListKey[] = [
  "responsibilities",
  "requirements",
  "nice_to_have",
  "offer",
  "process",
];
export const TEXT_KEYS: readonly AdTextKey[] = [
  "title",
  "lead",
  "about",
  "start",
  "duration",
  "language",
  "city",
];

/** Pole treści z własnym edytorem. */
export type AdFieldKey = AdListKey | AdTextKey;
/** Lista technologii z karty Pracuj.pl — zapisuje się do `tech`, nie do treści. */
export type AdTechKey = "tech_required" | "tech_optional";
/** Klucz niezapisanej poprawki: pole, technologie albo ukryte punkty „co oferujemy”. */
export type AdEditKey = AdFieldKey | AdTechKey | "offer_hidden";

/** Niezapisane teksty pól okna; brak klucza = pole nie jest w edycji. */
export type AdDrafts = Readonly<Partial<Record<AdEditKey, string>>>;

export function withDraft(drafts: AdDrafts, key: AdEditKey, text: string | null): AdDrafts {
  if (text !== null) return { ...drafts, [key]: text };
  if (!(key in drafts)) return drafts;
  const next = { ...drafts };
  delete next[key];
  return next;
}

export function isListKey(key: string): key is AdListKey {
  return (LIST_KEYS as readonly string[]).includes(key);
}

export function isEditKey(key: string | null | undefined): key is AdFieldKey {
  return !!key && (isListKey(key) || (TEXT_KEYS as readonly string[]).includes(key));
}

export function isTechKey(key: string): key is AdTechKey {
  return key === "tech_required" || key === "tech_optional";
}

/**
 * Tekst do pola edycji: lista = jedna pozycja w wierszu. Etapy bez własnej
 * listy otwierają się z tym, co pokazuje karta (`shown`, stały blok firmy).
 */
export function editorText(
  content: AdContent,
  key: AdFieldKey,
  shown: readonly string[] = [],
): string {
  if (key === "process" && !content.process?.length) return shown.join("\n");
  return isListKey(key) ? (content[key] ?? []).join("\n") : content[key];
}

/**
 * Ile wierszy karty to stały blok, którego edytor nie zmienia. Etapy
 * w edycji to cała lista — własna zastępuje stały blok, a nie dopisuje się
 * do niego jak w „To oferujemy”.
 */
export function lockedFixedCount(key: string, fixedCount: number, drafts: AdDrafts): number {
  return key === "process" && drafts.process !== undefined ? 0 : fixedCount;
}

/** Treść po zapisaniu pola z edytora. */
export function withEdited(content: AdContent, key: AdFieldKey, text: string): AdContent {
  if (isListKey(key)) return { ...content, [key]: linesToItems(text) };
  // Opis projektu zachowuje akapity; pozostałe pola to jedna linia.
  const value = key === "about" ? text.trim() : text.replace(/\s+/g, " ").trim();
  return { ...content, [key]: value };
}

/** Ten sam punkt mimo innych wielkich liter i spacji — jak `render._key` na serwerze. */
export function sameItem(a: string, b: string): boolean {
  const norm = (text: string) => text.split(/\s+/).filter(Boolean).join(" ").toLowerCase();
  return norm(a) === norm(b);
}

/**
 * Własne punkty z edytora listy, bez tego, co ogłoszenie dokłada samo
 * (`locked`), i bez powtórzeń. Wklejona lista z karty „To oferujemy” niosła
 * warunki z rekrutacji i stały blok — liczyły się do limitu 6 i wychodziły
 * w ogłoszeniu dwa razy (zgłoszenie 28.10.2026).
 */
export function ownOfferLines(
  text: string,
  locked: readonly string[],
): { items: string[]; skipped: number } {
  const lines = linesToItems(text);
  const items: string[] = [];
  for (const line of lines) {
    if (![...locked, ...items].some((taken) => sameItem(taken, line))) items.push(line);
  }
  return { items, skipped: lines.length - items.length };
}

/**
 * Treść bez wskazanego fragmentu (akcja „Usuń fragment” w kontroli). Pozycja
 * listy, z której nic nie zostało, znika. `null` = fragmentu nie ma w polu.
 */
export function withoutExcerpt(content: AdContent, finding: AdFinding): AdContent | null {
  const key = finding.field;
  if (!finding.excerpt || !isEditKey(key)) return null;
  if (isListKey(key)) {
    const next = (content[key] ?? [])
      .map((item) => removeExcerpt(item, finding.excerpt as string))
      .filter(Boolean);
    return next.join("\n") === (content[key] ?? []).join("\n") ? null : { ...content, [key]: next };
  }
  const next = removeExcerpt(content[key], finding.excerpt);
  return next === content[key] ? null : { ...content, [key]: next };
}

export function withTechLevel(tech: AdTechItem[], name: string, level: AdTechLevel): AdTechItem[] {
  return tech.map((item) => (item.name === name ? { ...item, level } : item));
}

/**
 * Technologie po poprawce listy z karty Pracuj.pl (jedna nazwa w wierszu).
 * Znana nazwa zachowuje poziom (krytyczna zostaje krytyczną), nowa jest
 * wymagana albo mile widziana — zależnie od listy. Nazwa wpisana tu znika
 * z drugiej listy, żeby nie wyszła w ogłoszeniu dwa razy.
 */
export function withTechNames(tech: AdTechItem[], key: AdTechKey, text: string): AdTechItem[] {
  const optional = key === "tech_optional";
  const inList = (item: AdTechItem) => (item.level === "nice") === optional;
  const names: string[] = [];
  for (const line of linesToItems(text)) {
    if (!names.some((name) => sameItem(name, line))) names.push(line);
  }
  const edited = names.map((name): AdTechItem => {
    const before = tech.find((item) => inList(item) && sameItem(item.name, name));
    return before ? { ...before, name } : { name, level: optional ? "nice" : "must" };
  });
  const rest = tech.filter(
    (item) => !inList(item) && !names.some((name) => sameItem(name, item.name)),
  );
  return optional ? [...rest, ...edited] : [...edited, ...rest];
}

export function withoutTech(tech: AdTechItem[], name: string): AdTechItem[] {
  return tech.filter((item) => item.name !== name);
}

/** Pole ogłoszenia, do którego odsyła znalezisko — dla ramki i „Pokaż”. */
export function findingsByField(findings: AdFinding[]): Map<string, AdFinding[]> {
  const map = new Map<string, AdFinding[]>();
  for (const finding of findings) {
    if (!finding.field) continue;
    map.set(finding.field, [...(map.get(finding.field) ?? []), finding]);
  }
  return map;
}
