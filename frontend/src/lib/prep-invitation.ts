// Zaproszenie na prep — podgląd tego, co dostanie kandydat.
//
// Tytuł i treść składa serwer (`backend/app/services/prep_invitation.py`);
// tu jest wyłącznie podstawienie pól formularza do podglądu. Moduł jest czysty
// (bez `@/lib/api`), bo testy okna mockują klienta API w całości.

/**
 * Tytuł i treść zaproszenia z serwera (`prep_invitation.py`). `body` niesie
 * pola `{note}`, `{organizer}`, `{role}` i `{role_hint}` — podgląd podstawia
 * je z formularza, a serwer przy zapisie składa treść tą samą funkcją.
 */
export interface PrepInvitation {
  title: string;
  body: string;
  /** Akapit o terminie rozmowy — serwer pomija go, gdy prep nie jest przed rozmową. */
  interview_line?: string | null;
  /** Zdanie o opisie roli pod podpisem (26.10.2026); starszy serwer = brak. */
  role_hint?: string;
}

/** Podgląd treści zaproszenia dla bieżących wartości formularza. */
export function renderInvitationPreview(
  invitation: PrepInvitation,
  {
    note,
    organizer,
    beforeInterview,
    role = "",
    withRole = false,
  }: {
    note: string;
    organizer: string;
    beforeInterview: boolean;
    /** Stanowisko z okna; puste = zdanie bez „na stanowisko”. */
    role?: string;
    /** Opis roli idzie w zaproszeniu — w treści stoi zdanie o nim. */
    withRole?: boolean;
  },
): string {
  let body = invitation.body;
  if (invitation.interview_line && !beforeInterview) {
    body = body.replace(`\n\n${invitation.interview_line}`, "");
  }
  const extra = note.trim();
  const roleName = role.trim().split(/\s+/).join(" ");
  const hint = withRole && invitation.role_hint ? invitation.role_hint : "";
  // Funkcje zamiast napisów: `$&` w wiadomości nie może zadziałać jak wzorzec.
  return body
    .replace(" na stanowisko {role}", () => (roleName ? ` na stanowisko ${roleName}` : ""))
    .replace("\n\n{role_hint}", () => (hint ? `\n\n${hint}` : ""))
    .replace("\n\n{note}", () => (extra ? `\n\n${extra}` : ""))
    .replace("{organizer}", () => organizer);
}

/** Nagłówek sekcji pod podpisem — lustro `prep_invitation.role_section`. */
export function roleSectionHeading(role: string): string {
  const name = role.trim().split(/\s+/).join(" ");
  return name ? `O roli: ${name}` : "O roli";
}

// Lustro `prep_role._CODE_LIKE` (backend/app/services/prep_role.py): numery
// zapytań, kody stanowisk, „_” Nordei, „Replacement”. Rok to nie kod.
const CODE_LIKE = /#|_|\d{5,}|(?<![A-Za-z])(?:ZOB|RITM|PKN|EITE|PEP|TP)(?![A-Za-z])|replacement/i;
const LETTER = /\p{L}/u;

/** Stanowisko trzeba poprawić, zanim pójdzie do kandydata. */
export function looksLikeRoleCode(role: string): boolean {
  const text = role.trim();
  return !LETTER.test(text) || CODE_LIKE.test(text);
}
