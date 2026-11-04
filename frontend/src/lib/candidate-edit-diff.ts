/**
 * Edycja kandydata wysyła WYŁĄCZNIE to, co użytkownik zmienił (runda 9, R9-N8-7).
 *
 * Okno „Edytuj” odsyłało pełny stan z chwili otwarcia — status, preferencje,
 * dni w biurze, dostępność i tagi. Zmiana wprowadzona w tym czasie przez kogoś
 * innego (np. czarna lista, stawka z telefonu, tag dodany przez kolegę) była
 * po cichu cofana starą wartością z formularza. Porównujemy więc ładunek
 * zbudowany z formularza z ładunkiem zbudowanym TĄ SAMĄ funkcją ze stanu
 * z otwarcia, a tagi idą pojedynczymi wywołaniami dodaj/usuń.
 */

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

/**
 * Pola, które się zmieniły. `preferences` backend scala płytko (klucz
 * nieobecny = bez zmian, `null` = usuń), więc idą tylko zmienione klucze.
 */
export function changedCandidateFields(
  initial: Record<string, unknown>,
  next: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(next)) {
    if (key === "preferences") {
      const before = (initial.preferences ?? {}) as Record<string, unknown>;
      const after = (value ?? {}) as Record<string, unknown>;
      const prefs: Record<string, unknown> = {};
      for (const prefKey of new Set([...Object.keys(before), ...Object.keys(after)])) {
        if (!same(before[prefKey], after[prefKey])) prefs[prefKey] = after[prefKey] ?? null;
      }
      if (Object.keys(prefs).length) out.preferences = prefs;
      continue;
    }
    if (!same(initial[key], value)) out[key] = value;
  }
  return out;
}

function splitTags(text: string): string[] {
  return text.split(",").map(t => t.trim()).filter(Boolean);
}

/**
 * Tagi-napisy dodane i usunięte względem stanu z otwarcia (bez wielkości liter,
 * tak jak porównuje serwer). Obiekty importu nie są edytowane w ogóle.
 */
export function tagChanges(
  initialText: string,
  nextText: string,
): { add: string[]; remove: string[] } {
  const before = splitTags(initialText);
  const after = splitTags(nextText);
  const beforeFolded = new Set(before.map(t => t.toLocaleLowerCase("pl")));
  const afterFolded = new Set(after.map(t => t.toLocaleLowerCase("pl")));
  const add: string[] = [];
  const seen = new Set<string>();
  for (const tag of after) {
    const folded = tag.toLocaleLowerCase("pl");
    if (!beforeFolded.has(folded) && !seen.has(folded)) {
      add.push(tag);
      seen.add(folded);
    }
  }
  const remove = before.filter(t => !afterFolded.has(t.toLocaleLowerCase("pl")));
  return { add, remove };
}
