/**
 * Czysta logika panelu klienta: terminy, święta, czas Europe/Warsaw, etykiety.
 * Bez Reacta i bez sieci, żeby dało się ją sprawdzić testem.
 */
import { formatIsoDatePl } from "@/lib/date-pl";
import type {
  EvidenceItem,
  PanelCandidateState,
  PanelRate,
  PanelRequirement,
  RequirementStatus,
} from "@/lib/api/clientPanel";
import { warsawDateOf } from "@/lib/warsaw-date";

const TZ = "Europe/Warsaw";

export const MAX_SLOTS = 6;
export const SLOT_HOURS = [
  "09:00",
  "10:00",
  "11:00",
  "12:00",
  "13:00",
  "14:00",
  "15:00",
  "16:00",
] as const;
export const SLOT_DURATIONS = [60, 45, 30, 90] as const;
/** Terminy najwyżej tyle dni w przód: klient mówi o najbliższych dwóch tygodniach. */
const SLOT_HORIZON_DAYS = 14;

const WEEKDAYS = ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"] as const;
const MONTHS_GENITIVE = [
  "stycznia",
  "lutego",
  "marca",
  "kwietnia",
  "maja",
  "czerwca",
  "lipca",
  "sierpnia",
  "września",
  "października",
  "listopada",
  "grudnia",
] as const;

function ymdParts(ymd: string): [number, number, number] {
  const [y, m, d] = ymd.split("-").map(Number);
  return [y, m, d];
}

export function addDays(ymd: string, days: number): string {
  const [y, m, d] = ymdParts(ymd);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** 0 = poniedziałek, 6 = niedziela. */
export function weekdayIndex(ymd: string): number {
  const [y, m, d] = ymdParts(ymd);
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
}

function easterSunday(year: number): string {
  // Algorytm Meeusa/Jonesa/Butchera (kalendarz gregoriański).
  const a = year % 19;
  const b = Math.floor(year / 100);
  const c = year % 100;
  const d = Math.floor(b / 4);
  const e = b % 4;
  const f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3);
  const h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4);
  const k = c % 4;
  const l = (32 + 2 * e + 2 * i - h - k) % 7;
  const m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31);
  const day = ((h + l - 7 * m + 114) % 31) + 1;
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/**
 * Polskie święta ustawowe wypadające w dni tygodnia. Lustro
 * `core/scheduling.is_business_day` (biblioteka `holidays`); Wigilia wolna od 2025.
 */
export function polishHolidays(year: number): ReadonlySet<string> {
  const easter = easterSunday(year);
  const fixed = ["01-01", "01-06", "05-01", "05-03", "08-15", "11-01", "11-11", "12-25", "12-26"];
  if (year >= 2025) fixed.push("12-24");
  return new Set([
    ...fixed.map((day) => `${year}-${day}`),
    addDays(easter, 1), // Poniedziałek Wielkanocny
    addDays(easter, 60), // Boże Ciało
  ]);
}

export function isBusinessDay(ymd: string): boolean {
  if (weekdayIndex(ymd) >= 5) return false;
  return !polishHolidays(ymdParts(ymd)[0]).has(ymd);
}

export interface SlotDay {
  ymd: string;
  /** „Pn 09.11” */
  label: string;
  selectable: boolean;
  holiday: boolean;
}

export interface SlotWeek {
  monday: string;
  /** „9–13 listopada” */
  label: string;
  days: SlotDay[];
}

function dayLabel(ymd: string): string {
  const [, m, d] = ymdParts(ymd);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${WEEKDAYS[weekdayIndex(ymd)]} ${pad(d)}.${pad(m)}`;
}

function weekLabel(monday: string): string {
  const friday = addDays(monday, 4);
  const [, mondayMonth, mondayDay] = ymdParts(monday);
  const [, fridayMonth, fridayDay] = ymdParts(friday);
  return mondayMonth === fridayMonth
    ? `${mondayDay}–${fridayDay} ${MONTHS_GENITIVE[fridayMonth - 1]}`
    : `${mondayDay} ${MONTHS_GENITIVE[mondayMonth - 1]} – ${fridayDay} ${MONTHS_GENITIVE[fridayMonth - 1]}`;
}

/**
 * Tygodnie siatki terminów: od jutra przez kolejne 14 dni, poniedziałek–piątek.
 * Tydzień bez ani jednego dnia do wyboru (koniec tygodnia, same święta) znika.
 */
export function slotWeeks(today: string): SlotWeek[] {
  const first = addDays(today, 1);
  const last = addDays(today, SLOT_HORIZON_DAYS);
  const weeks: SlotWeek[] = [];
  for (
    let monday = addDays(first, -weekdayIndex(first));
    monday <= last;
    monday = addDays(monday, 7)
  ) {
    const days = [0, 1, 2, 3, 4].map((offset) => {
      const ymd = addDays(monday, offset);
      const business = isBusinessDay(ymd);
      return {
        ymd,
        label: dayLabel(ymd),
        selectable: business && ymd >= first && ymd <= last,
        holiday: !business,
      };
    });
    if (days.some((day) => day.selectable)) {
      weeks.push({ monday, label: weekLabel(monday), days });
    }
  }
  return weeks;
}

/** Klucz wybranego terminu: „2026-11-10T10:00” w czasie warszawskim. */
export type SlotKey = string;

export function slotKey(ymd: string, hour: string): SlotKey {
  return `${ymd}T${hour}`;
}

/** Nowa lista wybranych; siódmy termin nie wchodzi, klik w wybrany go zdejmuje. */
export function togglePicked(picked: readonly SlotKey[], key: SlotKey): SlotKey[] {
  if (picked.includes(key)) return picked.filter((item) => item !== key);
  if (picked.length >= MAX_SLOTS) return [...picked];
  return [...picked, key].sort();
}

function warsawOffsetMinutes(utcMs: number): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: TZ,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).formatToParts(new Date(utcMs));
  const value = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((part) => part.type === type)?.value);
  const local = Date.UTC(
    value("year"),
    value("month") - 1,
    value("day"),
    value("hour"),
    value("minute"),
  );
  return Math.round((local - utcMs) / 60_000);
}

/** „2026-11-10T10:00” (czas warszawski) → ISO z przesunięciem. Nie zależy od strefy przeglądarki. */
export function warsawLocalToIso(key: SlotKey): string {
  const [ymd, hour] = key.split("T");
  const [y, m, d] = ymdParts(ymd);
  const [hh, mm] = hour.split(":").map(Number);
  const naive = Date.UTC(y, m - 1, d, hh, mm);
  // Przesunięcie liczone dwa razy, bo pierwsze zgadnięcie może wypaść po
  // drugiej stronie zmiany czasu.
  const offset = warsawOffsetMinutes(naive - warsawOffsetMinutes(naive) * 60_000);
  const sign = offset >= 0 ? "+" : "-";
  const abs = Math.abs(offset);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${ymd}T${hour}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

/** „Wt 10.11, 10:00” z klucza. */
export function slotKeyLabel(key: SlotKey): string {
  const [ymd, hour] = key.split("T");
  return `${dayLabel(ymd)}, ${hour}`;
}

function warsawTime(iso: string): string {
  return new Intl.DateTimeFormat("pl-PL", {
    timeZone: TZ,
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

/** „Wt 10.11, 10:00”, a dla okna klienta „Wt 10.11, 09:00–12:00”. */
export function formatSlotLabel(start: string, windowEnd?: string | null): string {
  const ymd = warsawDateOf(start);
  if (!ymd) return "—";
  const range = windowEnd
    ? `${warsawTime(start)}–${warsawTime(windowEnd)}`
    : warsawTime(start);
  return `${dayLabel(ymd)}, ${range}`;
}

/** „DD.MM.RRRR” w kalendarzu firmy; `—`, gdy nie ma daty. */
export function formatPanelDate(value: string | null | undefined): string {
  return formatIsoDatePl(warsawDateOf(value));
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export function isValidEmail(value: string): boolean {
  return EMAIL.test(value.trim());
}

const UNIT_SUFFIX: Record<string, string> = { hourly: "/h", daily: "/MD", monthly: "/mies." };

/** „168,75 zł/h”; wartość nieczytelna daje `null`, nigdy „NaN zł”. */
export function formatRate(rate: PanelRate | null | undefined): string | null {
  if (!rate) return null;
  const value = Number(rate.value);
  if (!Number.isFinite(value)) return null;
  const amount = value.toLocaleString("pl-PL", {
    minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
    maximumFractionDigits: 2,
  });
  const currency = rate.currency === "PLN" ? "zł" : rate.currency;
  return `${amount} ${currency}${UNIT_SUFFIX[rate.unit] ?? ""}`;
}

export const STATUS_LABELS: Record<RequirementStatus, string> = {
  project: "w opisie projektu",
  list: "tylko na liście umiejętności",
  none: "nie ma w CV",
};

export const STATUS_GROUPS: readonly { status: RequirementStatus; title: string }[] = [
  { status: "project", title: "W opisie projektów" },
  { status: "list", title: "Tylko lista umiejętności lub certyfikat" },
  { status: "none", title: "Nie ma w CV" },
];

export type PillTone = "neutral" | "success" | "warning";

export const STATE_LABELS: Record<PanelCandidateState, { label: string; tone: PillTone | null }> = {
  none: { label: "bez decyzji", tone: null },
  question_open: { label: "Pytanie u opiekuna", tone: "warning" },
  answered: { label: "Odpowiedź od opiekuna", tone: "neutral" },
  interview_requested: { label: "Rozmowa: terminy wysłane", tone: "success" },
  interview_confirmed: { label: "Rozmowa potwierdzona", tone: "success" },
  not_fit: { label: "Nie pasuje", tone: "neutral" },
};

const GENERIC_WORDS = new Set([
  "rozwój",
  "technika",
  "technologie",
  "implementacja",
  "znajomość",
  "doświadczenie",
  "umiejętność",
  "praca",
  "aplikacji",
  "język",
  "języka",
]);
const SHORT_LABEL_LENGTH = 8;

/**
 * Nagłówek kolumny w macierzy, gdzie na 14 wymagań przy 1280 px jest ok. 50 px
 * na kolumnę. Pełna nazwa stoi w `title` komórki.
 */
export function shortRequirementLabel(label: string): string {
  const words = label
    .split(/[\s,]+/)
    .filter(Boolean)
    .filter((word) => /\p{L}/u.test(word));
  const word = words.find((item) => !GENERIC_WORDS.has(item.toLowerCase())) ?? words[0] ?? label;
  const capitalized = word.charAt(0).toUpperCase() + word.slice(1);
  return capitalized.length > SHORT_LABEL_LENGTH
    ? `${capitalized.slice(0, SHORT_LABEL_LENGTH - 1)}.`
    : capitalized;
}

export function candidatesCountLabel(count: number): string {
  return count === 1 ? "1 kandydat" : `${count} kandydatów`;
}

/** Wymagania, których nie ma w projektach: podpowiedzi w oknie pytania. */
export function questionHints(
  requirements: readonly PanelRequirement[],
  statuses: Record<string, RequirementStatus>,
): PanelRequirement[] {
  return requirements.filter((item) => statuses[item.key] !== "project").slice(0, 5);
}

export function questionFromHint(label: string): string {
  return `Czy kandydat pracował z: ${label}? W jakim projekcie?`;
}

/** Klik w dowód: najpierw fraza cytatu, a gdy jej nie ma w PDF-ie, samo słowo. */
export interface EvidenceSearch {
  quote: string;
  term: string;
  stage: "quote" | "term";
}

export function startEvidenceSearch(item: EvidenceItem): EvidenceSearch {
  return { quote: item.quote, term: item.term, stage: "quote" };
}

/** Słowo do drugiej próby; `null`, gdy szukanie jeszcze trwa albo już trafiło. */
export function evidenceFallback(
  search: EvidenceSearch | null,
  result: { total: number; pending: boolean },
): string | null {
  if (!search || result.pending || result.total > 0) return null;
  if (search.stage !== "quote" || !search.term.trim()) return null;
  return search.term;
}

const AUTHOR_KEY = "nexus.client-panel.author";

export interface StoredAuthor {
  name: string;
  email: string;
}

/** Pamięć przeglądarki bywa zablokowana; wtedy osoba wpisuje dane jeszcze raz. */
export function loadAuthor(): StoredAuthor {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(AUTHOR_KEY) ?? "null");
    if (parsed && typeof parsed === "object") {
      const { name, email } = parsed as Record<string, unknown>;
      return {
        name: typeof name === "string" ? name : "",
        email: typeof email === "string" ? email : "",
      };
    }
  } catch {
    // Bez pamięci formularz startuje pusty.
  }
  return { name: "", email: "" };
}

export function saveAuthor(author: StoredAuthor): void {
  try {
    window.localStorage.setItem(AUTHOR_KEY, JSON.stringify(author));
  } catch {
    // Jak wyżej: zapis jest tylko wygodą.
  }
}
