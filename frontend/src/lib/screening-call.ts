/**
 * Umówiony telefon na screening (decyzja Artura 03.11.2026): terminy liczone
 * w kalendarzu firmy i wywołania API. Reguły są w `services/screening_calls.py`.
 */

import api from "@/lib/api";
import { warsawToday } from "@/lib/warsaw-date";

export interface BookedCallSummary {
  event_id: number;
  start_time: string;
  note?: string | null;
  owner_id?: number | null;
  owner_name?: string | null;
  in_outlook?: boolean;
}

export type CallTone = "overdue" | "today" | "later";

export interface CallPreset {
  label: string;
  iso: string;
}

export type OutlookResult = "added" | "updated" | "not_connected" | "failed";

export interface ScreeningCallSaved {
  event_id: number;
  candidate_id: number;
  job_id: number;
  start_time: string;
  note?: string | null;
  status: string;
  outlook?: OutlookResult | null;
}

export const MAX_NOTE_LENGTH = 500;

const TZ = "Europe/Warsaw";
const WEEKDAYS = ["nd", "pon", "wt", "śr", "czw", "pt", "sob"];

function wallParts(moment: Date): { date: string; hour: number; minute: number } {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: TZ,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(moment);
  const read = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return { date: warsawToday(moment), hour: read("hour"), minute: read("minute") };
}

function addDays(date: string, days: number): string {
  const moment = new Date(`${date}T12:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + days);
  return moment.toISOString().slice(0, 10);
}

function weekdayIndex(date: string): number {
  return new Date(`${date}T12:00:00Z`).getUTCDay();
}

function nextWorkday(date: string): string {
  let next = addDays(date, 1);
  while (weekdayIndex(next) === 0 || weekdayIndex(next) === 6) next = addDays(next, 1);
  return next;
}

function offsetMinutes(moment: Date): number {
  const wall = wallParts(moment);
  const asUtc = Date.parse(`${wall.date}T${String(wall.hour).padStart(2, "0")}:${String(wall.minute).padStart(2, "0")}:00Z`);
  return Math.round((asUtc - Math.floor(moment.getTime() / 60000) * 60000) / 60000);
}

/** Chwila dla daty i godziny w kalendarzu firmy, niezależnie od strefy przeglądarki. */
export function warsawInstant(date: string, time: string): Date {
  const guess = new Date(`${date}T${time}:00Z`);
  const first = new Date(guess.getTime() - offsetMinutes(guess) * 60000);
  return new Date(guess.getTime() - offsetMinutes(first) * 60000);
}

function hhmm(moment: Date): string {
  const wall = wallParts(moment);
  return `${wall.hour}:${String(wall.minute).padStart(2, "0")}`;
}

/** „dziś 16:00”, „jutro 9:30”, „wczoraj 15:00”, „czw 10:00”, „12.11 10:00”. */
export function callWhen(iso: string, now: Date = new Date()): string {
  const moment = new Date(iso);
  const day = warsawToday(moment);
  const today = warsawToday(now);
  const time = hhmm(moment);
  if (day === today) return `dziś ${time}`;
  if (day === addDays(today, 1)) return `jutro ${time}`;
  if (day === addDays(today, -1)) return `wczoraj ${time}`;
  if (day > today && day < addDays(today, 7)) return `${WEEKDAYS[weekdayIndex(day)]} ${time}`;
  return `${day.slice(8, 10)}.${day.slice(5, 7)} ${time}`;
}

export function callTone(iso: string, now: Date = new Date()): CallTone {
  const moment = new Date(iso);
  if (moment.getTime() < now.getTime()) return "overdue";
  return warsawToday(moment) === warsawToday(now) ? "today" : "later";
}

function dayLabel(date: string, today: string): string {
  if (date === addDays(today, 1)) return "Jutro";
  const name = WEEKDAYS[weekdayIndex(date)];
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** Gotowe terminy: dziś po południu, jeśli jeszcze się da, i dwa kolejne dni pracy. */
export function callPresets(now: Date = new Date()): CallPreset[] {
  const today = warsawToday(now);
  const wall = wallParts(now);
  const presets: CallPreset[] = [];
  const workdayToday = weekdayIndex(today) !== 0 && weekdayIndex(today) !== 6;
  if (workdayToday && wall.hour * 60 + wall.minute < 15 * 60 + 30) {
    presets.push({ label: "Dziś 16:00", iso: warsawInstant(today, "16:00").toISOString() });
  }
  const first = nextWorkday(today);
  const second = nextWorkday(first);
  presets.push(
    { label: `${dayLabel(first, today)} 9:00`, iso: warsawInstant(first, "09:00").toISOString() },
    { label: `${dayLabel(first, today)} 16:00`, iso: warsawInstant(first, "16:00").toISOString() },
    { label: `${dayLabel(second, today)} 9:00`, iso: warsawInstant(second, "09:00").toISOString() },
  );
  return presets;
}

/** Zdanie po zapisie: termin i to, co wydarzyło się z Outlookiem. */
export function savedMessage(saved: ScreeningCallSaved, now: Date = new Date()): string {
  const when = callWhen(saved.start_time, now);
  if (saved.outlook === "failed") {
    return `Telefon: ${when}. Przypomnę 15 minut przed, ale Outlook nie przyjął wpisu.`;
  }
  if (saved.outlook === "added" || saved.outlook === "updated") {
    return `Telefon: ${when}, także w Outlooku. Przypomnę 15 minut przed.`;
  }
  return `Telefon: ${when}. Przypomnę 15 minut przed.`;
}

export const screeningCallsApi = {
  book: (body: {
    candidate_id: number;
    job_id: number;
    start: string;
    note: string | null;
    client_request_id: string;
  }) => api.post<ScreeningCallSaved>("/api/screening-calls", body).then((r) => r.data),
  reschedule: (eventId: number, body: { start: string; note: string | null }) =>
    api.put<ScreeningCallSaved>(`/api/screening-calls/${eventId}`, body).then((r) => r.data),
  cancel: (eventId: number) =>
    api.post<ScreeningCallSaved>(`/api/screening-calls/${eventId}/cancel`).then((r) => r.data),
};
