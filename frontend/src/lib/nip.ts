/** Powód odrzucenia numeru z formularza klienta albo `null`, gdy numer jest dobry. */
const NIP_WEIGHTS = [6, 5, 7, 2, 3, 4, 5, 6, 7];
// Te same kształty co `order_client_identity.client_registry_number` na backendzie.
const FOREIGN_ID = /^[A-Z]{2}[A-Z0-9+*]*$/;

function compact(value: string): string {
  return value.toUpperCase().replace(/[\s.\- ]/g, "");
}

export function normalizedNip(value: string): string {
  const number = compact(value);
  return /^PL\d+$/.test(number) ? number.slice(2) : number;
}

export function nipProblem(value: string): string | null {
  const number = normalizedNip(value);
  if (!number) return null;
  if (/^\d+$/.test(number)) {
    if (number.length !== 10) return "NIP ma 10 cyfr.";
    const digits = [...number].map(Number);
    const control = NIP_WEIGHTS.reduce((sum, weight, i) => sum + weight * digits[i], 0) % 11;
    return control === digits[9] && control !== 10
      ? null
      : "Ten NIP ma niepoprawną sumę kontrolną.";
  }
  const digitCount = number.replace(/\D/g, "").length;
  return FOREIGN_ID.test(number) && digitCount >= 5
    ? null
    : "Wpisz NIP (10 cyfr), VAT UE albo inny identyfikator z prefiksem kraju.";
}

/** Zapytanie, które jest samym polskim NIP-em („734-286-71-48”, „PL7342867148”), albo `null`. */
export function nipFromQuery(value: string): { nip: string; valid: boolean } | null {
  const number = normalizedNip(value);
  if (!/^\d{10}$/.test(number)) return null;
  return { nip: number, valid: nipProblem(number) === null };
}

/** „7342867148” → „734-286-71-48”. */
export function formatNip(nip: string): string {
  return `${nip.slice(0, 3)}-${nip.slice(3, 6)}-${nip.slice(6, 8)}-${nip.slice(8)}`;
}
