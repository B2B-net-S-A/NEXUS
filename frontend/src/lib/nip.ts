/** Powód odrzucenia numeru z formularza klienta albo `null`, gdy numer jest dobry. */
const NIP_WEIGHTS = [6, 5, 7, 2, 3, 4, 5, 6, 7];
// Te same kształty co `order_client_identity.client_registry_number` na backendzie.
const EU_VAT = /^[A-Z]{2}[A-Z0-9+*]*$/;

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
  return EU_VAT.test(number) && digitCount >= 5
    ? null
    : "Wpisz NIP (10 cyfr) albo VAT UE z prefiksem kraju, np. FI12345678.";
}
