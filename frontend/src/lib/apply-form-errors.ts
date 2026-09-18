/**
 * Odmowa backendu z publicznego formularza aplikacyjnego → komunikat przy POLU.
 *
 * Audyt 18.09.2026: `detail` z FastAPI było wstawiane wprost do JSX. Dla błędu
 * walidacji `Form(...)` jest to TABLICA obiektów — React #31, granica błędu
 * zjada całą stronę, a kandydat traci wypełniony formularz RAZEM z załączonym
 * CV i nie dowiaduje się, że chodziło o adres e-mail.
 *
 * Rozbieżność, która to wywołuje, jest realna i nie znika po naprawie renderu:
 * zod 4 przyjmuje `jan@firma-.pl`, `EmailStr` po stronie backendu odrzuca.
 * Dlatego komunikat ma trafić PRZY POLU, a nie do zbiorczego banera — inaczej
 * kandydat czyta „popraw dane" i nie wie, które.
 */

/** Pola formularza, przy których umiemy postawić komunikat. */
const FIELD_LABELS: Record<string, string> = {
  first_name: "Imię",
  last_name: "Nazwisko",
  email: "E-mail",
  phone: "Telefon",
  linkedin: "LinkedIn",
  message: "Wiadomość",
  cv: "CV",
};

/** Zdania po polsku dla odmów, które backend opisuje po angielsku. */
function friendly(field: string, raw: string): string {
  const lowered = raw.toLowerCase();
  if (field === "email" && lowered.includes("email")) {
    return "Ten adres e-mail wygląda na niepoprawny — sprawdź, czy nie ma literówki.";
  }
  if (lowered.includes("field required")) {
    return `${FIELD_LABELS[field] ?? "To pole"} jest wymagane.`;
  }
  return raw;
}

export interface ApplyFieldError {
  field: string;
  message: string;
}

/**
 * Wyciąga błędy PÓL z ciała odpowiedzi 422.
 *
 * Bierzemy wyłącznie `loc[0] === "body"` — `query`/`path`/`header` ustawia kod
 * aplikacji, nie kandydat, więc nie ma przy czym postawić komunikatu i takie
 * odmowy zostają w zbiorczym banerze.
 */
export function applyFieldErrors(body: unknown): ApplyFieldError[] {
  if (!body || typeof body !== "object") return [];
  const { detail } = body as { detail?: unknown };
  if (!Array.isArray(detail)) return [];
  const out: ApplyFieldError[] = [];
  for (const item of detail) {
    const entry = item as { msg?: unknown; loc?: unknown } | null;
    if (!entry || typeof entry.msg !== "string") continue;
    const loc = Array.isArray(entry.loc) ? entry.loc : [];
    if (loc[0] !== "body") continue;
    const field = loc.slice(1).join(".");
    if (!field || !(field in FIELD_LABELS)) continue;
    out.push({ field, message: friendly(field, entry.msg) });
  }
  return out;
}
