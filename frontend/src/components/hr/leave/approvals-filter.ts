// „Akceptacje” jako jedna lista (makieta zatwierdzona 22.10.2026): chipy
// rodzaju („Wszystko · Nieobecności · Raporty godzin · Zgody · Do wiadomości”),
// „Czeka | Zdecydowane” i grupy listy. Czyste funkcje, bez zapytań.
//
// Adres: `?tab=leave|time|consents|info` (bez `tab` = „Wszystko”),
// `?view=decided` („Zdecydowane”). Linki z powiadomień i maili zostają:
// `?tab=consents[&request=<id>]` → „Zgody”, `?kind=timesheet&year=&month=&user=`
// → „Raporty godzin”.

import type { HrConfig } from "@/lib/api/hr";
import type { ApprovalRequestRow } from "@/lib/api/hr-approvals";
import { isUrgent } from "@/components/hr/approvals/approvals-format";

import type { InboxItem } from "./approvals-inbox";

export type ApprovalsChip = "all" | "leave" | "time" | "consents" | "info";
export type ApprovalsView = "waiting" | "decided";

const URL_CHIPS: readonly ApprovalsChip[] = ["leave", "time", "consents", "info"];

/** Chip z adresu; `null` = adres nic nie mówi (zostaje bieżący wybór). */
export function chipFromParams(params: URLSearchParams): ApprovalsChip | null {
  const tab = params.get("tab");
  if (tab && (URL_CHIPS as readonly string[]).includes(tab)) return tab as ApprovalsChip;
  if (tab === "all") return "all";
  if (params.get("kind") === "timesheet") return "time";
  return null;
}

export function viewFromParams(params: URLSearchParams): ApprovalsView | null {
  const view = params.get("view");
  return view === "decided" || view === "waiting" ? view : null;
}

/**
 * Bieżący adres z nowym chipem albo widokiem. Miesiąc i osoba raportu godzin
 * (`year`, `month`, `user`) i zgoda z linku (`request`) zostają; `kind` i
 * `decide` znikają — chip mówi już, co widać, a okno decyzji z maila nie
 * powinno wracać po odświeżeniu.
 */
export function approvalsSearch(
  search: string,
  next: { chip: ApprovalsChip; view: ApprovalsView },
): string {
  const params = new URLSearchParams(search);
  params.delete("kind");
  params.delete("decide");
  if (next.chip === "all") params.delete("tab");
  else params.set("tab", next.chip);
  if (next.view === "decided") params.set("view", "decided");
  else params.delete("view");
  const query = params.toString();
  return query ? `?${query}` : "?";
}

/**
 * Wniosek z linku maila (26.10.2026): `?leave=<id>[&decide=approve|reject]`.
 * Decyzja tylko otwiera okno potwierdzenia — nic nie zapisuje sama.
 */
export function leaveLinkFromParams(
  params: Pick<URLSearchParams, "get">,
): { id: string; decision: "approve" | "reject" | null } | null {
  const id = params.get("leave")?.trim();
  if (!id) return null;
  const decide = params.get("decide");
  return { id, decision: decide === "approve" || decide === "reject" ? decide : null };
}

export interface ApprovalsAccess {
  leave: boolean;
  time: boolean;
  consents: boolean;
}

/** Które części ekranu są włączone — chipy modułów wyłączonych znikają. */
export function approvalsAccess(config: HrConfig): ApprovalsAccess {
  const timesheetViewer =
    config.me.is_manager ||
    (config.me.covering?.length ?? 0) > 0 ||
    config.me.people_admin ||
    config.me.timesheets === true ||
    config.me.payroll ||
    config.me.is_admin;
  return {
    // Same „Raporty godzin” nie dają nieobecności — bez chipów i bloku 403.
    leave: config.open_modules.leave && config.me.leave_approver !== false,
    time: config.open_modules.time && timesheetViewer,
    consents: config.open_modules.approvals,
  };
}

export function visibleChips(access: ApprovalsAccess): ApprovalsChip[] {
  const chips: ApprovalsChip[] = ["all"];
  if (access.leave) chips.push("leave");
  if (access.time) chips.push("time");
  if (access.consents) chips.push("consents");
  if (access.leave) chips.push("info");
  return chips;
}

/** Chip z adresu, o ile jego moduł jest włączony; inaczej „Wszystko”. */
export function allowedChip(chip: ApprovalsChip | null, access: ApprovalsAccess): ApprovalsChip {
  return chip && visibleChips(access).includes(chip) ? chip : "all";
}

/** Co pokazuje chip: część listy, sekcja raportów godzin. */
export function chipShows(chip: ApprovalsChip) {
  return {
    leaveDecide: chip === "all" || chip === "leave",
    consents: chip === "all" || chip === "consents",
    info: chip === "all" || chip === "info",
    timesheets: chip === "all" || chip === "time",
  };
}

export type QueueEntry =
  | { key: string; source: "leave"; item: InboxItem; at: number | null }
  | { key: string; source: "consent"; row: ApprovalRequestRow; at: number | null };

export function consentKey(id: number): string {
  return `consent-${id}`;
}

function instant(value: string | null | undefined): number | null {
  if (!value) return null;
  const time = Date.parse(value);
  return Number.isNaN(time) ? null : time;
}

/** Najstarsze pierwsze; bez daty na końcu, w kolejności z serwera (sort stabilny). */
function oldestFirst(entries: QueueEntry[]): QueueEntry[] {
  return [...entries].sort((a, b) => {
    if (a.at === null || b.at === null) return a.at === null ? (b.at === null ? 0 : 1) : -1;
    return a.at - b.at;
  });
}

export interface QueueGroups {
  /** Zgody z terminem „potrzebne do” dziś albo jutro. */
  urgent: QueueEntry[];
  /** Wnioski o nieobecność i zgody do decyzji, najstarsze pierwsze. */
  decide: QueueEntry[];
  /** Zgłoszenia z B2B i zlecenia — do wiadomości. */
  info: QueueEntry[];
}

export function queueGroups({
  decide,
  info,
  consents,
  today,
  chip,
}: {
  decide: readonly InboxItem[];
  info: readonly InboxItem[];
  consents: readonly ApprovalRequestRow[];
  today: string;
  chip: ApprovalsChip;
}): QueueGroups {
  const shows = chipShows(chip);
  const leaveEntry = (item: InboxItem): QueueEntry => ({
    key: item.key,
    source: "leave",
    item,
    at: instant(item.row.created_at),
  });
  const consentEntry = (row: ApprovalRequestRow): QueueEntry => ({
    key: consentKey(row.id),
    source: "consent",
    row,
    at: instant(row.submitted_at),
  });
  const shownConsents = shows.consents ? consents : [];
  return {
    urgent: shownConsents.filter((row) => isUrgent(row, today)).map(consentEntry),
    decide: oldestFirst([
      ...(shows.leaveDecide ? decide.map(leaveEntry) : []),
      ...shownConsents.filter((row) => !isUrgent(row, today)).map(consentEntry),
    ]),
    info: shows.info ? info.map(leaveEntry) : [],
  };
}

export type ChipCounts = Partial<Record<ApprovalsChip, number>>;

/**
 * Liczby przy chipach — z tych samych danych co lista. Źródło, które się
 * jeszcze nie wczytało (albo padło), nie ma liczby; „Raporty godzin” liczby
 * nie mają (kolejka miesiąca ma własne podsumowanie).
 */
export function chipCounts({
  decide,
  info,
  consents,
}: {
  decide: number | null;
  info: number | null;
  consents: number | null;
}): ChipCounts {
  const counts: ChipCounts = {};
  if (decide !== null) counts.leave = decide;
  if (info !== null) counts.info = info;
  if (consents !== null) counts.consents = consents;
  const parts = [decide, info, consents].filter((value): value is number => value !== null);
  if (parts.length > 0) counts.all = parts.reduce((sum, value) => sum + value, 0);
  return counts;
}
