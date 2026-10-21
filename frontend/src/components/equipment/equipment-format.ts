// Etykiety i czyste funkcje modułu „Sprzęt” (testowane bez renderowania).

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  AssignmentRow,
  EquipmentCategory,
  EquipmentHolderKind,
  EquipmentItem,
  EquipmentItemStatus,
  EquipmentModel,
  EquipmentProvider,
  EquipmentTask,
  EquipmentTaskKind,
  ImportDecision,
  ProtocolStatus,
  ReturnCondition,
  SignatureMethod,
} from "@/lib/api/equipment";
import { WEEKDAYS_PL, formatDayMonthPl, formatIsoDatePl, weekdayOfIso } from "@/lib/date-pl";
import { formatPlnDocument } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";

export const CATEGORY_LABELS: Record<EquipmentCategory, string> = {
  laptop: "Laptop",
  telefon: "Telefon",
  monitor: "Monitor",
  karta_sim: "Karta SIM",
  karta_dostepu: "Karta dostępu",
  akcesorium: "Akcesorium",
  inne: "Inne",
};

/**
 * Gdzie szukać kodów, których NEXUS nie przechowuje (Artur 18.10.2026): klucz
 * odzyskiwania BitLocker zostaje w Intune/Entra, PIN i PUK karty SIM u operatora.
 * Ewidencja pokazuje tylko drogę do nich.
 */
export interface SecretHint {
  label: string;
  text: string;
  href?: string;
}

export function secretHint(category: EquipmentCategory): SecretHint | null {
  if (category === "laptop") {
    return {
      label: "Klucz odzyskiwania BitLocker",
      text: "Intune → Urządzenia → Wszystkie urządzenia → ten komputer → Klucze odzyskiwania (albo Entra → Urządzenia → Klucze BitLocker).",
      href: "https://intune.microsoft.com/",
    };
  }
  if (category === "karta_sim" || category === "telefon") {
    return {
      label: "PIN i PUK karty SIM",
      text: "U operatora: panel firmowy operatora albo opiekun biznesowy, po numerze telefonu.",
    };
  }
  return null;
}

export const CATEGORY_ORDER: EquipmentCategory[] = [
  "laptop",
  "telefon",
  "monitor",
  "karta_sim",
  "karta_dostepu",
  "akcesorium",
  "inne",
];

export const ITEM_STATUS_LABELS: Record<EquipmentItemStatus, string> = {
  na_stanie: "Na stanie",
  wydany: "Wydany",
  serwis: "W serwisie",
  wycofany: "Wycofany",
  zgubiony: "Zgubiony",
};

export const ITEM_STATUS_TONE: Record<EquipmentItemStatus, StatusDotTone> = {
  na_stanie: "success",
  wydany: "info",
  serwis: "warning",
  wycofany: "neutral",
  zgubiony: "danger",
};

export const CONDITION_LABELS: Record<ReturnCondition, string> = {
  sprawny: "Sprawny",
  uszkodzony: "Uszkodzony (do serwisu)",
  niekompletny: "Niekompletny",
  zgubiony: "Zgubiony (brak zwrotu)",
};

export const PROTOCOL_STATUS_LABELS: Record<ProtocolStatus, string> = {
  oczekuje: "Czeka na podpis",
  podpisany: "Podpisany — do potwierdzenia",
  potwierdzony: "Potwierdzony",
  anulowany: "Anulowany",
};

export const PROTOCOL_STATUS_TONE: Record<ProtocolStatus, StatusDotTone> = {
  oczekuje: "warning",
  podpisany: "info",
  potwierdzony: "success",
  anulowany: "neutral",
};

export const SIGNATURE_LABELS: Record<SignatureMethod, string> = {
  brak: "—",
  link: "Link",
  papier: "Papier",
  profil_zaufany: "Profil zaufany",
};

export const TASK_KIND_LABELS: Record<EquipmentTaskKind, string> = {
  wydanie: "Przygotuj",
  zwrot: "Zwrot",
  podpis: "Podpis",
  zakup: "Zakup",
};

export const DECISION_LABELS: Record<ImportDecision, string> = {
  przyjmij: "Do przyjęcia",
  do_wyjasnienia: "Do wyjaśnienia",
  konflikt: "Konflikt",
  pomin: "Pominięte",
};

export const HOLDER_KIND_LABELS: Record<EquipmentHolderKind, string> = {
  user: "Konsultant/kontraktor",
  contract: "Kontraktor",
  external: "Spoza NEXUSA",
  academy: "Uczestnik Akademii",
};

export const PROVIDER_LABELS: Record<EquipmentProvider, string> = {
  nasz: "Sprzęt od nas",
  klienta: "Sprzęt od klienta",
  nieznany: "Nie wiadomo",
};

/** Kategorie bez wartości w protokole (decyzja D6). */
export function isNoValueCategory(category: EquipmentCategory): boolean {
  return category === "karta_sim" || category === "karta_dostepu";
}

/** „500000077” → „+48 500 000 077”. */
export function phoneDisplay(digits: string | null | undefined): string | null {
  if (!digits) return null;
  if (!/^\d{9}$/.test(digits)) return digits;
  return `+48 ${digits.slice(0, 3)} ${digits.slice(3, 6)} ${digits.slice(6)}`;
}

type Identified = Pick<
  EquipmentItem,
  | "category"
  | "inventory_number"
  | "serial_number"
  | "imei"
  | "phone_number"
  | "access_card_number"
>;

/**
 * Nazwa pozycji na ekranie: laptop, telefon, monitor i karty z nazwą rodzaju
 * („Laptop Dell Vostro…”), akcesorium i inne samą nazwą modelu („Słuchawki
 * Jabra…”) — jak w protokole recepcji.
 */
export function itemTitle(item: Pick<EquipmentItem, "category" | "model">): string {
  if (item.category === "akcesorium" || item.category === "inne") return item.model.name;
  return `${CATEGORY_LABELS[item.category]} ${item.model.name}`;
}

/** Numer, po którym recepcja zna pozycję (ewidencyjny, potem karta i telefon). */
export function itemNumber(item: Identified): string {
  return (
    item.inventory_number ??
    item.access_card_number ??
    (item.category === "karta_sim" ? "SIM" : null) ??
    "—"
  );
}

/** Numer techniczny do kolumny „Numer”: S/N, IMEI albo numer telefonu SIM. */
export function itemIdentifier(item: Identified): string {
  if (item.category === "karta_sim") return phoneDisplay(item.phone_number) ?? "—";
  if (item.category === "telefon" && item.imei) return `IMEI ${item.imei}`;
  if (item.category === "karta_dostepu") return item.access_card_number ?? "—";
  return item.serial_number ?? item.imei ?? "—";
}

/** Kwota jak w protokole recepcji (`formatPlnDocument`): „3 903,73 zł”; brak = „bez wartości”. */
export function formatPln(value: string | number | null | undefined): string {
  return formatPlnDocument(value) ?? "bez wartości";
}

export interface IssueDraftLine {
  item: EquipmentItem;
  /** Wartość wpisana przy wydaniu („” = z cennika). */
  value: string;
  accessories: string;
}

/** Wartość pozycji w protokole (ręczna zmiana albo cena z cennika; SIM i karta — brak). */
export function lineValue(line: IssueDraftLine): number | null {
  if (isNoValueCategory(line.item.category)) return null;
  const raw = line.value.trim().replace(",", ".");
  if (raw !== "") {
    const typed = Number(raw);
    return Number.isFinite(typed) && typed >= 0 ? typed : null;
  }
  const price = line.item.model.price_pln;
  return price == null ? null : Number(price);
}

/** Suma protokołu — liczona w groszach, żeby 0,1 + 0,2 nie dało 0,30000000000000004. */
export function issueTotal(lines: IssueDraftLine[]): number {
  const cents = lines.reduce((sum, line) => {
    const value = lineValue(line);
    return value == null ? sum : sum + Math.round(value * 100);
  }, 0);
  return cents / 100;
}

/** Czy pozycję można dodać do wydania (na stanie i bez posiadacza). */
export function canIssue(item: Pick<EquipmentItem, "status" | "holder">): boolean {
  return item.status === "na_stanie" && item.holder == null;
}

/** Powód, dla którego pozycji nie da się wydać (do podpowiedzi w kreatorze). */
export function issueBlocker(item: Pick<EquipmentItem, "status" | "holder">): string | null {
  if (canIssue(item)) return null;
  if (item.holder) return `Wydana: ${item.holder.name}`;
  return `Stan: ${ITEM_STATUS_LABELS[item.status]}`;
}

/** Wiersz aktywnego wydania w czytelnej postaci („Laptop Dell (221) · S/N …”). */
export function assignmentLabel(row: AssignmentRow): string {
  const number = row.inventory_number ? ` (${row.inventory_number})` : "";
  const identifier =
    row.category === "karta_sim"
      ? phoneDisplay(row.phone_number)
      : row.category === "karta_dostepu"
        ? row.access_card_number
        : row.serial_number ?? row.imei;
  // Model kart nazywa się zwykle jak kategoria („Karta dostępu”) — bez
  // powtórzenia („Karta dostępu Karta dostępu · 2481”, testy produkcji 19.10).
  const category = CATEGORY_LABELS[row.category];
  const model = (row.model_name ?? "").trim();
  const name = !model
    ? category
    : model.toLocaleLowerCase("pl").startsWith(category.toLocaleLowerCase("pl"))
      ? model
      : `${category} ${model}`;
  return `${name}${number}${identifier ? ` · ${identifier}` : ""}`;
}

/** „Do zrobienia”: termin i opóźnienie słowami. */
export function dueLabel(dueOn: string | null, overdueDays: number): string {
  if (!dueOn) return "bez terminu";
  const date = formatIsoDatePl(dueOn);
  if (overdueDays > 0) return `po terminie ${countPl(overdueDays, "dzień", "dni", "dni")} (${date})`;
  return `do ${date}`;
}

/** Treść wiadomości z linkiem do podpisu (recepcja wysyła ją ze swojej poczty). */
export function signatureMailHref(email: string | null, number: string, url: string): string {
  const subject = `Protokół ${number} — potwierdzenie odbioru sprzętu`;
  const body = [
    "Dzień dobry,",
    "",
    `proszę o potwierdzenie odbioru sprzętu z protokołu ${number}:`,
    url,
    "",
    "Link jest ważny 14 dni i działa jeden raz.",
  ].join("\n");
  return `mailto:${encodeURIComponent(email ?? "")}?subject=${encodeURIComponent(
    subject,
  )}&body=${encodeURIComponent(body)}`;
}

// ── Ekran po makiecie 19.10.2026: kafle, modele, zestawy, agenda ─────────────

/** Liczba mnoga kategorii — kafle stanu i „Czy starczy na wydania?”. */
export const CATEGORY_PLURAL: Record<EquipmentCategory, string> = {
  laptop: "Laptopy",
  telefon: "Telefony",
  monitor: "Monitory",
  karta_sim: "Karty SIM",
  karta_dostepu: "Karty dostępu",
  akcesorium: "Akcesoria",
  inne: "Inne",
};

/** Kategorie z własnym kaflem stanu w „Ewidencji” (reszta pod filtrem „Kategoria”). */
export const TILE_CATEGORIES: EquipmentCategory[] = ["laptop", "telefon", "monitor", "karta_sim"];

/** Numer ewidencyjny po ludzku: „095” < „148” < „T-062”, potem id. */
export function compareItemNumber(a: EquipmentItem, b: EquipmentItem): number {
  return itemNumber(a).localeCompare(itemNumber(b), "pl", { numeric: true }) || a.id - b.id;
}

export interface ModelGroup {
  /** Klucz grupy (`modelKey`) — ten sam model zapisany różnie to jedna grupa. */
  key: string;
  /** Model z najczęstszym zapisem nazwy w grupie (etykieta wiersza). */
  model: EquipmentModel;
  category: EquipmentCategory;
  /** Sztuki po numerze ewidencyjnym — pierwsza to ta, którą bierze „Wydaj”. */
  items: EquipmentItem[];
  /** Miejsca sztuk od najczęstszego („szafka B”). */
  locations: string[];
}

/**
 * Klucz modelu w widoku „Modele”: import Exceli recepcji założył ten sam model
 * kilka razy różnym zapisem („Laptop DELL Vostro 3530” i „Laptop Dell Vostro
 * 3530”, prod 20.10) — wielkość liter i spacje nie rozdzielają grup.
 */
export function modelKey(item: Pick<EquipmentItem, "category" | "model">): string {
  const name = item.model.name.trim().replace(/\s+/g, " ").toLocaleLowerCase("pl");
  return `${item.category}:${name}`;
}

function mostCommon<T>(values: readonly T[], keyOf: (value: T) => string | number): T {
  const counts = new Map<string | number, number>();
  for (const value of values) counts.set(keyOf(value), (counts.get(keyOf(value)) ?? 0) + 1);
  // Remis: pierwszy w kolejności wejścia (sztuki są już po numerze ewidencyjnym).
  return values.reduce((best, value) =>
    (counts.get(keyOf(value)) ?? 0) > (counts.get(keyOf(best)) ?? 0) ? value : best,
  );
}

/**
 * Widok „Modele”: sztuki zwinięte po modelu (`modelKey`). Kolejność: kategoria
 * rejestru, potem model z największą liczbą sztuk, potem nazwa.
 */
export function groupByModel(items: readonly EquipmentItem[]): ModelGroup[] {
  const groups = new Map<string, EquipmentItem[]>();
  for (const item of items) {
    const key = modelKey(item);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.entries()]
    .map(([key, members]): ModelGroup => {
      const sorted = [...members].sort(compareItemNumber);
      const counts = new Map<string, number>();
      for (const member of members) {
        const place = member.location?.trim();
        if (place) counts.set(place, (counts.get(place) ?? 0) + 1);
      }
      return {
        key,
        model: mostCommon(sorted, (member) => member.model.id).model,
        category: members[0].category,
        items: sorted,
        locations: [...counts.entries()]
          .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "pl"))
          .map(([place]) => place),
      };
    })
    .sort(
      (a, b) =>
        CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category) ||
        b.items.length - a.items.length ||
        a.model.name.localeCompare(b.model.name, "pl"),
    );
}

// ── Gotowe zestawy (decyzja Artura 19.10.2026) ────────────────────────────────
//
// Skład zestawów żyje w kodzie, bo NEXUS nie ma wzoru zestawu: pakiet klienta
// wybiera tylko wzór protokołu, a zestaw edycji Akademii recepcja składa z
// modeli przy każdym wydaniu. Zmiana składu = zmiana tej listy (i reguły
// `docs/claude/ludzie/sprzet-i-protokoly-recepcji.md`).

export interface KitSlot {
  category: EquipmentCategory;
  label: string;
  /** Akcesorium bierzemy po nazwie modelu (słuchawki, nie kabel). */
  modelName?: RegExp;
}

export type IssueKitKey = "kontraktor" | "biuro";

export interface IssueKit {
  key: IssueKitKey;
  title: string;
  slots: KitSlot[];
}

const HEADSET: KitSlot = { category: "akcesorium", label: "słuchawki", modelName: /słuchawk|headset/i };

export const ISSUE_KITS: IssueKit[] = [
  {
    key: "kontraktor",
    title: "Zestaw kontraktora",
    slots: [
      { category: "laptop", label: "laptop" },
      { category: "telefon", label: "telefon" },
      { category: "karta_sim", label: "SIM" },
      HEADSET,
      { category: "karta_dostepu", label: "karta dostępu" },
    ],
  },
  {
    key: "biuro",
    title: "Zestaw biura",
    slots: [
      { category: "laptop", label: "laptop" },
      { category: "monitor", label: "monitor" },
      HEADSET,
      { category: "karta_dostepu", label: "karta dostępu" },
    ],
  },
];

export function kitByKey(key: IssueKitKey): IssueKit {
  return ISSUE_KITS.find((kit) => kit.key === key) as IssueKit;
}

export function slotMatches(slot: KitSlot, item: Pick<EquipmentItem, "category" | "model">): boolean {
  return (
    item.category === slot.category && (!slot.modelName || slot.modelName.test(item.model.name))
  );
}

/**
 * „Dodaj zestaw”: na każde miejsce zestawu pierwsza wolna sztuka (po numerze).
 * Miejsce już zajęte pozycją z protokołu nie dostaje drugiej sztuki; brak
 * wolnej sztuki wraca w `missing` (recepcja widzi, czego zabrakło).
 */
export function pickKit(
  kit: IssueKit,
  free: readonly EquipmentItem[],
  chosen: readonly EquipmentItem[],
): { added: EquipmentItem[]; missing: string[] } {
  const used = new Set<number>();
  const taken = new Set(chosen.map((item) => item.id));
  const added: EquipmentItem[] = [];
  const missing: string[] = [];
  const pool = [...free].sort(compareItemNumber);
  for (const slot of kit.slots) {
    const already = chosen.find((item) => !used.has(item.id) && slotMatches(slot, item));
    if (already) {
      used.add(already.id);
      continue;
    }
    const next = pool.find((item) => !taken.has(item.id) && slotMatches(slot, item));
    if (next) {
      taken.add(next.id);
      used.add(next.id);
      added.push(next);
    } else {
      missing.push(slot.label);
    }
  }
  return { added, missing };
}

/** Zestaw zadania „Przygotuj”: start kontraktu = kontraktor, wejście pracownika = biuro. */
export function kitForTask(task: Pick<EquipmentTask, "kind" | "details">): IssueKit | null {
  if (task.kind !== "wydanie") return null;
  if (task.details.reason === "start_kontraktu") return kitByKey("kontraktor");
  if (task.details.reason === "wejscie") return kitByKey("biuro");
  return null;
}

export interface CoverageRow {
  category: EquipmentCategory;
  needed: number;
  free: number;
  short: number;
}

/**
 * „Czy starczy na wydania?”: kategorie zestawów z otwartych zadań „Przygotuj”
 * zestawione z wolnymi sztukami na stanie. Słuchawki liczą się jako akcesoria
 * (licznik stanu nie rozróżnia akcesoriów po nazwie).
 */
export function stockCoverage(
  tasks: readonly Pick<EquipmentTask, "kind" | "status" | "details">[],
  freeByCategory: Readonly<Record<EquipmentCategory, number>>,
): CoverageRow[] {
  const needed = new Map<EquipmentCategory, number>();
  for (const task of tasks) {
    if (task.status !== "otwarte") continue;
    for (const slot of kitForTask(task)?.slots ?? []) {
      needed.set(slot.category, (needed.get(slot.category) ?? 0) + 1);
    }
  }
  return CATEGORY_ORDER.filter((category) => needed.has(category)).map((category) => {
    const need = needed.get(category) ?? 0;
    const free = freeByCategory[category] ?? 0;
    return { category, needed: need, free, short: Math.max(0, need - free) };
  });
}

// ── Agenda „Do zrobienia” ────────────────────────────────────────────────────

export type AgendaBucket = "overdue" | "today" | "later";
export type AgendaFilter = "all" | "przygotuj" | "podpis" | "zwrot";

export const AGENDA_TITLES: Record<AgendaBucket, string> = {
  overdue: "Po terminie",
  today: "Dziś",
  later: "Później",
};

const FILTER_KINDS: Record<Exclude<AgendaFilter, "all">, EquipmentTaskKind[]> = {
  przygotuj: ["wydanie", "zakup"],
  podpis: ["podpis"],
  zwrot: ["zwrot"],
};

export function matchesAgendaFilter(task: Pick<EquipmentTask, "kind">, filter: AgendaFilter): boolean {
  return filter === "all" || FILTER_KINDS[filter].includes(task.kind);
}

export function agendaBucket(task: Pick<EquipmentTask, "due_on">, today: string): AgendaBucket {
  if (!task.due_on || task.due_on > today) return "later";
  return task.due_on < today ? "overdue" : "today";
}

/** Grupy agendy w kolejności Po terminie → Dziś → Później, puste pominięte. */
export function agendaGroups<T extends Pick<EquipmentTask, "due_on" | "id">>(
  tasks: readonly T[],
  today: string,
): { bucket: AgendaBucket; tasks: T[] }[] {
  const sorted = [...tasks].sort(
    (a, b) =>
      (a.due_on ?? "9999-12-31").localeCompare(b.due_on ?? "9999-12-31") || a.id - b.id,
  );
  return (["overdue", "today", "later"] as const)
    .map((bucket) => ({ bucket, tasks: sorted.filter((t) => agendaBucket(t, today) === bucket) }))
    .filter((group) => group.tasks.length > 0);
}

/** Termin w wierszu agendy: „6 dni po”, „dziś”, „do 26.10”. */
export function agendaDue(dueOn: string | null, today: string): string {
  if (!dueOn) return "bez terminu";
  if (dueOn === today) return "dziś";
  if (dueOn < today) {
    const days = Math.round(
      (Date.parse(`${today}T00:00:00Z`) - Date.parse(`${dueOn}T00:00:00Z`)) / 86_400_000,
    );
    return `${countPl(days, "dzień", "dni", "dni")} po`;
  }
  return `do ${formatDayMonthPl(dueOn)}`;
}

function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export interface WeekDay {
  date: string;
  label: string;
  count: number;
  isToday: boolean;
}

/**
 * „Ten tydzień w recepcji”: otwarte zadania na każdy dzień roboczy (pon–pt).
 * Zaległe liczą się do dziś — dziś trzeba je zrobić. W sobotę i niedzielę
 * pokazujemy nadchodzący tydzień.
 */
export function weekPlan(
  tasks: readonly Pick<EquipmentTask, "due_on" | "status">[],
  today: string,
): { days: WeekDay[]; next: { count: number; first: string | null } } {
  const weekday = weekdayOfIso(today);
  const monday = addDays(today, weekday >= 5 ? 7 - weekday : -weekday);
  const open = tasks.filter((task) => task.status === "otwarte" && task.due_on);
  const days = [0, 1, 2, 3, 4].map((offset): WeekDay => {
    const date = addDays(monday, offset);
    const due = open.filter((task) => task.due_on === date).length;
    const overdue =
      date === today ? open.filter((task) => (task.due_on as string) < today).length : 0;
    return {
      date,
      label: WEEKDAYS_PL[offset],
      count: due + overdue,
      isToday: date === today,
    };
  });
  const nextMonday = addDays(monday, 7);
  const nextFriday = addDays(monday, 11);
  const next = open
    .map((task) => task.due_on as string)
    .filter((due) => due >= nextMonday && due <= nextFriday)
    .sort();
  return { days, next: { count: next.length, first: next[0] ?? null } };
}

/** Dni od daty do dziś (0 = dziś) — „najstarszy 3 dni”, „w serwisie od 12 dni”. */
export function daysSince(iso: string | null | undefined, today: string): number | null {
  if (!iso) return null;
  return Math.max(
    0,
    Math.round(
      (Date.parse(`${today}T00:00:00Z`) - Date.parse(`${iso.slice(0, 10)}T00:00:00Z`)) /
        86_400_000,
    ),
  );
}

/** Inicjały posiadacza do awatara („Anna Kontraktorska” → „AK”). */
export function holderInitials(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter((part) => /\p{L}/u.test(part))
      .slice(0, 2)
      .map((part) => part[0].toLocaleUpperCase("pl"))
      .join("") || "?"
  );
}

/** Kontekst zadania pod tytułem: klient, powód i termin źródła, liczba pozycji. */
/**
 * Tytuł zadania w agendzie. Podpis: osoba w tytule, numer protokołu w drugiej
 * linii — przy 1280 px „Podpis protokołu PZO/2026/10/001: …” ucinał nazwisko
 * (prod 20.10). Starsze zadania mają numer w zapisanym tytule, stąd składanie tutaj.
 */
export function taskTitle(task: Pick<EquipmentTask, "kind" | "title" | "holder" | "protocol">): string {
  if (task.kind === "podpis" && task.protocol && task.holder.name) {
    return `Podpis protokołu: ${task.holder.name}`;
  }
  return task.title;
}

export function taskContext(
  task: Pick<EquipmentTask, "kind" | "details"> & Partial<Pick<EquipmentTask, "protocol">>,
): string {
  const d = task.details;
  const parts: string[] = [];
  const protocol = task.kind === "podpis" ? task.protocol : null;
  if (protocol) {
    parts.push(protocol.number);
    if (protocol.client_name) parts.push(protocol.client_name);
    if (protocol.link_sent_on) parts.push(`wysłany ${formatDayMonthPl(protocol.link_sent_on)}`);
    return parts.join(" · ");
  }
  if (typeof d.client_name === "string" && d.client_name) parts.push(d.client_name);
  const on = (key: string) =>
    typeof d[key] === "string" ? formatDayMonthPl(d[key] as string) : null;
  switch (d.reason) {
    case "start_kontraktu":
      parts.push(`wejście u klienta${on("start_date") ? ` ${on("start_date")}` : ""}`);
      break;
    case "wejscie":
      parts.push(`start w biurze${on("start_date") ? ` ${on("start_date")}` : ""}`);
      break;
    case "koniec_wspolpracy":
      parts.push(`koniec współpracy${on("end_date") ? ` ${on("end_date")}` : ""}`);
      break;
    case "odejscie":
      parts.push(`odejście${on("last_day") ? ` ${on("last_day")}` : ""}`);
      break;
    default:
      break;
  }
  if (task.kind === "zwrot" && typeof d.items === "number" && d.items > 0) {
    parts.push(`${countPl(d.items, "pozycja", "pozycje", "pozycji")} z ewidencji`);
  }
  return parts.join(" · ");
}

/** Wiadomość z prośbą o zwrot — recepcja wysyła ją ze swojej poczty (osoba bez konta). */
export function returnReminderMailHref(email: string, dueOn: string | null): string {
  const subject = "Zwrot sprzętu firmy";
  const body = [
    "Dzień dobry,",
    "",
    dueOn
      ? `przypominamy o zwrocie sprzętu firmy — termin minął ${formatIsoDatePl(dueOn)}.`
      : "przypominamy o zwrocie sprzętu firmy.",
    "Prosimy o kontakt z recepcją w sprawie terminu oddania.",
  ].join("\n");
  return `mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent(
    subject,
  )}&body=${encodeURIComponent(body)}`;
}
