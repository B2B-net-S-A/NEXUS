// Nieobecność przy wzmiance „@” (17.10.2026, „Ludzie w NEXUSIE”) — czyste
// funkcje bez renderu.
//
// Lista „@” pokazuje przy osobie nieobecnej dziś krótki tekst „nieobecność do
// pt 23.10”, a po oznaczeniu takiej osoby z zastępcą pole podpowiada, żeby
// oznaczyć też zastępcę. Bez rodzaju nieobecności (D6): `/api/hr/leave/absence`
// go nie oddaje, plakietkę widzi każdy, kto może oznaczyć osobę.

import { dayLabel } from "@/components/hr/leave/leave-format";
import type { PersonAbsence } from "@/lib/api/hr-leave";
import type { ChatUserMini } from "@/types/job-chat";

/** Ten sam wzorzec co `mention_parser._EMAIL_RE` po stronie serwera. */
const MENTION_RE = /@([A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/g;

/** „nieobecność do pt 23.10”, „nieobecność dziś”, „nieobecność dziś (pół dnia)”. */
export function absenceShortText(
  absence: Pick<PersonAbsence, "until" | "half_day">,
  today: string,
): string {
  if (absence.until === today) {
    return absence.half_day ? "nieobecność dziś (pół dnia)" : "nieobecność dziś";
  }
  return `nieobecność do ${dayLabel(absence.until)}`;
}

/** Adresy oznaczone w tekście (małymi literami). */
export function mentionedEmails(text: string): Set<string> {
  const found = new Set<string>();
  for (const match of text.matchAll(MENTION_RE)) found.add(match[1].toLowerCase());
  return found;
}

export interface SubstituteHint {
  person: ChatUserMini;
  absence: PersonAbsence;
  substitute: ChatUserMini;
}

/**
 * Podpowiedź dla osoby `personId`: jest oznaczona w tekście, jest dziś
 * nieobecna i ma zastępcę, którego można oznaczyć, a jeszcze go nie oznaczono.
 */
export function substituteHint(
  text: string,
  personId: number,
  users: readonly ChatUserMini[],
  absences: ReadonlyMap<number, PersonAbsence>,
): SubstituteHint | null {
  const person = users.find((user) => user.id === personId);
  const absence = absences.get(personId);
  if (!person || !absence?.substitute_user_id) return null;
  const substitute = users.find((user) => user.id === absence.substitute_user_id);
  if (!substitute) return null;
  const mentioned = mentionedEmails(text);
  if (!mentioned.has(person.email.toLowerCase())) return null;
  if (mentioned.has(substitute.email.toLowerCase())) return null;
  return { person, absence, substitute };
}

/** „Kamil Wiśniewski — nieobecność do pt 23.10. Oznaczyć też zastępcę (Ola Nowak)?” */
export function substituteHintText(hint: SubstituteHint, today: string): string {
  return `${hint.person.name} — ${absenceShortText(hint.absence, today)}. Oznaczyć też zastępcę (${hint.substitute.name})?`;
}

/**
 * Wstawia `@zastępca` zaraz po ostatniej wzmiance osoby (bez niej — na końcu).
 * Zwraca nowy tekst i miejsce kursora za wstawką.
 */
export function insertAfterMention(
  text: string,
  personEmail: string,
  substituteEmail: string,
): { text: string; caret: number } {
  const wanted = personEmail.toLowerCase();
  let point = -1;
  for (const match of text.matchAll(MENTION_RE)) {
    if (match[1].toLowerCase() === wanted && match.index !== undefined) {
      point = match.index + match[0].length;
    }
  }
  if (point < 0) {
    const sep = text === "" || /\s$/.test(text) ? "" : " ";
    const next = `${text}${sep}@${substituteEmail} `;
    return { text: next, caret: next.length };
  }
  const after = text.slice(point);
  const insertion = ` @${substituteEmail}` + (/^\s/.test(after) ? "" : " ");
  return {
    text: text.slice(0, point) + insertion + after,
    caret: point + insertion.length,
  };
}
