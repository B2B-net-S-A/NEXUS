/**
 * Numer telefonu do wyświetlenia: polska komórka w trójkach cyfr
 * („600100200” → „600 100 200”, „+48600100200” → „+48 600 100 200”) — prośba
 * rekruterek z 27.10.2026, bo ciąg dziewięciu cyfr źle się czyta przy
 * dyktowaniu i przepisywaniu. „48514641516” (kierunkowy bez plusa, 83% numerów
 * list dzwonienia 27.11.2026) to też polski numer: „+48 514 641 516”.
 *
 * Tylko wyświetlanie: w bazie i w `tel:` zostaje numer tak, jak go zapisano.
 * Czego nie rozpoznajemy na pewno (numer zagraniczny, stacjonarny z inną
 * liczbą cyfr, dwa numery w jednym polu, tekst), zwracamy bez zmian — źle
 * pogrupowany numer czytałby się gorzej niż surowy.
 */
export function formatPhone(raw: string): string {
  const value = raw.trim();
  const parsed = polishNumber(value);
  if (parsed == null) return value;
  const grouped = parsed.national.replace(/(\d{3})(\d{3})(\d{3})/, "$1 $2 $3");
  return parsed.prefixed ? `+48 ${grouped}` : grouped;
}

/**
 * Numer do schowka, z którego osoba dzwoni z telefonu: polski numer zawsze
 * jako „+48XXXXXXXXX”, bo „48XXXXXXXXX” bez plusa telefon wybiera jak numer
 * krajowy i połączenie nie wychodzi. Resztę zwracamy tak, jak ją zapisano.
 */
export function dialablePhone(raw: string): string {
  const value = raw.trim();
  const parsed = polishNumber(value);
  return parsed == null ? value : `+48${parsed.national}`;
}

function polishNumber(value: string): { national: string; prefixed: boolean } | null {
  if (!/^[\d\s()+./-]+$/.test(value)) return null;
  const plus = /^\(?\+/.test(value);
  const digits = value.replace(/\D/g, "");
  if (!plus && digits.length === 9) return { national: digits, prefixed: false };
  if (digits.length === 11 && digits.startsWith("48")) return { national: digits.slice(2), prefixed: true };
  if (!plus && digits.length === 13 && digits.startsWith("0048")) return { national: digits.slice(4), prefixed: true };
  return null;
}
