/**
 * „„SailPoint” = SailPoint IIQ” (28.10.2026, sekcja „Ukryci przez »musi
 * mieć«”): wariant trafia do słów wiersza krytycznej TYM SAMYM zapisem co
 * „+ lub” w edytorze wymagań — `PUT …/champion-profile` z całym `stack`
 * i odciskiem profilu. Nocny przegląd liczy go od następnej nocy.
 *
 * Czysta funkcja — bez Reacta i sieci.
 */

import type { ChampionStack } from "@/lib/api";
import { addRowVariants, rowHead, ROW_WORDS_MAX } from "@/lib/requirement-rows";

type StoredRows = NonNullable<ChampionStack["rows"]>;

export type VariantRowsResult =
  | { ok: true; rows: StoredRows }
  | { ok: false; reason: string };

const fold = (value: string) => value.trim().toLocaleLowerCase("pl");

/**
 * Wiersze `stack.rows` z `word` dopisanym do wiersza „musi mieć” o etykiecie
 * `rowLabel` (pierwsze słowo wiersza, jak `rowHead`). Reszta wierszy bez zmian.
 */
export function rowsWithVariant(
  rows: ChampionStack["rows"],
  rowLabel: string,
  word: string,
): VariantRowsResult {
  const list = rows ?? [];
  const index = list.findIndex(
    (row) => row.level !== "nice" && fold(rowHead(row.words)) === fold(rowLabel),
  );
  if (index < 0) {
    return { ok: false, reason: `W Profilu Championa nie ma już wiersza „${rowLabel}”.` };
  }
  const { words } = addRowVariants(list[index].words, word);
  if (words.length === list[index].words.length) {
    return { ok: false, reason: `„${word}” jest już w wierszu „${rowLabel}”.` };
  }
  if (words.length > ROW_WORDS_MAX) {
    return {
      ok: false,
      reason: `Wiersz „${rowLabel}” ma już ${ROW_WORDS_MAX} wariantów — dopisz w Profilu Championa.`,
    };
  }
  return {
    ok: true,
    rows: list.map((row, i) => (i === index ? { ...row, words } : row)),
  };
}
