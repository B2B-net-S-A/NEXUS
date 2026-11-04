// Czyste reguły ekranów portalu (testy bez przeglądarki i bez API).

import type { PortalFaqItem, PortalMonth, PortalTopic } from "@/lib/api/consultant-portal";

const WARSAW = "Europe/Warsaw";
const MONTHS = [
  "Styczeń",
  "Luty",
  "Marzec",
  "Kwiecień",
  "Maj",
  "Czerwiec",
  "Lipiec",
  "Sierpień",
  "Wrzesień",
  "Październik",
  "Listopad",
  "Grudzień",
];

export function monthLabel(year: number, month: number): string {
  return `${MONTHS[month - 1] ?? month} ${year}`;
}

export function formatDay(iso: string | null): string {
  if (!iso) return "—";
  const [year, month, day] = iso.split("T")[0].split("-");
  return `${day}.${month}.${year}`;
}

/** „jutro 09:30”: terminy zawsze w strefie firmy, a nie w strefie przeglądarki. */
export function slotLabel(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  const dayOf = (value: Date) =>
    new Intl.DateTimeFormat("sv-SE", { timeZone: WARSAW }).format(value);
  const clock = new Intl.DateTimeFormat("pl-PL", {
    timeZone: WARSAW,
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
  const tomorrow = new Date(now.getTime() + 24 * 60 * 60 * 1000);
  if (dayOf(date) === dayOf(now)) return `dziś ${clock}`;
  if (dayOf(date) === dayOf(tomorrow)) return `jutro ${clock}`;
  const day = new Intl.DateTimeFormat("pl-PL", {
    timeZone: WARSAW,
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
  }).format(date);
  return `${day} ${clock}`;
}

export function matchesFaq(item: PortalFaqItem, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const text = `${item.question} ${item.answer}`.toLowerCase();
  return words.every((word) => text.includes(word));
}

export interface FaqGroup {
  key: PortalTopic;
  label: string;
  items: PortalFaqItem[];
}

export function groupFaq(
  items: PortalFaqItem[],
  topics: { key: PortalTopic; label: string }[],
  query = "",
): FaqGroup[] {
  return topics
    .map((topic) => ({
      ...topic,
      items: items.filter((item) => item.topic === topic.key && matchesFaq(item, query)),
    }))
    .filter((group) => group.items.length > 0);
}

/** Tylko cyfry, najwyżej 6: telefon wkleja kod ze spacją albo z tekstem SMS-a. */
export function cleanCode(raw: string): string {
  return raw.replace(/\D/g, "").slice(0, 6);
}

export function monthActionLabel(row: PortalMonth): string | null {
  if (row.action === "send_report") return "Wyślij raport";
  if (row.action === "send_invoice") return "Wyślij fakturę";
  return null;
}

/** Sekcja finansów ma trzy stany, a awaria zapytania nie może wyglądać jak jeden z nich. */
export type FinanceView = "loading" | "error" | "unavailable" | "verify" | "open";

export function financeView(
  status: { available: boolean; verified: boolean } | undefined,
  { isError }: { isError: boolean },
): FinanceView {
  if (isError) return "error";
  if (!status) return "loading";
  if (!status.available) return "unavailable";
  return status.verified ? "open" : "verify";
}
