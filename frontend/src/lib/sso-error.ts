/**
 * Tłumaczenie kodów błędów logowania Microsoft SSO na komunikaty dla człowieka.
 *
 * Backend (`backend/app/api/auth_microsoft.py`) przekierowuje nieudane logowanie
 * na `/login?error=<kod>`. Kody są stabilne i maszynowe (`account_disabled`,
 * `state_expired`, ...) — tu zamieniamy je na polskie zdanie, które mówi
 * użytkownikowi CO ZROBIĆ, a nie tylko że się nie udało.
 *
 * Wsteczna zgodność: starsze wydania backendu wysyłały surowe angielskie zdania
 * ("Account disabled", "Missing identity claims", "Microsoft sign-in failed.").
 * Taki link może jeszcze wisieć w zakładce albo być w locie w trakcie deployu,
 * więc każde mapowanie łapie zarówno nowy kod, jak i stary tekst.
 */

interface SsoErrorRule {
  /** Nowy, stabilny kod z backendu (dopasowanie dokładne, case-insensitive). */
  code: string
  /** Fragmenty starych, surowych komunikatów (dopasowanie po podciągu). */
  legacy: string[]
  message: string
}

const RULES: SsoErrorRule[] = [
  {
    code: "account_disabled",
    legacy: ["account disabled"],
    message:
      "Twoje konto w NEXUS jest nieaktywne — poproś administratora o jego włączenie.",
  },
  {
    code: "domain_forbidden",
    legacy: [],
    message:
      "Twoja domena email nie jest dopuszczona do logowania przez Microsoft. Skontaktuj się z administratorem.",
  },
  {
    code: "foreign_tenant",
    legacy: [],
    message:
      "To konto Microsoft nie należy do organizacji firmy. Zaloguj się kontem firmowym.",
  },
  {
    code: "identity_mismatch",
    legacy: [],
    message:
      "To konto NEXUS jest przypisane do innej tożsamości Microsoft. Poproś administratora o sprawdzenie konta.",
  },
  {
    code: "missing_identity_claims",
    legacy: ["missing identity claims"],
    message:
      "Microsoft nie zwrócił wymaganych danych identyfikacyjnych. Spróbuj ponownie.",
  },
  {
    code: "state_expired",
    legacy: ["state expired"],
    message:
      "Sesja logowania wygasła. Kliknij ponownie „Zaloguj się przez Microsoft”.",
  },
  {
    code: "missing_code_state",
    legacy: ["missing code/state"],
    message:
      "Logowanie przez Microsoft wróciło niekompletne. Kliknij ponownie „Zaloguj się przez Microsoft”.",
  },
  {
    // Zbiorczy kod na błąd po stronie Microsoftu i na nieudaną wymianę kodu na
    // token — backend celowo nie wynosi szczegółów do URL-a (idą do Sentry).
    code: "microsoft_sign_in_failed",
    legacy: ["microsoft sign-in failed", "token exchange failed", "access_denied"],
    message:
      "Logowanie przez Microsoft nie powiodło się. Spróbuj ponownie — jeśli to się powtarza, zgłoś administratorowi.",
  },
  {
    code: "aad_no_role",
    legacy: ["nie ma przypisanej roli w microsoft ad"],
    message:
      "Twoje konto nie ma przypisanej roli w Microsoft AD — poproś administratora o dodanie Cię do właściwej grupy.",
  },
  {
    code: "aad_no_graph_token",
    legacy: ["aad rbac misconfigured"],
    message:
      "Logowanie przez Microsoft jest źle skonfigurowane po stronie NEXUS (brak zgody na odczyt grup AD). Zgłoś to administratorowi.",
  },
  {
    code: "aad_group_lookup_failed",
    legacy: ["aad group lookup failed", "microsoft role lookup failed"],
    message:
      "Nie udało się sprawdzić Twoich grup w Microsoft AD. Spróbuj ponownie lub zgłoś administratorowi.",
  },
  {
    code: "aad_role_map_invalid",
    legacy: ["aad role mapping misconfigured"],
    message:
      "Mapowanie grup Microsoft AD na role w NEXUS jest niepoprawne. Zgłoś to administratorowi.",
  },
  {
    code: "aad_role_invalid",
    legacy: ["aad role mapping is invalid"],
    message:
      "Rola przypisana Twojej grupie Microsoft AD nie istnieje w NEXUS. Zgłoś to administratorowi.",
  },
  {
    code: "last_active_admin_blocked",
    legacy: ["at least one active administrator must remain"],
    message:
      "Zmiana roli z Microsoft AD została wstrzymana — w NEXUS musi zostać co najmniej jeden aktywny administrator. Zgłoś to administratorowi.",
  },
  {
    // Ustawiany przez proxy `app/auth/microsoft/callback/route.ts`, gdy backend
    // jest nieosiągalny i nie ma czego przekazać dalej.
    code: "backend_unreachable",
    legacy: ["logowanie przez microsoft nie powiodło się — spróbuj ponownie."],
    message:
      "Logowanie przez Microsoft nie powiodło się — NEXUS był nieosiągalny. Spróbuj ponownie za chwilę.",
  },
]

/**
 * Zamienia `?error=` z URL-a na polski komunikat.
 *
 * Zwraca `null`, gdy parametru nie ma. Nieznany kod (np. z nowszego backendu)
 * wraca jako zdekodowany tekst — lepiej pokazać surowe „coś", niż zjeść błąd.
 */
export function ssoErrorMessage(rawCode: string | null | undefined): string | null {
  if (!rawCode) return null
  const code = rawCode.toLowerCase()
  const hit = RULES.find(
    (rule) => code === rule.code || rule.legacy.some((frag) => code.includes(frag)),
  )
  if (hit) return hit.message
  try {
    return decodeURIComponent(rawCode)
  } catch {
    // Uszkodzone procentowe kodowanie (`%E0%A4%A`) wywala decodeURIComponent —
    // pokaż surowy parametr zamiast wysypać cały ekran logowania.
    return rawCode
  }
}
