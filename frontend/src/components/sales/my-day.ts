// Sprzedaż → „Mój dzień”: podpisy i proste decyzje ekranu. Reguły kolejki są w backendzie
// (services/sales/my_day.py), tu nic się nie liczy.

import type { MyDay, MyDayPerson, MyDayPrepEntry, MyDayRow } from "@/lib/api/sales";
import { weekdayOfIso } from "@/lib/date-pl";

import { daysLabel } from "./format";

export const OFFERS_PREVIEW = 10;

export type SalesSearchParams = Record<string, string | string[] | undefined>;

/** Dokąd prowadzi `/sales`: z parametrami to stary odnośnik do Szans, bez nich „Mój dzień”. */
export function salesLandingPath(params: SalesSearchParams): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    for (const item of Array.isArray(value) ? value : value === undefined ? [] : [value]) {
      query.append(key, item);
    }
  }
  const text = query.toString();
  return text ? `/sales/opportunities?${text}` : "/sales/my-day";
}

const WEEKDAYS = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"];

/** „1 spotkanie”, „2 zaległe”, „16 ofert bez ruchu”. */
export function plural(n: number, one: string, few: string, many: string): string {
  const tens = n % 100;
  const units = n % 10;
  if (n === 1) return `${n} ${one}`;
  return `${n} ${units >= 2 && units <= 4 && (tens < 12 || tens > 14) ? few : many}`;
}

/** „Poniedziałek 9.11” z daty kalendarza firmy, bez przeliczania strefy przeglądarki. */
export function dayHeading(iso: string): string {
  const [, month, day] = iso.split("-").map(Number);
  return `${WEEKDAYS[weekdayOfIso(iso)]} ${day}.${month}`;
}

export function dayLine(day: MyDay): string {
  const { meetings, reply, overdue, offers } = day.counts;
  return [
    plural(meetings, "spotkanie", "spotkania", "spotkań"),
    `${reply} do odpisania`,
    plural(overdue, "zaległy", "zaległe", "zaległych"),
    plural(offers, "oferta bez ruchu", "oferty bez ruchu", "ofert bez ruchu"),
  ].join(" · ");
}

export function isDayEmpty(day: MyDay): boolean {
  return (
    day.meetings.length === 0 &&
    day.reply.length === 0 &&
    day.overdue.length === 0 &&
    day.offers.length === 0
  );
}

/** Numer do linku `tel:`: same cyfry i plus, bez numeru wewnętrznego. */
export function telHref(numer: string): string {
  return `tel:${numer.split(/wew/i)[0].replace(/[^\d+]/g, "")}`;
}

export function clock(iso: string, timeZone = "Europe/Warsaw"): string {
  return new Date(iso).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit", timeZone });
}

/** „09:30–10:00”; bez czasu trwania sama godzina początku. */
export function meetingSpan(at: string, minutes: number | null): string {
  if (!minutes) return clock(at);
  return `${clock(at)}–${clock(new Date(Date.parse(at) + minutes * 60_000).toISOString())}`;
}

function deals(count: number): string {
  if (count === 0) return "brak otwartej szansy";
  return plural(count, "otwarta szansa", "otwarte szanse", "otwartych szans");
}

/** Powód w drugim wierszu; dla zaległych czerwony początek dokleja wiersz. */
export function rowReason(row: MyDayRow): string {
  switch (row.section) {
    case "meetings":
      return [row.duration_minutes ? `${row.duration_minutes} min` : null, deals(row.open_opportunities)]
        .filter(Boolean)
        .join(" · ");
    case "reply":
      return [`Napisali ${daysLabel(row.days)} temu`, row.opportunity?.title].filter(Boolean).join(" · ");
    case "overdue":
      return `${row.kind === "call" ? "Telefon: " : ""}${row.subject ?? "Krok bez opisu"}`;
    case "offers":
      return `Bez ruchu ${daysLabel(row.days)} · ${row.subject ?? ""}`;
  }
}

export function replyHref(row: MyDayRow, safeLink: string | undefined): string | undefined {
  if (safeLink) return safeLink;
  const email = row.person?.email;
  if (!email) return undefined;
  return `mailto:${email}?subject=${encodeURIComponent(row.subject ?? "")}`;
}

const HISTORY_KIND: Record<MyDayPrepEntry["kind"], string> = {
  call: "Telefon",
  email: "Mail",
  meeting: "Spotkanie",
  note: "Notatka",
  task: "Zadanie",
};

export function historyHeadline(entry: MyDayPrepEntry, companyName: string): string {
  if (entry.kind === "email" && entry.direction === "in") return `Mail od ${companyName}`;
  if (entry.kind === "email" && entry.direction === "out") return "Mail od nas";
  return HISTORY_KIND[entry.kind];
}

export function personLabel(person: MyDayPerson): string {
  return person.title ? `${person.name}, ${person.title}` : person.name;
}
