/**
 * Numer telefonu do wyświetlenia: polska komórka w trójkach cyfr
 * („531898451” → „531 898 451”, „+48531898451” → „+48 531 898 451”) — prośba
 * rekruterek z 27.10.2026, bo ciąg dziewięciu cyfr źle się czyta przy
 * dyktowaniu i przepisywaniu.
 *
 * Tylko wyświetlanie: w bazie, w `tel:` i w schowku zostaje numer tak, jak
 * go zapisano. Czego nie rozpoznajemy na pewno (numer zagraniczny,
 * stacjonarny z inną liczbą cyfr, dwa numery w jednym polu, tekst), zwracamy
 * bez zmian — źle pogrupowany numer czytałby się gorzej niż surowy.
 */
export function formatPhone(raw: string): string {
  const value = raw.trim();
  if (!/^[\d\s()+./-]+$/.test(value)) return value;

  const plus = /^\(?\+/.test(value);
  const digits = value.replace(/\D/g, "");

  let national: string | null = null;
  if (!plus && digits.length === 9) national = digits;
  else if (plus && digits.length === 11 && digits.startsWith("48")) national = digits.slice(2);
  else if (!plus && digits.length === 13 && digits.startsWith("0048")) national = digits.slice(4);

  if (national == null) return value;
  const grouped = national.replace(/(\d{3})(\d{3})(\d{3})/, "$1 $2 $3");
  return national === digits ? grouped : `+48 ${grouped}`;
}
