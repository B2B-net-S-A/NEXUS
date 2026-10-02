// Zaproszenie na prep — podgląd tego, co dostanie kandydat.
//
// Tytuł i treść składa serwer (`backend/app/services/prep_invitation.py`);
// tu jest wyłącznie podstawienie pól formularza do podglądu. Moduł jest czysty
// (bez `@/lib/api`), bo testy okna mockują klienta API w całości.

/**
 * Tytuł i treść zaproszenia z serwera (`prep_invitation.py`). `body` niesie
 * pola `{note}` i `{organizer}` — podgląd podstawia je z formularza, a serwer
 * przy zapisie składa treść tą samą funkcją.
 */
export interface PrepInvitation {
  title: string;
  body: string;
  /** Akapit o terminie rozmowy — serwer pomija go, gdy prep nie jest przed rozmową. */
  interview_line?: string | null;
}

/** Podgląd treści zaproszenia dla bieżących wartości formularza. */
export function renderInvitationPreview(
  invitation: PrepInvitation,
  {
    note,
    organizer,
    beforeInterview,
  }: { note: string; organizer: string; beforeInterview: boolean },
): string {
  let body = invitation.body;
  if (invitation.interview_line && !beforeInterview) {
    body = body.replace(`\n\n${invitation.interview_line}`, "");
  }
  const extra = note.trim();
  // Funkcje zamiast napisów: `$&` w wiadomości nie może zadziałać jak wzorzec.
  return body
    .replace("\n\n{note}", () => (extra ? `\n\n${extra}` : ""))
    .replace("{organizer}", () => organizer);
}
