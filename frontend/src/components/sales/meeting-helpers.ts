// Sprzedaż → Spotkania: daty w kalendarzu firmy i krótka nazwa firmy w wierszu.

const WARSAW = "Europe/Warsaw";

const PARTS = new Intl.DateTimeFormat("en-CA", {
  timeZone: WARSAW,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

interface LocalParts {
  year: string;
  month: string;
  day: string;
  time: string;
}

function localParts(moment: Date): LocalParts {
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    PARTS.formatToParts(moment).find((item) => item.type === type)?.value ?? "";
  return { year: part("year"), month: part("month"), day: part("day"), time: `${part("hour")}:${part("minute")}` };
}

function dayKey(parts: LocalParts): string {
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function nextDayKey(key: string): string {
  const date = new Date(`${key}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

/** Dzień `RRRR-MM-DD` i godzina `GG:MM` chwili ISO w kalendarzu firmy. */
export function companyDayTime(iso: string | Date): { day: string; time: string } {
  const parts = localParts(typeof iso === "string" ? new Date(iso) : iso);
  return { day: dayKey(parts), time: parts.time };
}

/** Czy chwila ISO to dziś w kalendarzu firmy. */
export function isMeetingToday(iso: string | null, now: Date = new Date()): boolean {
  return iso !== null && dayKey(localParts(new Date(iso))) === dayKey(localParts(now));
}

/** „Dziś 09:30”, „Jutro 10:00”, „13.11 10:00”, „12.08.2027 10:00”. */
export function meetingWhen(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "—";
  const moment = localParts(new Date(iso));
  const today = localParts(now);
  const key = dayKey(moment);
  if (key === dayKey(today)) return `Dziś ${moment.time}`;
  if (key === nextDayKey(dayKey(today))) return `Jutro ${moment.time}`;
  const day = `${moment.day}.${moment.month}`;
  return moment.year === today.year ? `${day} ${moment.time}` : `${day}.${moment.year} ${moment.time}`;
}

const LEGAL_FORMS: readonly [RegExp, string][] = [
  [/spółka z ograniczoną odpowiedzialnością/iu, "sp. z o.o."],
  [/spółka komandytowo-akcyjna/iu, "S.K.A."],
  [/spółka akcyjna/iu, "S.A."],
  [/spółka komandytowa/iu, "sp.k."],
  [/spółka jawna/iu, "sp.j."],
  [/spółka europejska/iu, "SE"],
];

/** „Firma SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ” → „Firma sp. z o.o.”. */
export function shortCompanyName(name: string): string {
  return LEGAL_FORMS.reduce((text, [form, short]) => text.replace(form, short), name);
}
