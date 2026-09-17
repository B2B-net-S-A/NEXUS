/**
 * Uczestnicy wpisywani ręcznie w formularzach kalendarza.
 *
 * „Nowe wydarzenie" dzieliło wpis tylko po przecinku, „Zaplanuj spotkanie"
 * po przecinku i średniku — adresy wklejone z Outlooka (spacje, nowe linie)
 * trafiały jako jeden „adres" i Graph odrzucał całe zaproszenie.
 */
const SEPARATORS = /[,;\s]+/;
// Celowo luźny: ma złapać literówkę („jan.kowalski@”), nie walidować RFC.
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function splitAttendeeEmails(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of raw.split(SEPARATORS)) {
    const email = part.trim();
    if (!email) continue;
    const key = email.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(email);
  }
  return out;
}

export function invalidAttendeeEmails(emails: string[]): string[] {
  return emails.filter((email) => !EMAIL.test(email));
}
