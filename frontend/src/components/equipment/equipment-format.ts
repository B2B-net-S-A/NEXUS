// Etykiety i czyste funkcje modułu „Sprzęt” (testowane bez renderowania).

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  AssignmentRow,
  EquipmentCategory,
  EquipmentHolderKind,
  EquipmentItem,
  EquipmentItemStatus,
  EquipmentProvider,
  EquipmentTaskKind,
  ImportDecision,
  ProtocolStatus,
  ReturnCondition,
  SignatureMethod,
} from "@/lib/api/equipment";
import { formatIsoDatePl } from "@/lib/date-pl";
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
  user: "Pracownik",
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
  return `${CATEGORY_LABELS[row.category]} ${row.model_name}${number}${
    identifier ? ` · ${identifier}` : ""
  }`;
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
