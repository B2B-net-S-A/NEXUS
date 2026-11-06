/**
 * Podpowiedź przy słowie wymagania, którego słownik nie zna (06.11.2026,
 * audyt słownika, makieta S2). Serwer (`POST /api/job-intake/dictionary-hints`)
 * czyta nocne propozycje; tu tylko tekst i dopisanie wariantów do wiersza.
 * Delivery Lead zmienia nią wyłącznie swój wiersz; słownik zmienia HoR+.
 */

import { pluralPl } from "@/lib/plural-pl";
import { ROW_WORDS_MAX } from "@/lib/requirement-rows";

export type DictionaryHintKind = "new" | "alias" | "generic" | "suggest";

export interface DictionaryHintWord {
  name: string;
  count: number | null;
}

export interface DictionaryHint {
  word: string;
  kind: DictionaryHintKind;
  proposal_id: number | null;
  word_count: number | null;
  target: DictionaryHintWord | null;
  add_words: DictionaryHintWord[];
  canonical: string | null;
  category: string | null;
}

export interface DictionaryHintsResponse {
  hints: DictionaryHint[];
  can_curate: boolean;
}

function fold(word: string): string {
  return word.trim().toLocaleLowerCase("pl-PL");
}

function num(n: number | null | undefined): string | null {
  return typeof n === "number" ? n.toLocaleString("pl-PL") : null;
}

function people(n: number): string {
  return `${num(n)} ${pluralPl(n, "osoba", "osoby", "osób")}`;
}

function withCount(word: DictionaryHintWord): string {
  const n = num(word.count);
  return n ? `${word.name} ${n}` : word.name;
}

/** Słowa podpowiedzi, których wiersz jeszcze nie ma (z limitem słów wiersza). */
export function missingWords(rowWords: readonly string[], hint: DictionaryHint): string[] {
  const have = new Set(rowWords.map(fold));
  const room = Math.max(0, ROW_WORDS_MAX - rowWords.length);
  return hint.add_words
    .map((w) => w.name)
    .filter((name, index, all) => !have.has(fold(name)) && all.findIndex((n) => fold(n) === fold(name)) === index)
    .slice(0, room);
}

/** Wiersz z dopisanymi wariantami podpowiedzi (bez duplikatów). */
export function rowWithHint(rowWords: readonly string[], hint: DictionaryHint): string[] {
  return [...rowWords, ...missingWords(rowWords, hint)];
}

export function hintMessage(hint: DictionaryHint): string {
  const own = num(hint.word_count);
  switch (hint.kind) {
    case "alias": {
      const target = hint.target;
      const counts =
        own && target && num(target.count)
          ? ` W umiejętnościach profili „${hint.word}” ma ${people(hint.word_count as number)}, a „${target.name}” ${num(target.count)}.`
          : "";
      return `Słownik nie zna „${hint.word}”, więc dopasowanie i bramka must-have szukają go dosłownie.${counts}`;
    }
    case "generic": {
      const lead = own
        ? `Ogólne wymaganie: w umiejętnościach profili ma je dosłownie ${people(hint.word_count as number)}`
        : "Ogólne wymaganie: profile opisują to konkretnymi hasłami";
      const examples = hint.add_words.slice(0, 4).map(withCount).join(", ");
      return examples ? `${lead}, a konkretne hasła więcej (${examples}).` : `${lead}.`;
    }
    case "new": {
      const forms = hint.add_words.slice(0, 4).map(withCount).join(", ");
      return forms
        ? `Słownik nie zna „${hint.word}”, a profile zapisują go na kilka sposobów: ${forms}.`
        : `Słownik nie zna „${hint.word}”, więc dopasowanie szuka go dosłownie.`;
    }
    case "suggest": {
      const target = hint.target;
      const n = num(target?.count);
      return target
        ? `Słownik nie zna „${hint.word}”. Może chodzi o „${target.name}”${n ? ` (${people(target.count as number)} w profilach)` : ""}?`
        : `Słownik nie zna „${hint.word}”.`;
    }
  }
}

/** Etykieta przycisku, który zmienia tylko wiersz. */
export function rowActionLabel(hint: DictionaryHint, missing: readonly string[]): string | null {
  if (missing.length === 0) return null;
  const list = missing.slice(0, 3).join(", ") + (missing.length > 3 ? "…" : "");
  if (hint.kind === "alias" || hint.kind === "suggest") return `Dodaj do wiersza „${missing[0]}”`;
  if (hint.kind === "generic") return `Dodaj warianty: ${list}`;
  return `Dodaj zapisy: ${list}`;
}

/** Etykieta przycisku HoR+, który zmienia słownik całej aplikacji. */
export function curateActionLabel(hint: DictionaryHint): string | null {
  if (!hint.proposal_id) return null;
  if (hint.kind === "new") return `Dodaj do słownika${hint.canonical ? ` jako „${hint.canonical}”` : ""}`;
  if (hint.kind === "alias" && hint.target) return `Zmapuj w słowniku na „${hint.target.name}”`;
  return null;
}
