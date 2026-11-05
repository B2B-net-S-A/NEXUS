// Czyste reguły ekranów portalu (testy bez przeglądarki i bez API).

import type {
  PortalFaqItem,
  PortalMonth,
  PortalRate,
  PortalTopic,
  SettlementMode,
} from "@/lib/api/consultant-portal";

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

export function monthActionLabel(row: PortalMonth): string | null {
  if (row.action === "send_report") return "Wyślij raport";
  if (row.action === "send_invoice") return "Wyślij fakturę";
  return null;
}

const UNIT_LABELS: Record<string, string> = { hourly: "h", daily: "dzień", monthly: "miesiąc" };

/** „160,00 zł/h netto”: kwota po polsku, a waluta inna niż PLN zostaje kodem. */
export function rateLabel(rate: PortalRate | null): string | null {
  if (!rate) return null;
  const amount = Number(rate.amount).toLocaleString("pl-PL", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const currency = rate.currency === "PLN" ? "zł" : rate.currency;
  return `${amount} ${currency}/${UNIT_LABELS[rate.unit] ?? rate.unit} netto`;
}

/** „3 dni robocze przed startem”: pakiet klienta liczy termin względem startu. */
export function offsetLabel(days: number | null): string | null {
  if (days === null) return null;
  if (days === 0) return "w dniu startu";
  const count = Math.abs(days);
  const unit = count === 1 ? "dzień roboczy" : "dni robocze";
  return `${count} ${unit} ${days < 0 ? "przed startem" : "po starcie"}`;
}

export const SETTLEMENT_MODES: Record<SettlementMode, { label: string; intro: string; steps: string[] }> = {
  client_report: {
    label: "Raport od klienta",
    intro:
      "Nie wysyłasz raportu. Klient przekazuje nam godziny, a Ty wystawiasz fakturę na tyle godzin, ile zaakceptował.",
    steps: [
      "Klient przekazuje nam raport za miesiąc.",
      "Wystawiasz fakturę na godziny z raportu klienta.",
      "Fakturę dosyłasz w zakładce Faktury albo na adres rozliczeń.",
    ],
  },
  report_with_approval: {
    label: "Raport i akceptacja klienta",
    intro: "Sam zbierasz akceptację godzin u klienta i dołączasz ją do rozliczenia razem z raportem.",
    steps: [
      "Wgrywasz raport godzin razem z akceptacją klienta.",
      "Finanse sprawdzają dokumenty i dają znać.",
      "Wystawiasz fakturę na zaakceptowane godziny.",
    ],
  },
  own_report: {
    label: "Raport akceptowany przez B2B.net",
    intro: "Wysyłasz raport do nas. Finanse go sprawdzają i dają sygnał, że możesz wystawić fakturę.",
    steps: [
      "Wgrywasz raport godzin w zakładce Faktury.",
      "Finanse sprawdzają raport.",
      "Po naszym sygnale wystawiasz fakturę.",
    ],
  },
};

export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}
