/**
 * Błąd walidacji pola e-mail z odpowiedzi 422 FastAPI → polskie zdanie przy
 * polu (runda 10, F05).
 *
 * Do 27.09.2026 formularz kandydata wypisywał na górze surowy tekst walidatora
 * („email: value is not a valid email address: The domain name … is a
 * special-use or reserved name …”), obok pola Imię — a w edycji trzeba było
 * przewinąć do góry, żeby go w ogóle zobaczyć. `null` = błąd nie dotyczy
 * e-maila (formularz pokazuje wtedy dotychczasowy baner).
 */
export function emailFieldError(error: unknown): string | null {
  const response = (
    error as { response?: { status?: unknown; data?: unknown } } | null | undefined
  )?.response;
  if (response?.status !== 422) return null;
  const detail = (response.data as { detail?: unknown } | null | undefined)?.detail;
  if (!Array.isArray(detail)) return null;
  const hit = detail.find((item) => {
    const loc = (item as { loc?: unknown } | null)?.loc;
    return Array.isArray(loc) && loc[0] === "body" && loc[loc.length - 1] === "email";
  }) as { msg?: unknown } | undefined;
  if (!hit) return null;
  const raw = typeof hit.msg === "string" ? hit.msg.toLowerCase() : "";
  if (raw.includes("special-use") || raw.includes("reserved")) {
    return "Ta domena jest zastrzeżona i nie przyjmuje poczty — wpisz prawdziwy adres e-mail.";
  }
  if (raw.includes("does not exist") || raw.includes("domain name")) {
    return "Domena w adresie e-mail wygląda na nieprawidłową — sprawdź część po „@”.";
  }
  return "Nieprawidłowy adres e-mail — sprawdź pisownię (np. jan.kowalski@firma.pl).";
}
