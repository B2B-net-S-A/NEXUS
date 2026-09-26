import { classifyKeywords } from "@/lib/keyword-suggest";

/**
 * Czy wiersz wymagań to technologia (audyt 26.09.2026): każde słowo wiersza
 * jest nazwą albo aliasem ze słownika umiejętności (`/keywords/classify`,
 * jedno wywołanie na wiersz). Tylko takie wiersze są w „Szukaj ręcznie”
 * obowiązkowe; pozostałe („bankowość”, „narzędzia case”) tylko podnoszą
 * w kolejności — wszystkie wiersze naraz spełniało 39% osób, które zespół
 * potem wybrał.
 *
 * `false` = nie technologia (także wzorzec z gwiazdką — tego serwer nie
 * rozpozna), `null` = nie wiadomo (błąd, limit czasu): wiersz zostaje
 * obowiązkowy, jak przed zmianą. Słowo będące też nazwiskiem albo miastem
 * („Ruby”) serwer odrzuca — wiersz tylko podnosi, czyli nikogo nie wycina.
 */
export async function classifyRequirementRows(
  rows: readonly string[][],
): Promise<Array<boolean | null>> {
  return Promise.all(
    rows.map(async (row) => {
      if (row.some((word) => word.includes("*"))) return false;
      const result = await classifyKeywords(row.join(" "));
      return result === null ? null : result.as_requirements;
    }),
  );
}

/** Podział wierszy: obowiązkowe (technologie i „nie wiadomo”) i tylko podnoszące. */
export function splitRequirementRows(
  rows: readonly string[][],
  kinds: ReadonlyArray<boolean | null> | null,
): { required: string[][]; preferred: string[][] } {
  return {
    required: rows.filter((_, i) => kinds?.[i] !== false),
    preferred: rows.filter((_, i) => kinds?.[i] === false),
  };
}
