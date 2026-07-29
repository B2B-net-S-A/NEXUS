// Bezpiecznik przy dodawaniu notatki: wykrywa wklejkę formularza opisującą
// INNĄ osobę niż kandydat, którego profil jest otwarty (incydent 29.07.2026 —
// odpowiedź formularza o Marku Szczegodzińskim wklejona na profil Tomasza
// Jarząba; AI "Podsumowanie aktywności" wiernie streściło cudzy życiorys).
//
// Ostrzegamy WYŁĄCZNIE przy pełnym mismatchu (ani imię, ani nazwisko kandydata
// nie występują w polu "Imię i nazwisko:") — sam mismatch nazwiska na prodzie
// to w ~90% literówki, transliteracje i artefakty HTML tej samej osoby.

const POLISH_FOLD: Record<string, string> = {
  ą: "a",
  ć: "c",
  ę: "e",
  ł: "l",
  ń: "n",
  ó: "o",
  ś: "s",
  ź: "z",
  ż: "z",
};

function fold(value: string): string {
  return value
    .toLowerCase()
    .replace(/[ąćęłńóśźż]/g, (ch) => POLISH_FOLD[ch] ?? ch)
    .replace(/\s+/g, " ")
    .trim();
}

// Placeholdery z importu Traffit — kandydat bez realnego imienia/nazwiska
// nie daje podstawy do porównania (patrz backfill-names w traffit_sync).
const PLACEHOLDERS = new Set(["", "?", "nieznane", "nieznany", "brak", "-"]);

function usableToken(value?: string | null): string | null {
  const folded = fold(value ?? "");
  return PLACEHOLDERS.has(folded) ? null : folded;
}

const NAME_FIELD_RE = /imi[eę]\s+i\s+nazwisko\s*:\s*([^\n\r]+)/i;

/**
 * Zwraca osobę wymienioną w polu "Imię i nazwisko:" notatki, gdy NIE pasuje
 * ona do kandydata (pełny mismatch: ani imię, ani nazwisko). W pozostałych
 * przypadkach (brak pola, zgodność, placeholder zamiast danych kandydata,
 * artefakty HTML zamiast nazwiska) zwraca null.
 */
export function detectNotePersonMismatch(
  content: string,
  candidateName?: string | null,
  candidateLastname?: string | null,
): string | null {
  const match = NAME_FIELD_RE.exec(content ?? "");
  if (!match) return null;

  // Zdejmij tagi i encje HTML — na prodzie pole bywa opakowane w <strong>/<li>
  // i dosypane &nbsp;, co bez czyszczenia produkuje fałszywe mismatche.
  const mentionedRaw = match[1]
    .replace(/<[^>]*>/g, " ")
    .replace(/&[a-z#0-9]+;/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
  const mentioned = fold(mentionedRaw);
  // Pojedynczy token (samo imię, np. "Kateryna") nie identyfikuje innej osoby.
  if (!mentioned || !mentioned.includes(" ")) return null;

  const name = usableToken(candidateName);
  const lastname = usableToken(candidateLastname);
  // Bez realnych danych kandydata nie ma czego porównywać.
  if (!name && !lastname) return null;

  const nameMatches = name != null && mentioned.includes(name);
  const lastnameMatches = lastname != null && mentioned.includes(lastname);
  if (nameMatches || lastnameMatches) return null;

  return mentionedRaw.slice(0, 80);
}
