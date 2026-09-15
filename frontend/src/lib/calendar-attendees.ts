/**
 * Uczestnik wydarzenia z API kalendarza ma DWA kształty: tekst (wydarzenia
 * zakładane w NEXUS — pole „Uczestnicy” to lista adresów) albo obiekt
 * `{ address, name }` (synchronizacja M365, `services/m365/sync.py`).
 *
 * Do 15.09.2026 okno szczegółów renderowało wpis wprost — obiekt jako dziecko
 * Reacta wywracał CAŁY kalendarz („Coś poszło nie tak”, React #31) dla każdego
 * wydarzenia z uczestnikami z Outlooka, w tym wszystkich powiązanych z kandydatem.
 */
export type CalendarAttendee =
  | string
  | { address?: string | null; name?: string | null }
  | null
  | undefined;

/** Etykieta do wyświetlenia: imię i nazwisko, a bez niego adres; pusty wpis = null. */
export function attendeeLabel(attendee: CalendarAttendee): string | null {
  if (typeof attendee === "string") {
    const text = attendee.trim();
    return text || null;
  }
  if (attendee && typeof attendee === "object") {
    const name = typeof attendee.name === "string" ? attendee.name.trim() : "";
    const address = typeof attendee.address === "string" ? attendee.address.trim() : "";
    return name || address || null;
  }
  return null;
}

/** Adres do podpowiedzi (`title`), gdy etykietą jest imię i nazwisko. */
export function attendeeAddress(attendee: CalendarAttendee): string | null {
  if (typeof attendee === "string") return attendee.trim() || null;
  if (attendee && typeof attendee === "object" && typeof attendee.address === "string") {
    return attendee.address.trim() || null;
  }
  return null;
}
