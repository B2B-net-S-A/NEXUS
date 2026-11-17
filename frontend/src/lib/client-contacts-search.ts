// Wyszukiwanie w „Kontaktach klienta” (17.11.2026). U PKO BP jest 88 osób,
// u Nordei 103 — bez filtra DL przewija całą listę, żeby znaleźć jedną osobę.
// Filtr działa w przeglądarce na już pobranej liście: lista klienta to
// najwyżej ok. 100 wierszy, nowe API nie jest potrzebne.

import { foldText } from "@/lib/prep-people";

export interface SearchableContact {
  name: string;
  email: string | null;
  phone: string | null;
  position: string | null;
  department: string | null;
  notes: string | null;
  relationship_notes: string | null;
}

const digitsOnly = (value: string): string => value.replace(/\D/g, "");

/**
 * Czy kontakt pasuje do wpisanego tekstu. Każde słowo zapytania musi wystąpić
 * w którymś polu („kowal test” znajdzie Kowalską z działu testów), bez
 * polskich znaków („mozejko” → „Możejko”). Numer telefonu porównujemy po
 * samych cyfrach, bo w bazie bywa „600 833 277” i „600833277”.
 */
export function contactMatches(contact: SearchableContact, query: string): boolean {
  const words = foldText(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = foldText(
    [
      contact.name,
      contact.email,
      contact.position,
      contact.department,
      contact.notes,
      contact.relationship_notes,
    ]
      .filter(Boolean)
      .join(" "),
  );
  const phone = contact.phone ? digitsOnly(contact.phone) : "";
  return words.every((word) => {
    if (haystack.includes(word)) return true;
    const digits = digitsOnly(word);
    return digits.length >= 3 && digits.length === word.length && phone.includes(digits);
  });
}
