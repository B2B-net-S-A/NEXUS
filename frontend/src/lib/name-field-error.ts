/**
 * Odmowa serwera dla imienia albo nazwiska z dopiskiem w nawiasie
 * („[ACTIVE] Jan”, „(czarna lista)”) — od 13.10.2026 (decyzja D6) serwer
 * odpowiada 422 z błędem przy polu `name` / `lastname`. Zdanie serwera
 * pokazujemy przy polu, nie na górze okna (wzór `emailFieldError`).
 */
export interface NameFieldErrors {
  name: string | null;
  lastname: string | null;
}

export function nameFieldErrors(error: unknown): NameFieldErrors | null {
  const response = (
    error as { response?: { status?: unknown; data?: unknown } } | null | undefined
  )?.response;
  if (response?.status !== 422) return null;
  const detail = (response.data as { detail?: unknown } | null | undefined)?.detail;
  if (!Array.isArray(detail)) return null;
  const out: NameFieldErrors = { name: null, lastname: null };
  for (const item of detail) {
    const loc = (item as { loc?: unknown } | null)?.loc;
    const msg = (item as { msg?: unknown } | null)?.msg;
    if (!Array.isArray(loc) || loc[0] !== "body" || typeof msg !== "string") continue;
    const field: unknown = loc[loc.length - 1];
    if (field === "name") out.name = msg;
    else if (field === "lastname") out.lastname = msg;
  }
  return out.name || out.lastname ? out : null;
}
