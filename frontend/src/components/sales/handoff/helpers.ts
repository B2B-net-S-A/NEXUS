// Sprzedaż → przekazanie spotkania: podpisy i drobne decyzje ekranu.
// Reguły (fazy, kto może dać werdykt, liczby tygodni) są w backendzie: services/sales/handoff*.py.

import type { MyDayRow } from "@/lib/api/sales";
import type { BusySpan, Handoff, HandoffVerdict, HandoffWeek } from "@/lib/api/sales-handoffs";
import { formatDayMonthPl, weekdayOfIso, WEEKDAYS_PL } from "@/lib/date-pl";
import { localDay, manualStart, overlaps, spanOf } from "@/lib/interview-pick";

import { companyDayTime } from "../meeting-helpers";

export const VERDICT_LABELS: Record<HandoffVerdict, string> = {
  qualified: "Kwalifikuje się",
  not_now: "Nie teraz",
  not_a_fit: "Nie nasz klient",
  no_show: "Nie odbyło się",
};

export const VERDICT_HINTS: Record<HandoffVerdict, string> = {
  qualified: "→ Lead kwalifikowany",
  not_now: "→ wraca z datą",
  not_a_fit: "→ zamknięcie z powodem",
  no_show: "→ wraca do osoby, która umówiła",
};

export const VERDICT_ORDER: HandoffVerdict[] = ["qualified", "not_now", "not_a_fit", "no_show"];

export const DURATIONS = [30, 45, 60, 90] as const;
export const DEFAULT_DURATION = 30;

function nextDay(day: string): string {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

/** „dziś 09:30”, „jutro 10:00”, „czw 12.11 13:00”; bez terminu „bez terminu”. */
export function handoffWhen(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "bez terminu";
  const { day, time } = companyDayTime(iso);
  const today = companyDayTime(now).day;
  if (day === today) return `dziś ${time}`;
  if (day === nextDay(today)) return `jutro ${time}`;
  return `${WEEKDAYS_PL[weekdayOfIso(day)]} ${formatDayMonthPl(day)} ${time}`;
}

/** Druga linia wiersza: z kim jest spotkanie i kto je umówił. */
export function briefLine(handoff: Handoff, viewer: "host" | "booker"): string {
  const person = handoff.contact ? (handoff.contact.title ?? handoff.contact.name) : "bez osoby";
  const other =
    viewer === "host"
      ? handoff.booked_by && `od: ${handoff.booked_by.name}`
      : handoff.host && `prowadzi: ${handoff.host.name}`;
  return [person, handoff.service, other].filter(Boolean).join(" · ");
}

/** Co osoba, która umówiła spotkanie, widzi przy swoim wierszu. */
export function bookerStatus(handoff: Handoff): string {
  switch (handoff.verdict) {
    case "qualified":
      return VERDICT_LABELS.qualified;
    case "not_now":
      return handoff.return_on ? `Nie teraz, wraca ${formatDayMonthPl(handoff.return_on)}` : VERDICT_LABELS.not_now;
    case "not_a_fit":
      return handoff.verdict_reason ? `Nie nasz klient: ${handoff.verdict_reason}` : VERDICT_LABELS.not_a_fit;
    case "no_show":
      return "Nie odbyło się, umów ponownie";
    default:
      if (handoff.phase === "no_term") return "Bez terminu";
      if (handoff.phase === "verdict") return "Po terminie, czeka na werdykt";
      return handoff.confirmed_at ? "Termin potwierdzony" : "Czeka na spotkanie";
  }
}

/** „6 → 2 → 1”: umówione, odbyte, zakwalifikowane. */
export function weekFunnel(week: HandoffWeek): string {
  return `${week.booked} → ${week.held} → ${week.qualified}`;
}

export function weekLabel(week: HandoffWeek, index: number): string {
  if (index === 0) return "ten tydzień";
  if (index === 1) return "poprzedni";
  return `od ${formatDayMonthPl(week.week_start)}`;
}

/** Tygodnie do pokazania: bieżący i poprzedni zawsze, starsze tylko z liczbami. */
export function visibleWeeks(weeks: HandoffWeek[]): HandoffWeek[] {
  return weeks.filter((week, index) => index < 2 || week.booked + week.held + week.qualified > 0);
}

/** Chwila ISO z pól formularza (czas przeglądarki, jak w „Zaplanuj Prep”); bez dnia albo godziny `null`. */
export function termFromFields(day: string, time: string): string | null {
  if (!day || !time) return null;
  return manualStart(day, time);
}

/** Pola formularza z chwili ISO. */
export function fieldsFromTerm(iso: string | null): { day: string; time: string } {
  if (!iso) return { day: "", time: "" };
  const moment = new Date(iso);
  const pad = (value: number) => String(value).padStart(2, "0");
  return { day: localDay(moment), time: `${pad(moment.getHours())}:${pad(moment.getMinutes())}` };
}

const GRID_MINUTES = 30;
const WORK_START = 8 * 60;
const WORK_END = 18 * 60;

/** Wolne początki spotkania w dniu prowadzącego: siatka co 30 minut, 8:00–18:00, bez przeszłych. */
export function freeStarts(
  day: string,
  minutes: number,
  busy: BusySpan[],
  now: Date = new Date(),
  limit = 8,
): string[] {
  const out: string[] = [];
  for (let minute = WORK_START; minute + minutes <= WORK_END && out.length < limit; minute += GRID_MINUTES) {
    const time = `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
    const start = manualStart(day, time);
    if (!start || new Date(start).getTime() <= now.getTime()) continue;
    const span = spanOf(start, minutes);
    if (busy.some((block) => overlaps(span, block))) continue;
    out.push(time);
  }
  return out;
}

/** Data `RRRR-MM-DD` za `days` dni od dziś, w czasie przeglądarki. */
export function dayPlus(days: number, now: Date = new Date()): string {
  const date = new Date(now);
  date.setDate(date.getDate() + days);
  return localDay(date);
}

/** Wiersz „Mój dzień” dla panelu „Co dalej i kiedy” po werdykcie. */
export function planRow(handoff: Handoff): MyDayRow {
  return {
    key: `handoff-${handoff.opportunity.id}`,
    section: "meetings",
    company: handoff.company,
    opportunity: { id: handoff.opportunity.id, title: handoff.opportunity.name },
    activity_id: null,
    kind: null,
    subject: null,
    at: handoff.meeting_at ?? new Date().toISOString(),
    days: 0,
    amount: null,
    currency: "PLN",
    open_opportunities: 1,
    duration_minutes: handoff.duration_minutes,
    web_link: null,
    do_not_contact: false,
    person: null,
    people_without_phone: [],
  };
}

/** Sam adres do `mailto:`; adres z dopiskiem (`?bcc=…`, spacja) nie staje się odnośnikiem. */
export function mailAddress(email: string | null | undefined): string | undefined {
  const value = (email ?? "").trim();
  return /^[^\s?&#<>"]+@[^\s?&#<>"]+$/.test(value) ? value : undefined;
}

/** Mail do klienta z prośbą o potwierdzenie: otwiera program pocztowy, NEXUS niczego nie wysyła. */
export function confirmMailHref(handoff: Handoff): string | undefined {
  const email = mailAddress(handoff.contact?.email);
  if (!email || handoff.contact?.do_not_contact) return undefined;
  const when = handoffWhen(handoff.meeting_at);
  return `mailto:${email}?subject=${encodeURIComponent(`Potwierdzenie spotkania: ${when}`)}`;
}
