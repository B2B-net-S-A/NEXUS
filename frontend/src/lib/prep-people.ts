// Kogo zaprosić na prep (17.10.2026, decyzja D1): każdego z NEXUSA albo
// dowolny adres e-mail. Do tej daty okno pokazywało zespół rekrutacji jako
// przyciski (u Nordei 13 osób) i nikogo spoza niego nie dało się dopisać.
//
// Czyste funkcje — komponent `PrepPeoplePicker` tylko rysuje.

import type { PrepPerson, PrepPersonOption } from "@/lib/api/prepMeetings";

/** Limit serwera: po 10 osób z NEXUSA i 10 adresów. */
export const MAX_INVITEES = 10;

export interface Invitees {
  userIds: number[];
  emails: string[];
}

export const NO_INVITEES: Invitees = { userIds: [], emails: [] };

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export function isEmailAddress(value: string): boolean {
  return EMAIL.test(value.trim());
}

/** Małe litery bez polskich znaków — „Łukasz” znajdzie się po „luk”. */
export function foldText(value: string): string {
  return value
    .toLowerCase()
    .replace(/ł/g, "l")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
}

/** Lista do wyboru; serwer sprzed 17.10.2026 nie zna `people` — wtedy zespół. */
export function invitablePeople(
  options: { people?: PrepPersonOption[]; team: PrepPerson[] } | undefined,
): PrepPersonOption[] {
  if (!options) return [];
  if (options.people && options.people.length > 0) return options.people;
  return options.team.map((p) => ({ ...p, role: null, in_team: true }));
}

/**
 * Osoby pasujące do wpisu: każde słowo wpisu to początek któregoś słowa
 * w nazwisku („ewa no” → „Ewa Nowicka”). Kolejność z serwera — zespół
 * rekrutacji pierwszy.
 */
export function searchPeople(
  people: readonly PrepPersonOption[],
  query: string,
  exclude: ReadonlySet<number>,
  limit = 8,
): PrepPersonOption[] {
  const words = foldText(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];
  return people
    .filter((p) => {
      if (exclude.has(p.id)) return false;
      const parts = foldText(p.name).split(/\s+/);
      return words.every((w) => parts.some((part) => part.startsWith(w)));
    })
    .slice(0, limit);
}

/** Podpowiedzi pod polem: DL rekrutacji i rekruter kandydata, jeśli ich nie ma. */
export function recommendedPeople(
  suggested: Record<string, PrepPerson | null> | undefined,
  people: readonly PrepPersonOption[],
  exclude: ReadonlySet<number>,
): PrepPersonOption[] {
  const ids = [suggested?.["1"]?.id, suggested?.["2"]?.id].filter(
    (id): id is number => id != null && !exclude.has(id),
  );
  return [...new Set(ids)]
    .map((id) => people.find((p) => p.id === id))
    .filter((p): p is PrepPersonOption => p != null);
}

export function addUser(value: Invitees, id: number): Invitees {
  if (value.userIds.includes(id) || value.userIds.length >= MAX_INVITEES) return value;
  return { ...value, userIds: [...value.userIds, id] };
}

export function removeUser(value: Invitees, id: number): Invitees {
  return { ...value, userIds: value.userIds.filter((u) => u !== id) };
}

export function addEmail(value: Invitees, raw: string): Invitees {
  const email = raw.trim();
  if (!isEmailAddress(email) || value.emails.length >= MAX_INVITEES) return value;
  if (value.emails.some((e) => e.toLowerCase() === email.toLowerCase())) return value;
  return { ...value, emails: [...value.emails, email] };
}

export function removeEmail(value: Invitees, email: string): Invitees {
  return { ...value, emails: value.emails.filter((e) => e !== email) };
}

export function sameInvitees(a: Invitees, b: Invitees): boolean {
  const ids = (v: Invitees) => [...v.userIds].sort((x, y) => x - y).join(",");
  const mails = (v: Invitees) =>
    v.emails
      .map((e) => e.toLowerCase())
      .sort()
      .join(",");
  return ids(a) === ids(b) && mails(a) === mails(b);
}

/** Zaproszeni istniejącego prepu → stan pola (osoby z NEXUSA po id, reszta po adresie). */
export function inviteesFromAttendees(
  attendees: readonly { email: string; user_id: number | null }[] | undefined,
): Invitees {
  const out: Invitees = { userIds: [], emails: [] };
  for (const a of attendees ?? []) {
    if (a.user_id != null) {
      if (!out.userIds.includes(a.user_id)) out.userIds.push(a.user_id);
    } else if (!out.emails.some((e) => e.toLowerCase() === a.email.toLowerCase())) {
      out.emails.push(a.email);
    }
  }
  return out;
}
