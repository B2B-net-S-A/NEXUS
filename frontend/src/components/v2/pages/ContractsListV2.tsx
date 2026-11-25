"use client";

import { RateDocumentRowNote } from "@/components/contracts/rate-documents/RateDocumentRowNote";
import { RateHistoryRowNote } from "@/components/contracts/rate-history-ksef/RateHistoryRowNote";
import {
 OrderAfterEndRowNote,
 type OrderAfterEndSummary,
} from "@/components/contracts/OrderAfterEndRowNote";
import type { RateDocumentChange } from "@/lib/api/contractRateDocuments";
import type { RateHistoryChange } from "@/lib/api/contractRateHistoryKsef";
import { useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from"react";
import Link from"next/link";
import dynamic from"next/dynamic";
import { keepPreviousData, useQuery, useQueryClient } from"@tanstack/react-query";
import {
 AlertTriangle,
 ArrowDown,
 ArrowUp,
 ChevronDown,
 ChevronRight,
 ChevronsUpDown,
 Download,
 FileText,
 FileWarning,
 Layers,
 Plus,
 Search,
 TrendingUp,
 X,
} from"lucide-react";
import api, { contractorsApi, type ContractorListItem } from"@/lib/api";
import { DraftCompletionModal } from "@/components/v2/modals/DraftCompletionModal";
import { cn, formatCurrency } from"@/lib/utils";
import { CONTRACT_FIELD_LABELS } from "@/lib/api-error";
import { contractRateUnitSuffix } from"@/lib/rate-unit";
import { useDebouncedValue } from"@/lib/use-debounced-value";
import { resolveViewState } from"@/lib/view-state";
import {
 CONTRACT_STATUS_LABEL,
 CONTRACT_STATUS_VARIANT,
} from"@/lib/contract-register";
import { QueryStateNotice } from"@/components/ds/QueryStateNotice";
import { ListDetailLayout } from"@/components/ds/ListDetailLayout";
import { rowActivationProps, useRowNavigation } from"@/hooks/useRowNavigation";
import { TruncatedText } from"@/components/ds/TruncatedText";
import { CALM_EMPTY, CALM_UNIT } from"@/lib/calm-table";
import {
 WIDE_HIDDEN,
 WIDE_ONLY_CELL,
 WIDE_ONLY_COL,
 WIDE_TABLE_CONTAINER,
} from"@/lib/wide-table";
import { useCapability } from"@/hooks/useCapability";
import { Button } from"@/components/ui/button";
import { Checkbox } from"@/components/ui/checkbox";
import { Input } from"@/components/ui/input";
import {
 Popover,
 PopoverContent,
 PopoverTrigger,
} from"@/components/ui/popover";
import { ContractsBulkActionsBarV2 } from"@/components/v2/modals/ContractsBulkActionsBar";
import { PlacementsExportDialog } from "@/components/v2/modals/PlacementsExportDialog";
import { ContractAgreementRecordDialog } from "@/components/contracts/ContractAgreementRecordDialog";
import { terminationDocKind, type TerminationDocumentRef } from "@/lib/contract-happening";
import { ContractNextCell, ContractRowNote } from "@/components/contracts/list/ContractNextCell";
import { ContractsEndingView, type EndingListRow } from "@/components/contracts/list/ContractsEndingView";
import {
 ContractsMoreFilters,
 EMPTY_DATE_RANGE,
 rangeInverted,
 type ContractsDateRange,
} from "@/components/contracts/list/ContractsMoreFilters";
import { placementsExportFilename, type PlacementsRange } from "@/lib/placements-export";
import {
 Table,
 TableBody,
 TableCell,
 TableHead,
 TableHeader,
 TableRow,
} from"@/components/ui/table";
import {
 CONTRACT_TYPE_OPTIONS,
 type ContractStatusValue,
 type ContractTypeValue,
} from"@/lib/filter-options";
import {
 DEFAULT_CONTRACT_STATUS_FILTER,
 type ContractSortDir,
 type ContractSortKey,
 buildContractDetailHref,
 buildContractsListUrl,
 parseContractsListState,
 rememberContractsListScroll,
 restoreContractsListScroll,
 takeContractsListScroll,
} from "@/lib/contracts-list-navigation";
import { localTodayIso } from "@/lib/client-order-list";
import { fmtDatePl } from "@/lib/contract-happening";
import { sortByLastDay } from "@/lib/contract-ending";
import {
 formatPlnWhole,
 groupRowsByClient,
 listNextSteps,
 peopleLabel,
 type ListRowFacts,
} from "@/lib/contract-list-next";
import { contractStatusLabel } from "@/lib/status-labels";
import { warsawToday } from "@/lib/warsaw-date";
import { hasAnyPermission, hasPermission, permissionLabel } from "@/lib/permissions";
import { getAuthenticatedRequestHeaders } from "@/lib/session";
import {
 canManageCandidateFinance,
 canViewClientFinance,
 hasAnalyticsCapability,
 hasRole,
 useAuthStore,
} from "@/store/auth";

export type { ContractsDateRange };

// Panel ładowany leniwie: niesie okna zakończenia, aneksów i dokumentów, których
// lista bez otwartego panelu nie potrzebuje.
const ContractSidePanel = dynamic(
 () =>
 import("@/components/contracts/ContractSidePanel").then(
 (m) => m.ContractSidePanel,
 ),
 {
 ssr: false,
 loading: () => (
 <p className="p-4 text-sm text-muted-foreground">Ładowanie kontraktu…</p>
 ),
 },
);

/** Klik w link, przycisk albo kwadracik w komórce nie otwiera panelu. */
function clickFromInteractive(event: MouseEvent<HTMLElement>): boolean {
 const target = event.target instanceof Element ? event.target : null;
 const el = target?.closest(
"a,button,input,select,textarea,label,[role=checkbox],[data-row-stop]",
 );
 return el != null && el !== event.currentTarget;
}

interface ContractGroupMemberRow {
 id: number;
 client_id: number;
 client_name?: string | null;
 job_title?: string | null;
 start_date?: string | null;
 end_date?: string | null;
 latest_order_end_date?: string | null;
 client_order_start_date?: string | null;
 client_order_end_date?: string | null;
 contract_type?: string;
 rate_client?: number | null;
 rate_candidate?: number | null;
 rate_unit?: string | null;
 margin?: number | null;
 status?: string;
 currency?: string | null;
 rate_client_currency?: string | null;
 rate_candidate_currency?: string | null;
 // Fakty „Co dalej” (20.11.2026); starszy serwer wysyła je tylko w wierszu głównym.
 terminated_at?: string | null;
 termination_reason?: string | null;
 termination_lessons?: string | null;
 agreement_termination_mode?: string | null;
 prolongation_status?: string | null;
 billing_hours_per_month?: number | null;
 // Wypowiedzenie/porozumienie w Dokumentach przy niezapisanym rozwiązaniu (22.11.2026).
 termination_document?: TerminationDocumentRef | null;
}

interface ContractRow {
 id: number;
 candidate_id?: number | null;
 client_id?: number | null;
 work_mode?: "remote" | "hybrid" | "onsite" | null;
 // Braki szkicu z serwera (bramka aktywacji) — „Uzupełnij / Aktywuj” w wierszu.
 missing_fields?: string[];
 // Stawka z dokumentu, której nie ma w harmonogramie (0739, redagowana z kwotami).
 rate_document_change?: RateDocumentChange | null;
 // Stawka z faktur KSeF, której nie ma w harmonogramie (0782, redagowana z kwotami).
 rate_history_change?: RateHistoryChange | null;
 // „Klient zamówił okres po zakończeniu” (19.11.2026): pierwsze takie zamówienie.
 order_after_end?: OrderAfterEndSummary | null;
 candidate_name?: string;
 client_name?: string;
 job_title?: string;
 start_date?: string;
 end_date?: string;
 latest_order_end_date?: string | null;
 client_order_start_date?: string | null;
 client_order_end_date?: string | null;
 contract_type?: string;
 rate_client?: number;
 rate_candidate?: number;
 rate_unit?: string | null;
 margin?: number;
 status?: string;
 currency?: string;
 rate_client_currency?: string | null;
 rate_candidate_currency?: string | null;
 terminated_at?: string | null;
 termination_reason?: string | null;
 termination_lessons?: string | null;
 agreement_termination_mode?: string | null;
 prolongation_status?: string | null;
 billing_hours_per_month?: number | null;
 termination_document?: TerminationDocumentRef | null;
 // `group_by_candidate=true`: wszystkie umowy tej osoby (żywe najpierw).
 // Wiersz z >1 członkiem renderuje kolumny okresu/stawek/marży per klient.
 group_members?: ContractGroupMemberRow[];
}

/** Fakty zakończenia i przedłużenia — wiersz główny niesie je zawsze. */
function primaryFacts(row: ContractRow): ListRowFacts {
 return {
  terminated_at: row.terminated_at ?? null,
  termination_reason: row.termination_reason ?? null,
  termination_lessons: row.termination_lessons ?? null,
  agreement_termination_mode: row.agreement_termination_mode ?? null,
  prolongation_status: row.prolongation_status ?? null,
  billing_hours_per_month: row.billing_hours_per_month ?? null,
  termination_document: row.termination_document ?? null,
 };
}

type ContractStatusBadge = {
 label: string;
 variant: "success" |"warning" |"neutral" |"danger" |"soft" |"info";
};

// Plakietka statusu musi pokrywać CAŁY enum `ContractStatus`
// (backend/app/models/contract.py). Do 2026-08 stały tu klucze `expiring`
// i `terminated`, których backend nigdy nie emitował, a brakowało `ending` —
// czyli JEDYNEGO statusu istniejącego po to, żeby ostrzegać („< 30 dni do
// końca"): renderował się w neutralnej szarości, nieodróżnialny od kontraktu
// zakończonego. Plakietka drukowała też surowy klucz enuma, więc polski
// rejestr pokazywał „active" i dosłowne „ready_for_signature".
//
// Cztery wartości bierzemy z `lib/contract-register.ts` — tego samego źródła,
// z którego korzysta rejestr per klient na tej samej stronie — żeby ten sam
// kontrakt nie nazywał się na dwóch listach inaczej. Dwie pozostałe są znane
// tylko tutaj: rejestr per klient pokazuje realizowane kontrakty, a globalny
// widzi też te czekające na podpis (`contract_lifecycle`) i anulowane (`void`
// = miękkie usunięcie, trzymane jako dowód podpisu).
//
// Kompletności pilnuje `__tests__/ContractsListV2Status.test.ts` wobec enuma
// backendu: dodanie tam nowej wartości ma wywalić CI, a nie wyciec do UI jako
// angielski identyfikator.
export const CONTRACT_STATUS_BADGE: Record<string, ContractStatusBadge> = {
 draft: { label: CONTRACT_STATUS_LABEL.draft, variant: CONTRACT_STATUS_VARIANT.draft },
 active: { label: CONTRACT_STATUS_LABEL.active, variant: CONTRACT_STATUS_VARIANT.active },
 ending: { label: CONTRACT_STATUS_LABEL.ending, variant: CONTRACT_STATUS_VARIANT.ending },
 ended: { label: CONTRACT_STATUS_LABEL.ended, variant: CONTRACT_STATUS_VARIANT.ended },
 // Oczekiwanie na podpis to nie jest ostrzeżenie (bursztyn zarezerwowany dla
 // `ending`), tylko stan przejściowy — stąd `info`.
 ready_for_signature: { label: "Do podpisu", variant: "info" },
 void: { label: "Anulowany", variant: "danger" },
};

function marginColor(margin: number | undefined, rateClient: number | undefined) {
 if (margin == null) return CALM_EMPTY;
 if (rateClient == null || rateClient === 0) return"text-foreground";
 const pct = (margin / rateClient) * 100;
 if (pct < 15) return"text-destructive font-semibold";
 if (pct < 25) return"text-warning-muted-foreground font-semibold";
 return"text-success-muted-foreground font-semibold";
}

type RateCurrencyRow = {
 currency?: string | null;
 rate_client_currency?: string | null;
 rate_candidate_currency?: string | null;
};

function clientCurrency(row: RateCurrencyRow): string {
 return row.rate_client_currency ?? row.currency ?? "PLN";
}

function candidateCurrency(row: RateCurrencyRow): string {
 return row.rate_candidate_currency ?? row.currency ?? "PLN";
}

function hasComparableRateCurrencies(row: RateCurrencyRow): boolean {
 return clientCurrency(row).toUpperCase() === candidateCurrency(row).toUpperCase();
}

/** Statusy, w których umowa DZIŚ obowiązuje — „kończąca się" też. */
const RUNNING_CONTRACT_STATUSES: ReadonlySet<ContractStatusValue> = new Set(
 DEFAULT_CONTRACT_STATUS_FILTER,
);

/**
 * Szybkie filtry jednej listy kontraktów (makieta 18.11.2026): zastępują tryby
 * „Obsługa kontraktorów” i „Rejestr kontraktów”, które pokazywały te same
 * umowy w dwóch cięciach. Każdy filtr to zbiór statusów rejestru, więc
 * licznik na pigułce i wiersze pod nią pochodzą z tego samego zapytania.
 * „Kończące się” = jedna reguła z serwera (`bucket=ending`,
 * `contract_service.ending_bucket_clause`): status `ending` albo żywa umowa
 * z końcem w 30 dni — ta sama, którą liczyła „Obsługa kontraktorów”.
 */
type QuickFilterKey =
 | "pending"
 | "running"
 | "ending"
 | "order_after_end"
 | "all"
 | "rate_document"
 | "rate_history";
const QUICK_FILTERS: ReadonlyArray<{
 key: QuickFilterKey;
 label: string;
 statuses: ContractStatusValue[];
 /** Zbiór liczy serwer (`bucket`), nie lista statusów. */
 bucket?: "ending" | "rate_document" | "rate_history" | "order_after_end";
 /** Pigułka tylko wtedy, gdy zbiór nie jest pusty (albo jest wybrany). */
 onlyWhenNotEmpty?: boolean;
 hint: string;
}> = [
 {
 key: "pending",
 label: "Do uzupełnienia",
 statuses: ["draft", "ready_for_signature"],
 hint: "Szkice bez danych do aktywacji i umowy czekające na podpis.",
 },
 {
 key: "running",
 label: "Aktywne",
 statuses: [...DEFAULT_CONTRACT_STATUS_FILTER],
 hint: "Obowiązujące dziś: aktywne i kończące się.",
 },
 {
 key: "ending",
 label: "Kończące się",
 statuses: [],
 bucket: "ending",
 hint: "Wypowiedziane i te, którym zostało 30 dni lub mniej.",
 },
 {
 key: "order_after_end",
 label: "Zamówione po końcu",
 statuses: [],
 bucket: "order_after_end",
 onlyWhenNotEmpty: true,
 hint: "Kończące się i zakończone kontrakty, u których klient zamówił okres po końcu współpracy.",
 },
 {
 key: "all",
 label: "Wszystkie",
 statuses: [],
 hint: "Wszystkie statusy, także zakończone.",
 },
 {
 key: "rate_document",
 label: "Stawka z dokumentu",
 statuses: [],
 bucket: "rate_document",
 hint: "Umowa albo aneks w Dokumentach podaje stawkę Partnera, której nie ma w kontrakcie.",
 },
 {
 key: "rate_history",
 label: "Stawka z faktur",
 statuses: [],
 bucket: "rate_history",
 hint: "Faktury KSeF (sprzedaż i faktury konsultanta) pokazują stawkę, której nie ma w harmonogramie kontraktu.",
 },
];

function sameStatuses(a: ContractStatusValue[], b: ContractStatusValue[]): boolean {
 return a.length === b.length && a.every((value) => b.includes(value));
}

/** Stawki ukryte przed kontem bez podglądu kwot — ten brak uzupełnia ktoś inny. */
const FINANCE_COMPLETION_FIELDS = new Set(["rate_candidate", "rate_client"]);

type DraftRowAction =
 | { kind: "activate" }
 | { kind: "complete"; fields: string[] }
 | { kind: "waits-for-rates" };

/**
 * Stan szkicu w wierszu, jak w dawnej „Obsłudze kontraktorów”: stawki, których
 * konto nie widzi, nie liczą się do braków, a szkic, któremu brakuje tylko
 * stawek, czeka na osobę z „Stawki i kwoty: zmiana”.
 */
export function draftRowAction(
 missingFields: readonly string[],
 access: { canSeeRates: boolean; canEditRates: boolean },
): DraftRowAction {
 if (missingFields.length === 0) return { kind: "activate" };
 const visible = missingFields.filter(
 (field) => access.canSeeRates || !FINANCE_COMPLETION_FIELDS.has(field),
 );
 if (visible.length > 0) return { kind: "complete", fields: visible };
 const waitsForRates =
 !access.canEditRates &&
 missingFields.some((field) => FINANCE_COMPLETION_FIELDS.has(field));
 return waitsForRates
 ? { kind: "waits-for-rates" }
 : { kind: "complete", fields: [...missingFields] };
}

/** Polska liczba mnoga: 1 / 2–4 (bez 12–14) / reszta. */
function pluralPl(n: number, one: string, few: string, many: string): string {
 const m10 = n % 10;
 const m100 = n % 100;
 if (n === 1) return one;
 return m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14) ? few : many;
}

export function missingCountLabel(n: number): string {
 return `${n} ${pluralPl(n, "brak", "braki", "braków")}`;
}

/** Podpowiedź z nazwami brakujących pól (te same etykiety co formularz kontraktu). */
function missingFieldsHint(fields: readonly string[]): string {
 return `Brakuje: ${fields.map((field) => CONTRACT_FIELD_LABELS[field] ?? field).join(", ")}`;
}

/** Wiersz rejestru jako wejście okna „Uzupełnij szkic” (to samo co w panelu). */
function draftFromRow(row: ContractRow): ContractorListItem {
 return {
 contract_id: row.id,
 candidate: { id: row.candidate_id ?? 0, name: row.candidate_name ?? `Kontrakt #${row.id}`, lastname: "" },
 client_id: row.client_id ?? null,
 client_name: row.client_name ?? null,
 job_title: row.job_title ?? null,
 status: (row.status ?? "draft") as ContractorListItem["status"],
 start_date: row.start_date ?? "",
 end_date: row.end_date ?? null,
 rate_candidate: row.rate_candidate ?? null,
 rate_client: row.rate_client ?? null,
 rate_unit: (row.rate_unit ?? "hourly") as ContractorListItem["rate_unit"],
 currency: row.currency,
 rate_client_currency: row.rate_client_currency ?? null,
 rate_candidate_currency: row.rate_candidate_currency ?? null,
 margin: row.margin ?? null,
 contract_type: (row.contract_type ?? "b2b") as ContractorListItem["contract_type"],
 work_mode: row.work_mode ?? null,
 missing_fields: row.missing_fields ?? [],
 };
}

export function contractorsCountText(
 contractors: number,
 contracts: number,
 activeOnly: boolean,
 futureStart = 0,
): string {
 const peopleFew =
 contractors % 10 >= 2 &&
 contractors % 10 <= 4 &&
 !(contractors % 100 >= 12 && contractors % 100 <= 14);
 const contractsFew =
 contracts % 10 >= 2 &&
 contracts % 10 <= 4 &&
 !(contracts % 100 >= 12 && contracts % 100 <= 14);

 if (activeOnly) {
 const contractorNoun = contractors === 1 ? "kontraktor" : "kontraktorów";
 const contractNoun =
 contracts === 1
 ? "aktywny kontrakt"
 : contractsFew
 ? "aktywne kontrakty"
 : "aktywnych kontraktów";
 // Status „Aktywny" niesie też umowy, które dopiero się zaczną (U5).
 const futureNote =
 futureStart > 0 ? ` (w tym ${futureStart} z przyszłym startem)` : "";
 return `${contractors} ${contractorNoun} / ${contracts} ${contractNoun}${futureNote}`;
 }

 const personNoun = contractors === 1 ? "osoba" : peopleFew ? "osoby" : "osób";
 const contractNoun =
 contracts === 1 ? "kontrakt" : contractsFew ? "kontrakty" : "kontraktów";
 return `${contractors} ${personNoun} / ${contracts} ${contractNoun}`;
}

// Jednostka obok kwoty: kontrakt zmienia ją razem z zamówieniem (120 zł/h →
// 960 zł/MD), więc sama kwota nie mówi, ile kosztuje godzina pracy.
function RateUnitSuffix({ unit }: { unit?: string | null }) {
 const suffix = contractRateUnitSuffix(unit);
 if (!suffix) return null;
 return (
 <span className="ml-0.5 text-[10px] font-normal text-muted-foreground">
 {suffix}
 </span>
 );
}

/** Jednostka domyślna rejestru — stoi raz, w nagłówku kolumn stawek. */
const DEFAULT_RATE_UNIT_LABEL = "zł/h";

/**
 * Wiersz w jednostce domyślnej (stawka godzinowa, obie strony w PLN) pokazuje
 * same liczby — „zł/h” stoi w nagłówku. Każdy inny (zł/MD, zł/mc, inna
 * waluta, brak jednostki) zostaje przy pełnym zapisie z walutą i jednostką,
 * żeby kwota nie udawała stawki godzinowej w złotych.
 */
function usesDefaultRateUnit(
 row: RateCurrencyRow & { rate_unit?: string | null },
): boolean {
 return (
 row.rate_unit === "hourly" &&
 clientCurrency(row).toUpperCase() === "PLN" &&
 candidateCurrency(row).toUpperCase() === "PLN"
 );
}

const BARE_AMOUNT = new Intl.NumberFormat("pl-PL", {
 minimumFractionDigits: 2,
 maximumFractionDigits: 3,
});

function RateAmount({
 value,
 currency,
 unit,
 bare,
}: {
 value: number;
 currency: string;
 unit?: string | null;
 bare: boolean;
}) {
 if (bare) return <>{BARE_AMOUNT.format(value)}</>;
 return (
 <>
 {formatCurrency(value, currency)}
 <RateUnitSuffix unit={unit} />
 </>
 );
}

function marginPercent(
 margin: number | null | undefined,
 rateClient: number | null | undefined,
): string | null {
 if (margin == null || rateClient == null || rateClient === 0) return null;
 return `${new Intl.NumberFormat("pl-PL", {
 minimumFractionDigits: 1,
 maximumFractionDigits: 1,
 }).format((margin / rateClient) * 100)}%`;
}

function rowAsGroupMember(row: ContractRow): ContractGroupMemberRow {
 return {
 ...primaryFacts(row),
 id: row.id,
 client_id: row.client_id ?? 0,
 client_name: row.client_name,
 job_title: row.job_title,
 start_date: row.start_date,
 end_date: row.end_date,
 latest_order_end_date: row.latest_order_end_date,
 client_order_start_date: row.client_order_start_date,
 client_order_end_date: row.client_order_end_date,
 contract_type: row.contract_type,
 rate_client: row.rate_client,
 rate_candidate: row.rate_candidate,
 rate_unit: row.rate_unit,
 margin: row.margin,
 status: row.status,
 currency: row.currency,
 rate_client_currency: row.rate_client_currency,
 rate_candidate_currency: row.rate_candidate_currency,
 };
}

export interface ContractsSort {
 by: ContractSortKey | null;
 dir: ContractSortDir;
}

/**
 * Zakres wysyłany do API. Odwrócona para (od > do) nie idzie wcale — pusty
 * wynik czytałby się jak brak kontraktów, a to tylko pomyłka w trakcie
 * wpisywania drugiej daty.
 */
export function effectiveDateRange(range: ContractsDateRange): ContractsDateRange {
 const startOk = !rangeInverted(range.startFrom, range.startTo);
 const orderOk = !rangeInverted(range.orderEndFrom, range.orderEndTo);
 return {
 startFrom: startOk ? range.startFrom : "",
 startTo: startOk ? range.startTo : "",
 orderEndFrom: orderOk ? range.orderEndFrom : "",
 orderEndTo: orderOk ? range.orderEndTo : "",
 };
}

/** Klik w nagłówek: nowa kolumna rosnąco, ta sama — odwraca kierunek. */
export function nextContractsSort(
 current: ContractsSort,
 key: ContractSortKey,
): ContractsSort {
 if (current.by !== key) return { by: key, dir: "asc" };
 return { by: key, dir: current.dir === "asc" ? "desc" : "asc" };
}

function dateRangeChipText(range: ContractsDateRange): string | null {
 const part = (label: string, from: string, to: string) => {
 if (!from && !to) return null;
 const f = from ? fmtDatePl(from) : "…";
 const t = to ? fmtDatePl(to) : "…";
 return `${label} ${f} – ${t}`;
 };
 const parts = [
 part("Start", range.startFrom, range.startTo),
 part("Koniec zam.", range.orderEndFrom, range.orderEndTo),
 ].filter(Boolean);
 return parts.length ? parts.join(" · ") : null;
}

function SortableHead({
 label,
 sortKey,
 sort,
 onSort,
 align = "left",
 unit,
 title,
 children,
 "data-tour": tourAnchor,
}: {
 label: string;
 sortKey: ContractSortKey;
 sort: ContractsSort;
 onSort: (key: ContractSortKey) => void;
 align?: "left" | "right";
 /** Jednostka kolumny („zł/h”) — drobnym drukiem obok nazwy. */
 unit?: string;
 /** Pełna nazwa kolumny albo opis sortowania w podpowiedzi. */
 title?: string;
 children?: ReactNode;
 /** Kotwica nowości na nagłówku kolumny. */
 "data-tour"?: string;
}) {
 const active = sort.by === sortKey;
 const Icon = !active ? ChevronsUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
 return (
 <TableHead
 className={cn("px-2", align === "right" && "text-right")}
 aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
 title={title}
 data-tour={tourAnchor}
 >
 <span
 className={cn(
 "flex items-center gap-2",
 align === "right" && "justify-end",
 )}
 >
 {children}
 <button
 type="button"
 onClick={() => onSort(sortKey)}
 aria-label={`Sortuj: ${label}`}
 className={cn(
 "inline-flex items-center gap-1 rounded-sm text-left uppercase hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
 align === "right" && "flex-row-reverse text-right",
 active && "text-foreground",
 )}
 >
 <span>
 {label}
 {unit && <> <span className={CALM_UNIT}>{unit}</span></>}
 </span>
 <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />
 </button>
 </span>
 </TableHead>
 );
}

function MobileFieldLabel({ children, unit }: { children: string; unit?: string }) {
 return (
 <span className="mb-1 hidden text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground max-xl:block">
 {children}
 {unit && <> <span className={CALM_UNIT}>{unit}</span></>}
 </span>
 );
}

/** „Grupuj: klient” i „Kończące się” biorą zbiór stronami po 100 (limit serwera). */
const ALL_ROWS_PAGE_SIZE = 100;
/** Bezpiecznik: 1000 umów naraz; więcej = komunikat, żeby zawęzić listę. */
const ALL_ROWS_MAX_PAGES = 10;
/** Tyle wierszy pokazuje rozwinięta grupa klienta, zanim „Pokaż wszystkie”. */
const ROWS_IN_OPEN_GROUP = 10;

interface ContractListPayload {
 items?: ContractRow[];
 total?: number;
 contractors_total?: number;
 contracts_total?: number;
 future_start_total?: number;
}

/**
 * Cały zbiór listy umowa po umowie (`group_by_candidate=false`), strona po
 * stronie. Sumy w nagłówku przychodzą z pierwszej odpowiedzi — serwer liczy
 * je z całego zbioru, nie ze strony.
 */
async function fetchAllContractRows(params: Record<string, unknown>) {
 const rows: ContractRow[] = [];
 let head: ContractListPayload | null = null;
 for (let page = 1; page <= ALL_ROWS_MAX_PAGES; page += 1) {
  const response = await api.get("/api/contracts", {
   params: { ...params, group_by_candidate: false, page, page_size: ALL_ROWS_PAGE_SIZE },
   paramsSerializer: { indexes: null },
  });
  const payload = (response.data ?? {}) as ContractListPayload;
  if (!head) head = payload;
  const batch = payload.items ?? [];
  rows.push(...batch);
  if (batch.length < ALL_ROWS_PAGE_SIZE || rows.length >= (payload.total ?? 0)) break;
 }
 const total = head?.total ?? rows.length;
 return {
  items: rows,
  total,
  contractors_total: head?.contractors_total ?? total,
  contracts_total: head?.contracts_total ?? total,
  future_start_total: head?.future_start_total ?? 0,
  truncated: rows.length < total,
 };
}

function clientGroupKey(clientId: number | null): string {
 return clientId == null ? "none" : String(clientId);
}

function contractTypeLabel(type: string): string {
 return CONTRACT_TYPE_OPTIONS.find((option) => option.value === type)?.label ?? type;
}

/** Linia tabeli: osoba (wiersz), umowa w tej linii i fakty „Co dalej”. */
interface ContractLine {
 person: ContractRow;
 member: ContractGroupMemberRow;
 facts: ListRowFacts;
 memberIndex: number;
 memberCount: number;
 /** Umowy zaznaczane kwadracikiem osoby (wiersz osoby = wszystkie jej umowy). */
 rowIds: number[];
 liveClientCount: number;
}

type PeriodRow = Pick<
 ContractGroupMemberRow,
 "start_date" | "end_date" | "client_order_start_date" | "client_order_end_date" | "latest_order_end_date"
>;

/**
 * Druga linia „Okresu”: koniec bieżącego zamówienia klienta (z najnowszego
 * uzupełnionego zamówienia), a bez okresu zamówienia — koniec ostatniego
 * zamówienia albo umowy. Brak = kreska.
 */
export function periodEndLine(m: PeriodRow): { text: string; warning: boolean } | null {
 if (m.client_order_start_date || m.client_order_end_date) {
  return {
   text: `→ ${m.client_order_end_date ? fmtDatePl(m.client_order_end_date) : "bezterminowo"}`,
   warning: false,
  };
 }
 if (m.latest_order_end_date) return { text: `→ ${fmtDatePl(m.latest_order_end_date)}`, warning: true };
 if (m.end_date) return { text: `umowa do ${fmtDatePl(m.end_date)}`, warning: false };
 return null;
}

/** Pełny okres umowy i zamówienia w podpowiedzi komórki „Okres”. */
export function periodTitle(m: PeriodRow): string {
 const contract = `Umowa: ${m.start_date ? fmtDatePl(m.start_date) : "—"} – ${
  m.end_date ? fmtDatePl(m.end_date) : "bezterminowo"
 }`;
 const order =
  m.client_order_start_date || m.client_order_end_date
   ? `Zamówienie: ${m.client_order_start_date ? fmtDatePl(m.client_order_start_date) : "—"} – ${
      m.client_order_end_date ? fmtDatePl(m.client_order_end_date) : "bezterminowo"
     }`
   : m.latest_order_end_date
     ? `Aktualne zamówienie klienta kończy się ${fmtDatePl(m.latest_order_end_date)}`
     : "Bez zamówienia klienta";
 return `${contract}\n${order}`;
}

interface ContractsListV2Props {
 /** Reactive search string from the App Router; omitted in isolated embeds/tests. */
 navigationSearch?: string;
 /** Pierwsza kontrolka paska filtrów (wybór klienta). */
 toolbarLead?: ReactNode;
 /** Przyciski z prawej strony rzędu szybkich filtrów (np. „Zamówienia z maila”). */
 trailingActions?: ReactNode;
}

export function ContractsListV2({
 navigationSearch,
 toolbarLead,
 trailingActions,
}: ContractsListV2Props = {}) {
 const user = useAuthStore((state) => state.user);
 const impersonating = useAuthStore((state) => state.realUser !== null);
 // Analityka = zbiorcze kwoty firmy: uprawnienie „Wyniki firmy” (02.11.2026).
 const canSeeContractAnalytics = hasPermission(user, "company_results");
 // Raport „Kontrakty bez zamówienia" = uprawnienie „Moduł Finanse" (strona
 // i trasa raportu pytają o to samo).
 const canSeeOrderlessReport = hasPermission(user, "finance_module");
 // Eksport = trasa `FinanceReadUser`, czyli capability `view_finance`, którą
 // backend wyprowadza z „Modułu Finanse".
 const canExport =
 canSeeOrderlessReport || hasAnalyticsCapability(user, "view_finance");
 // Kolumny stawek widzi też posiadacz „Stawki i kwoty: podgląd" — kwoty
 // klientów spoza jego zakresu serwer i tak redaguje wiersz po wierszu.
 const canSeeFinance = canExport || hasPermission(user, "amounts_view");
 // Marża przy każdym wierszu i plik z całą firmą to wynik firmy („Wyniki
 // firmy”, decyzja Artura 02.11.2026). Delivery Lead widzi swój portfel.
 const canSeeMargin =
 canSeeFinance && (canSeeContractAnalytics || hasRole(user, "delivery_lead"));
 // Zaznaczanie i pasek akcji zbiorczych: przedłużenie („Kontrakty
 // i zamówienia: tworzenie i edycja") albo „Oznacz zakończone" („Zakończenie
 // współpracy…"). Sam odczyt Delivery nie dostaje martwych pól wyboru.
 const canBulkAct =
 !impersonating &&
 hasAnyPermission(user, "contracts_orders_edit", "contract_status");
 // Rozwiązanie umowy z wiersza listy — to samo uprawnienie co
 // „Zakończ współpracę”.
 const canRecordAgreement = !impersonating && hasPermission(user, "contract_status");
 // „Uzupełnij” / „Aktywuj” szkicu w wierszu (dawniej tylko w „Obsłudze
 // kontraktorów”) — „Kontrakty i zamówienia: tworzenie i edycja”.
 const canCompleteDrafts = !impersonating && hasPermission(user, "contracts_orders_edit");
 const [draftToComplete, setDraftToComplete] = useState<ContractorListItem | null>(null);
 const [recordAgreementFor, setRecordAgreementFor] = useState<{
 id: number;
 candidateName: string | null;
 projectEnd: string | null;
 existingDocument: TerminationDocumentRef | null;
 } | null>(null);
 // Queryless `/contracts` is a fresh module entry (Active by default). Every
 // in-module change is encoded back into the URL, including an explicit
 // `status=all`, so a return from details can never be confused with a new
 // opening from the sidebar.
 const [initialListState] = useState(() => {
 const search = typeof window === "undefined" ? "" : window.location.search;
 const parsed = parseContractsListState(search);
 return {
 ...parsed,
 returnTarget: buildContractsListUrl(parsed.state),
 };
 });
 const [search, setSearch] = useState(initialListState.state.search);
 const [statusFilter, setStatusFilter] = useState<ContractStatusValue[]>(
 initialListState.state.statusFilter,
 );
 const [typeFilter, setTypeFilter] = useState<ContractTypeValue[]>(
 initialListState.state.typeFilter,
 );
 // „Kończące się” (18.11.2026): zbiór liczy serwer (`bucket=ending`) —
 // status `ending` albo żywa umowa z końcem w 30 dni. Adres `?ending=30`
 // zostaje, bo prowadzą na niego stare linki „Obsługi kontraktorów”.
 const [endingSoon, setEndingSoon] = useState(initialListState.state.endingSoon);
 // „Stawka z dokumentu” (0739): umowa albo aneks podaje stawkę, której nie
 // ma w harmonogramie — zbiór liczy serwer (`bucket=rate_document`).
 const [rateDocument, setRateDocument] = useState(
 initialListState.state.rateDocument ?? false,
 );
 // „Zamówione po końcu” (19.11.2026): kończący się albo zakończony kontrakt
 // z zamówieniem po końcu projektu — zbiór liczy serwer (`bucket=order_after_end`).
 // „Stawka z faktur” (0782): faktury KSeF pokazują stawkę, której nie ma
 // w harmonogramie — zbiór liczy serwer (`bucket=rate_history`).
 const [rateHistory, setRateHistory] = useState(
 initialListState.state.rateHistory ?? false,
 );
 const [orderAfterEnd, setOrderAfterEnd] = useState(
 initialListState.state.orderAfterEnd ?? false,
 );
 // „Umowa nierozwiązana” (decyzja Artura 28.10.2026): zakończone i kończące się
 // projekty B2B bez zapisanego rozwiązania umowy — lista zaległych porozumień.
 const [agreementNotTerminated, setAgreementNotTerminated] = useState(
 initialListState.state.agreementNotTerminated,
 );
 const [dateRange, setDateRange] = useState<ContractsDateRange>(() => ({
 startFrom: initialListState.state.startFrom,
 startTo: initialListState.state.startTo,
 orderEndFrom: initialListState.state.orderEndFrom,
 orderEndTo: initialListState.state.orderEndTo,
 }));
 const [sort, setSort] = useState<ContractsSort>(() => ({
 by: initialListState.state.sortBy,
 dir: initialListState.state.sortDir,
 }));
 const [page, setPage] = useState(initialListState.state.page);
 // „Grupuj: klient” i „Oś czasu” w „Kończących się” (przebudowa 20.11.2026) —
 // w adresie, żeby powrót z karty kontraktu wracał do tego samego widoku.
 const [groupByClient, setGroupByClient] = useState(
 initialListState.state.groupByClient ?? false,
 );
 const [endingTimeline, setEndingTimeline] = useState(
 initialListState.state.endingTimeline ?? false,
 );
 // Rozwinięte grupy klientów (domyślnie pierwsza) i grupy pokazane w całości.
 const [groupOpen, setGroupOpen] = useState<Record<string, boolean>>({});
 const [groupShowAll, setGroupShowAll] = useState<Record<string, boolean>>({});
 // Kontrakt otwarty w bocznym panelu (`?contract=`). Wybór NIE zeruje strony
 // ani filtrów — to podgląd, nie zawężenie listy.
 const [openContractId, setOpenContractId] = useState<number | null>(
 initialListState.state.selected ?? null,
 );
 const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
 const listRef = useRef<HTMLDivElement>(null);
 const [toast, setToast] = useState<string | null>(null);
 const [exporting, setExporting] = useState(false);
 const [placementsOpen, setPlacementsOpen] = useState(false);
 const queryClient = useQueryClient();
 const restoredScroll = useRef(false);
 const ownNavigationUrl = useRef<string | null>(null);

 const returnTarget = useMemo(
 () =>
 buildContractsListUrl({
 search,
 statusFilter,
 typeFilter,
 endingSoon,
 agreementNotTerminated,
 rateDocument,
 rateHistory,
 orderAfterEnd,
 ...dateRange,
 groupByClient,
 endingTimeline,
 sortBy: sort.by,
 sortDir: sort.dir,
 page,
 selected: openContractId ?? undefined,
 }),
 [
 search,
 statusFilter,
 typeFilter,
 endingSoon,
 agreementNotTerminated,
 rateDocument,
 rateHistory,
 orderAfterEnd,
 dateRange,
 groupByClient,
 endingTimeline,
 sort,
 page,
 openContractId,
 ],
 );

 // Keep the current list entry self-contained. `replaceState` deliberately
 // preserves Next's history payload; replacing it with `null` breaks App
 // Router back/forward bookkeeping.
 useEffect(() => {
 if (typeof window === "undefined") return;
 const current = `${window.location.pathname}${window.location.search}`;
 if (current !== returnTarget) {
 ownNavigationUrl.current = returnTarget;
 window.history.replaceState(window.history.state, "", returnTarget);
 }
 }, [returnTarget]);

 // App Router can keep this component mounted when a user clicks the sidebar
 // link from `/contracts?status=draft` to queryless `/contracts`. Treat that
 // as a genuinely fresh entry, while ignoring the URL updates emitted by the
 // controls above. This also makes same-route back/forward restore URL state.
 useEffect(() => {
 if (navigationSearch === undefined) return;
 const currentUrl = `/contracts${navigationSearch ? `?${navigationSearch}` : ""}`;
 if (ownNavigationUrl.current === currentUrl) {
 ownNavigationUrl.current = null;
 return;
 }
 const next = parseContractsListState(navigationSearch).state;
 setSearch(next.search);
 setStatusFilter(next.statusFilter);
 setTypeFilter(next.typeFilter);
 setEndingSoon(next.endingSoon);
 setRateDocument(next.rateDocument ?? false);
 setRateHistory(next.rateHistory ?? false);
 setOrderAfterEnd(next.orderAfterEnd ?? false);
 setAgreementNotTerminated(next.agreementNotTerminated);
 setDateRange({
 startFrom: next.startFrom,
 startTo: next.startTo,
 orderEndFrom: next.orderEndFrom,
 orderEndTo: next.orderEndTo,
 });
 setGroupByClient(next.groupByClient ?? false);
 setEndingTimeline(next.endingTimeline ?? false);
 setSort({ by: next.sortBy, dir: next.sortDir });
 setPage(next.page);
 setOpenContractId(next.selected ?? null);
 }, [navigationSearch]);

 // Do zapytania idzie wartość zdebouncowana, do inputa surowa — inaczej każde
 // naciśnięcie klawisza wysyłało request (a zapytanie listy robi sześć
 // `selectinload`) i przerzucało tabelę w stan ładowania.
 const debouncedSearch = useDebouncedValue(search, 300);
 // Zakres idzie do API dopiero, gdy jest spójny (od ≤ do).
 const appliedDates = useMemo(() => effectiveDateRange(dateRange), [dateRange]);
 const dateChip = dateRangeChipText(appliedDates);
 const onSort = (key: ContractSortKey) => {
 setSort((current) => nextContractsSort(current, key));
 setPage(1);
 };
 const updateDateRange = (patch: Partial<ContractsDateRange>) => {
 setDateRange((current) => ({ ...current, ...patch }));
 setPage(1);
 };

 // Zaznaczenie operuje na KOMPLECIE umów wiersza. Wiersz zgrupowany pokazuje
 // N umów (N klientów) — checkbox, który wnosiłby tylko umowę główną, robiłby
 // z „Zakończ"/„Przedłuż" cichą, częściową operację: użytkownik zaznacza
 // OSOBĘ, a skutek dotyka połowy jej kontraktów (P1 z przeglądu 2026-08-25).
 const toggleIds = (ids: number[]) => {
 setSelectedIds((prev) => {
 const next = new Set(prev);
 const allSelected = ids.every((id) => next.has(id));
 ids.forEach((id) => {
 if (allSelected) next.delete(id);
 else next.add(id);
 });
 return next;
 });
 };

 // Selection is scoped to the currently-visible result set. Reset it whenever
 // the filters, search, or page change so a bulk action can never target rows
 // the user can no longer see. (Functional guard avoids a needless re-render
 // when nothing is selected.)
 useEffect(() => {
 setSelectedIds((prev) => (prev.size === 0 ? prev : new Set()));
 }, [
 search,
 statusFilter,
 typeFilter,
 endingSoon,
 agreementNotTerminated,
 rateDocument,
 rateHistory,
 orderAfterEnd,
 appliedDates,
 sort,
 page,
 groupByClient,
 ]);

 const flashToast = (msg: string) => {
 setToast(msg);
 setTimeout(() => setToast(null), 3500);
 };

 // Export the currently-filtered contracts to Excel/CSV. Mirrors the list
 // query params so "eksportuj to, co widzę" holds; pagination is intentionally
 // dropped (the endpoint returns every matching row up to its cap).
 const doExport = async (format: "xlsx" | "csv") => {
 if (exporting) return;
 setExporting(true);
 try {
 const params = new URLSearchParams();
 // Zdebouncowana fraza, ta sama którą karmiona jest lista — inaczej w oknie
 // 300 ms eksport dostawałby inne `q` niż to, co widać na ekranie.
 if (debouncedSearch) params.set("q", debouncedSearch);
 statusFilter.forEach((s) => params.append("status", s));
 typeFilter.forEach((t) => params.append("contract_type", t));
 if (endingSoon) params.set("bucket", "ending");
 else if (rateDocument) params.set("bucket", "rate_document");
 else if (rateHistory) params.set("bucket", "rate_history");
 else if (orderAfterEnd) params.set("bucket", "order_after_end");
 if (agreementNotTerminated) params.set("agreement_not_terminated", "true");
 if (appliedDates.startFrom) params.set("start_from", appliedDates.startFrom);
 if (appliedDates.startTo) params.set("start_to", appliedDates.startTo);
 if (appliedDates.orderEndFrom) {
 params.set("order_end_from", appliedDates.orderEndFrom);
 }
 if (appliedDates.orderEndTo) params.set("order_end_to", appliedDates.orderEndTo);
 params.set("format", format);
 const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
 const res = await fetch(`${apiBase}/api/contracts/export?${params}`, {
 credentials: "include",
 headers: getAuthenticatedRequestHeaders(),
 });
 if (!res.ok) {
 flashToast("Eksport nie powiódł się.");
 return;
 }
 const blob = await res.blob();
 const url = URL.createObjectURL(blob);
 const a = document.createElement("a");
 a.href = url;
 a.download = `kontrakty-${new Date().toISOString().slice(0, 10)}.${format}`;
 // Anchor must be in the DOM for a.click() to fire in all browsers; the
 // object URL is revoked lazily so large blobs finish downloading.
 document.body.appendChild(a);
 a.click();
 document.body.removeChild(a);
 setTimeout(() => URL.revokeObjectURL(url), 60_000);
 } finally {
 setExporting(false);
 }
 };

 // Ticket 10: kontrakty bez zamówienia w zakładce „Dokumenty” (cała firma,
 // bez filtrów listy — raport odpowiada na pytanie o wszystkie kontrakty).
 // Backend: uprawnienie „Moduł Finanse" (`FinanceModuleUser`), stąd ta sama
 // bramka co Analityka.
 const doMissingOrdersReport = async () => {
 if (exporting) return;
 setExporting(true);
 try {
 const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
 const res = await fetch(`${apiBase}/api/contracts/missing-orders-report`, {
 credentials: "include",
 headers: getAuthenticatedRequestHeaders(),
 });
 if (!res.ok) {
 flashToast("Nie udało się pobrać raportu kontraktów bez zamówienia.");
 return;
 }
 const blob = await res.blob();
 const url = URL.createObjectURL(blob);
 const a = document.createElement("a");
 a.href = url;
 a.download = `kontrakty-bez-zamowienia-${localTodayIso()}.xlsx`;
 document.body.appendChild(a);
 a.click();
 document.body.removeChild(a);
 setTimeout(() => URL.revokeObjectURL(url), 60_000);
 } catch {
 flashToast("Nie udało się pobrać raportu kontraktów bez zamówienia.");
 } finally {
 setExporting(false);
 }
 };

 // Eksport „Placementy”: kontrakty ze startem w okresie w układzie arkusza
 // Delivery (DL, rekruter, akceptacja, podpis, premia). Okres zamiast filtrów
 // listy — arkusz liczy placementy po starcie, nie po tym, co widać na ekranie.
 const doPlacementsExport = async (range: PlacementsRange): Promise<boolean> => {
 if (exporting) return false;
 setExporting(true);
 try {
 const params = new URLSearchParams({
 start_from: range.from,
 start_to: range.to,
 });
 const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
 const res = await fetch(`${apiBase}/api/contracts/export/placements?${params}`, {
 credentials: "include",
 headers: getAuthenticatedRequestHeaders(),
 });
 if (!res.ok) {
 flashToast("Nie udało się pobrać placementów.");
 return false;
 }
 const blob = await res.blob();
 const url = URL.createObjectURL(blob);
 const a = document.createElement("a");
 a.href = url;
 a.download = placementsExportFilename(range);
 document.body.appendChild(a);
 a.click();
 document.body.removeChild(a);
 setTimeout(() => URL.revokeObjectURL(url), 60_000);
 return true;
 } catch {
 flashToast("Nie udało się pobrać placementów.");
 return false;
 } finally {
 setExporting(false);
 }
 };

 // Bramka „Nowy kontrakt" = POST /api/contracts. Z rejestru capability, NIE
 // z lokalnej reguły — to właśnie ten wzorzec rozjeżdżał się z backendem
 // (audyt F-19).
 const canCreateContract = useCapability("contract.create");

 // Szybki filtr „Kończące się” ma własny widok (odejścia, oś czasu), a
 // „Grupuj: klient” — nagłówki klientów. Oba biorą wszystkie wiersze zbioru
 // naraz: grupa klienta ani lista odejść nie mogą kończyć się na granicy strony.
 const activeQuickFilter: QuickFilterKey | null = agreementNotTerminated
 ? null
 : rateDocument
 ? statusFilter.length === 0
 ? "rate_document"
 : null
 : rateHistory
 ? statusFilter.length === 0
 ? "rate_history"
 : null
 : orderAfterEnd
 ? statusFilter.length === 0
 ? "order_after_end"
 : null
 : endingSoon
 ? statusFilter.length === 0
 ? "ending"
 : null
 : (QUICK_FILTERS.find(
 (filter) => !filter.bucket && sameStatuses(filter.statuses, statusFilter),
 )?.key ?? null);
 const endingView = activeQuickFilter === "ending";
 const groupView = groupByClient && !endingView;
 const allRowsMode = endingView || groupView;

 const listParams = {
 q: debouncedSearch || undefined,
 status: statusFilter.length ? statusFilter : undefined,
 contract_type: typeFilter.length ? typeFilter : undefined,
 // „Kończące się” (18.11.2026): jedna reguła z serwera, nie sama data końca.
 bucket: endingSoon
 ? "ending"
 : rateDocument
 ? "rate_document"
 : rateHistory
 ? "rate_history"
 : orderAfterEnd
 ? "order_after_end"
 : undefined,
 agreement_not_terminated: agreementNotTerminated || undefined,
 start_from: appliedDates.startFrom || undefined,
 start_to: appliedDates.startTo || undefined,
 order_end_from: appliedDates.orderEndFrom || undefined,
 order_end_to: appliedDates.orderEndTo || undefined,
 // Sortuje SERWER — lista jest stronicowana i grupowana po osobie.
 sort_by: sort.by ?? undefined,
 sort_dir: sort.by ? sort.dir : undefined,
 };

 const { data, isLoading, isError, error, refetch, isPlaceholderData } = useQuery({
 queryKey: [
 "contracts-v2",
 debouncedSearch,
 statusFilter,
 typeFilter,
 endingSoon,
 rateDocument,
 rateHistory,
 orderAfterEnd,
 appliedDates,
 sort,
 page,
 agreementNotTerminated,
 ],
 enabled: !allRowsMode,
 queryFn: () =>
 api
 .get("/api/contracts", {
 params: {
 ...listParams,
 // Jeden wiersz na OSOBĘ (konsolidacja kontraktorów wieloklientowych).
 // Grupuje SERWER — grupowanie strony wyników w FE rozdzielałoby osobę
 // między strony paginacji.
 group_by_candidate: true,
 page,
 },
 paramsSerializer: { indexes: null },
 })
 .then((r) => r.data),
 // Poprzednia strona wyników zostaje na ekranie do czasu przyjścia nowej —
 // bez tego lista migocze pustym stanem ładowania przy każdej zmianie filtra.
 placeholderData: keepPreviousData,
 });

 // Ten sam zbiór co lista, umowa po umowie (osoba u dwóch klientów stoi pod
 // każdym z nich). Klucz zaczyna się od `contracts-v2`, więc każda akcja,
 // która odświeża listę, odświeża też ten widok.
 const allRowsQuery = useQuery({
 queryKey: [
 "contracts-v2",
 "all-rows",
 debouncedSearch,
 statusFilter,
 typeFilter,
 endingSoon,
 rateDocument,
 rateHistory,
 orderAfterEnd,
 appliedDates,
 sort,
 agreementNotTerminated,
 ],
 enabled: allRowsMode,
 queryFn: () => fetchAllContractRows(listParams),
 // Poprzednie wiersze zostają tylko w tym samym widoku — odejścia nie mogą
 // na chwilę pokazać grup klientów i odwrotnie.
 placeholderData: (previous, previousQuery) =>
 previousQuery?.queryKey[5] === endingSoon ? previous : undefined,
 });

 // Liczniki szybkich filtrów: ta sama trasa i ten sam zakres co lista
 // (Delivery Lead — swój portfel), tylko status. Bez wyszukiwania i dat,
 // żeby pigułka mówiła, ile jest w module, a nie w bieżącym zawężeniu.
 const quickCounts = useQuery({
 queryKey: ["contracts-quick-counts"],
 staleTime: 60_000,
 queryFn: async () => {
 const entries = await Promise.all(
 QUICK_FILTERS.map(async (filter) => {
 const response = await api.get("/api/contracts", {
 params: {
 status: filter.statuses.length ? filter.statuses : undefined,
 bucket: filter.bucket,
 group_by_candidate: true,
 page: 1,
 // Pigułka potrzebuje samej sumy, nie wierszy.
 page_size: 1,
 },
 paramsSerializer: { indexes: null },
 });
 const total: number =
 response.data?.contracts_total ?? response.data?.total ?? 0;
 return [filter.key, total] as const;
 }),
 );
 return Object.fromEntries(entries) as Record<QuickFilterKey, number>;
 },
 });
 // Ostrzeżenie o szkicach bez danych z dawnej „Obsługi kontraktorów”
 // (`drafts_incomplete` z `/api/contractors/stats`, ta sama bramka podglądu).
 const draftStats = useQuery({
 queryKey: ["contractors-stats-v2"],
 enabled: hasPermission(user, "delivery_view"),
 staleTime: 60_000,
 queryFn: () => contractorsApi.stats().then((r) => r.data),
 });
 const incompleteDrafts = draftStats.data?.drafts_incomplete ?? 0;
 const selectQuickFilter = (key: QuickFilterKey) => {
 const filter = QUICK_FILTERS.find((item) => item.key === key);
 if (!filter) return;
 setStatusFilter([...filter.statuses]);
 setEndingSoon(filter.bucket === "ending");
 setRateDocument(filter.bucket === "rate_document");
 setRateHistory(filter.bucket === "rate_history");
 setOrderAfterEnd(filter.bucket === "order_after_end");
 setAgreementNotTerminated(false);
 setPage(1);
 };

 const items = useMemo<ContractRow[]>(() => data?.items ?? [], [data]);
 const allRows = useMemo<ContractRow[]>(() => allRowsQuery.data?.items ?? [], [allRowsQuery.data]);
 const headline = allRowsMode ? allRowsQuery.data : data;
 const total = data?.total ?? 0;
 const contractorsTotal = headline?.contractors_total ?? headline?.total ?? 0;
 const contractsTotal = headline?.contracts_total ?? headline?.total ?? 0;
 const futureStartTotal: number = headline?.future_start_total ?? 0;
 const today = warsawToday();
 const pageSize = data?.page_size ?? 20;
 const totalPages = Math.max(1, Math.ceil(total / pageSize));
 // Etykieta licznika ma opisywać widok, który użytkownik ma przed sobą.
 // Domyślny widok to „obowiązujące dziś" = Aktywne + Kończące się
 // (`DEFAULT_CONTRACT_STATUS_FILTER`), a kontrakt kończący się nadal jest
 // aktywny — to premisa tej zmiany. Warunek „dokładnie jeden status =
 // active" cofałby licznik do generycznego „osób / kontraktów" właśnie
 // przy domyślnym wejściu do modułu.
 const activeOnly =
 statusFilter.length > 0 &&
 statusFilter.every((value) => RUNNING_CONTRACT_STATUSES.has(value));

 // 403 (stawki = TacPlus na backendzie) i 5xx NIE mogą renderować się jako
 // „Brak kontraktów spełniających kryteria" (audyt F-20).
 const viewState = allRowsMode
 ? resolveViewState({
 isLoading: allRowsQuery.isLoading,
 isError: allRowsQuery.isError,
 error: allRowsQuery.error,
 isEmpty: allRows.length === 0,
 })
 : resolveViewState({
 isLoading,
 isError,
 error,
 isEmpty: items.length === 0,
 });
 const failed =
 viewState === "forbidden" ||
 viewState === "not_found" ||
 viewState === "error";
 const retryList = () => void (allRowsMode ? allRowsQuery.refetch() : refetch());

 // The scroll snapshot is one-shot and only consumed for an explicit return
 // URL. A fresh `/contracts` entry must start at the top even if the previous
 // session happened to use the default Active filter too.
 useEffect(() => {
 if (
 restoredScroll.current ||
 !initialListState.explicit ||
 viewState === "loading"
 ) {
 return;
 }
 restoredScroll.current = true;
 const y = takeContractsListScroll(initialListState.returnTarget);
 if (y == null) return;
 window.setTimeout(() => restoreContractsListScroll(y), 0);
 }, [initialListState, viewState]);

 // „Grupuj: klient”: grupy od największej; rozwinięta domyślnie pierwsza,
 // w rozwiniętej najpierw ROWS_IN_OPEN_GROUP wierszy.
 const clientGroups = useMemo(
 () => (groupView ? groupRowsByClient(allRows, today) : []),
 [groupView, allRows, today],
 );
 const isGroupOpen = (key: string, index: number) => groupOpen[key] ?? index === 0;
 const groupRowsShown = (group: (typeof clientGroups)[number], index: number) => {
 const key = clientGroupKey(group.clientId);
 if (!isGroupOpen(key, index)) return [];
 return groupShowAll[key] ? group.rows : group.rows.slice(0, ROWS_IN_OPEN_GROUP);
 };
 const endingRows = useMemo(
 () => (endingView ? sortByLastDay(allRows as EndingListRow[]) : []),
 [endingView, allRows],
 );

 // Kolejność wierszy na ekranie = kolejność ↑/↓ i zakres „Zaznacz wszystkie”.
 // Wiersz osoby wnosi WSZYSTKIE swoje umowy (patrz `toggleIds`), pas klienta
 // otwiera umowę tego klienta.
 const shownIds: number[] = endingView
 ? endingRows.map((row) => row.id)
 : groupView
 ? clientGroups.flatMap((group, index) => groupRowsShown(group, index).map((row) => row.id))
 : items.flatMap((i) =>
 i.group_members?.length ? i.group_members.map((m) => m.id) : [i.id],
 );
 const visibleIds = shownIds;
 const allVisibleSelected =
 visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
 const someVisibleSelected = visibleIds.some((id) => selectedIds.has(id));
 const rowKeysSignature = shownIds.join(",");
 const rowKeys = useMemo(
 () => (rowKeysSignature ? rowKeysSignature.split(",") : []),
 [rowKeysSignature],
 );
 const previews = useMemo(() => {
 const map = new Map<
 number,
 { candidate_name?: string | null; client_name?: string | null; job_title?: string | null; status?: string | null }
 >();
 for (const i of allRowsMode ? allRows : items) {
 const members = i.group_members?.length ? i.group_members : [rowAsGroupMember(i)];
 for (const m of members) {
 map.set(m.id, {
 candidate_name: i.candidate_name,
 client_name: m.client_name,
 job_title: m.job_title,
 status: m.status,
 });
 }
 }
 return map;
 }, [allRowsMode, allRows, items]);
 const openContract = (id: number) => setOpenContractId(id);
 const closePanel = () => setOpenContractId(null);
 useRowNavigation({
 keys: rowKeys,
 activeKey: openContractId != null ? String(openContractId) : null,
 onChange: (key) => setOpenContractId(Number(key)),
 containerRef: listRef,
 enabled: openContractId != null,
 });

 // Zmiana filtrów zostawia panel tylko wtedy, gdy kontrakt nadal jest na
 // liście — inaczej panel mówiłby o wierszu, którego nie widać. Wejście
 // z adresu (`?contract=`) nie jest zmianą filtrów i panelu nie zamyka.
 const recheckOpenRow = useRef(false);
 const filtersSignature = JSON.stringify([
 debouncedSearch,
 statusFilter,
 typeFilter,
 endingSoon,
 agreementNotTerminated,
 rateDocument,
 rateHistory,
 orderAfterEnd,
 appliedDates,
 ]);
 const previousFilters = useRef(filtersSignature);
 useEffect(() => {
 if (previousFilters.current === filtersSignature) return;
 previousFilters.current = filtersSignature;
 recheckOpenRow.current = true;
 }, [filtersSignature]);
 const activeLoading = allRowsMode ? allRowsQuery.isLoading : isLoading;
 const activePlaceholder = allRowsMode ? allRowsQuery.isPlaceholderData : isPlaceholderData;
 useEffect(() => {
 if (!recheckOpenRow.current || activeLoading || activePlaceholder) return;
 recheckOpenRow.current = false;
 if (openContractId == null) return;
 if (!rowKeys.includes(String(openContractId))) setOpenContractId(null);
 }, [rowKeys, activeLoading, activePlaceholder, openContractId, filtersSignature]);

 // Kolumny tabeli: osoba, klient (w grupie klienta — rekrutacja), [rekrutacja],
 // okres, [koniec umowy, start zamówienia], kwoty, „Co dalej”.
 const compactColumnCount = 3 + (canSeeFinance ? (canSeeMargin ? 3 : 2) : 0) + 1;
 const wideColumnCount = (groupView ? 0 : 1) + 2;
 const columnCount = compactColumnCount + wideColumnCount;
 // Wiersz na całą szerokość między wierszami danych (nagłówek grupy klienta,
 // „Pokaż wszystkie”): `colSpan` większy niż liczba widocznych kolumn dokłada
 // tabeli puste kolumny, więc kolumny szerokiej tabeli dostają własne komórki,
 // ukryte razem z nimi.
 const fullWidthCells = (content: ReactNode, className: string) => (
 <>
 <TableCell colSpan={compactColumnCount} className={className}>
 {content}
 </TableCell>
 {Array.from({ length: wideColumnCount }, (_, i) => (
 <TableCell key={`wide-${i}`} aria-hidden className={cn(WIDE_ONLY_CELL, "p-0")} />
 ))}
 </>
 );

 /** Jedna linia tabeli = jedna umowa; komórka osoby obejmuje jej wszystkie umowy. */
 const renderContractLine = ({
 person: c,
 member: m,
 facts,
 memberIndex,
 memberCount,
 rowIds,
 liveClientCount,
 }: ContractLine) => {
 const multi = memberCount > 1;
 const rowSelected = rowIds.every((id) => selectedIds.has(id));
 const clientId = m.client_id || c.client_id || null;
 const draftAction =
 !multi && m.status === "draft" && c.missing_fields
 ? draftRowAction(c.missing_fields, {
 canSeeRates: canSeeFinance,
 canEditRates: canManageCandidateFinance(user, clientId),
 })
 : null;
 const comparableMargin = hasComparableRateCurrencies(m) ? m.margin : null;
 const marginPct = marginPercent(comparableMargin, m.rate_client);
 const bareAmounts = usesDefaultRateUnit(m);
 // Brak stawki klienta liczy się tylko tam, gdzie konto widzi kwoty tego
 // klienta — u Delivery Leada serwer zeruje stawki spoza jego portfela.
 const steps = listNextSteps(facts, today, {
 canSeeRates: clientId != null && canViewClientFinance(user, clientId),
 });
 const periodEnd = periodEndLine(m);
 const panelOpen = openContractId === m.id;
 const showAgreementButton =
 canRecordAgreement &&
 agreementNotTerminated &&
 m.contract_type === "b2b" &&
 (m.status === "ended" || m.status === "ending");

 return (
 <TableRow
 key={m.id}
 data-contract-member={m.id}
 interactive
 selected={rowSelected}
 {...rowActivationProps(String(m.id), () => openContract(m.id))}
 aria-selected={panelOpen}
 data-tour="contracts.list.row"
 data-selected={panelOpen || undefined}
 // Spokojna tabela: jedna cienka linia między wierszami, bez
 // zebry. Wyróżnia się tylko wiersz zaznaczony i ten, którego
 // panel jest otwarty.
 className={cn(
 "h-auto xl:h-[50px] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
 rowSelected
 ?"bg-primary/10!"
 : panelOpen
 ?"bg-primary/5! shadow-[inset_3px_0_0_0_hsl(var(--primary))]"
 : undefined,
 "max-xl:grid max-xl:h-auto max-xl:grid-cols-2 max-xl:bg-card",
 )}
 >
 {memberIndex === 0 && (
 <TableCell
 rowSpan={memberCount}
 data-label="Osoba"
 className={cn(
 "align-top px-2 py-2 max-xl:col-span-2 max-xl:block max-xl:border-b max-xl:border-border max-xl:bg-muted/40",
 openContractId === c.id && "bg-primary/5",
 )}
 // Komórka osoby otwiera umowę główną (`c.id`), nie pas,
 // w którym akurat leży; kwadracik i link zostają sobą.
 onClick={(e) => {
 e.stopPropagation();
 if (!clickFromInteractive(e)) openContract(c.id);
 }}
 >
 <div className="flex min-w-0 items-start gap-2">
 {canBulkAct && (
 <Checkbox
 checked={rowSelected}
 onCheckedChange={() => toggleIds(rowIds)}
 aria-label={
 multi
 ? `Zaznacz wszystkie kontrakty: ${c.candidate_name ?? c.id}`
 : `Zaznacz kontrakt ${c.id}`
 }
 />
 )}
 <div className="min-w-0">
 {/* Imion i nazwisk nie ucinamy (wariant A) — długie łamią się
 na dwie linie. */}
 <Link
 href={buildContractDetailHref(c.id, returnTarget)}
 onClick={() => rememberContractsListScroll(returnTarget)}
 className="block wrap-break-word text-[13px] font-semibold leading-4 text-foreground hover:text-primary"
 >
 {c.candidate_name ?? `#${c.id}`}
 </Link>
 <RateDocumentRowNote change={c.rate_document_change} />
 <RateHistoryRowNote change={c.rate_history_change} />
 <OrderAfterEndRowNote summary={c.order_after_end} />
 {liveClientCount > 1 && (
 <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
 pracuje u {liveClientCount} klientów
 </div>
 )}
 </div>
 </div>
 </TableCell>
 )}

 <TableCell
 data-label={groupView ? "Rekrutacja" : "Klient"}
 className="px-2 py-1.5 align-top max-xl:block max-xl:min-w-0 max-xl:border-b max-xl:border-b-border/60"
 >
 <MobileFieldLabel>{groupView ? "Rekrutacja" : "Klient"}</MobileFieldLabel>
 {groupView ? (
 <TruncatedText className="max-w-full text-[12px] font-medium leading-4">
 {m.job_title ?? null}
 </TruncatedText>
 ) : (
 <Link
 href={buildContractDetailHref(m.id, returnTarget)}
 onClick={() => rememberContractsListScroll(returnTarget)}
 className="block min-w-0 hover:text-primary"
 >
 <TruncatedText className="max-w-full text-[12px] font-semibold leading-4">
 {m.client_name ?? null}
 </TruncatedText>
 </Link>
 )}
 <div className="flex min-w-0 items-center gap-1.5">
 <ContractRowNote
 status={m.status}
 contractType={m.contract_type}
 statusLabel={m.status ? CONTRACT_STATUS_BADGE[m.status]?.label : undefined}
 // Status nie ustępuje miejsca rekrutacji obok — inaczej napisy na siebie wchodzą.
 className="shrink-0"
 />
 {!groupView && m.job_title && (
 <TruncatedText className={cn("min-w-0 max-w-full text-[11px] leading-4 text-muted-foreground", WIDE_HIDDEN)}>
 {m.job_title}
 </TruncatedText>
 )}
 </div>
 </TableCell>

 {!groupView && (
 <TableCell
 data-testid="contract-job-cell"
 className={cn(WIDE_ONLY_CELL, "px-2 py-1.5 align-top")}
 >
 {m.job_title ? (
 <TruncatedText className="max-w-full text-[12px] leading-4">
 {m.job_title}
 </TruncatedText>
 ) : (
 <span className={cn("text-[12px]", CALM_EMPTY)}>—</span>
 )}
 </TableCell>
 )}

 <TableCell
 data-label="Okres"
 title={periodTitle(m)}
 className="px-2 py-1.5 align-top whitespace-nowrap tabular-nums max-xl:block max-xl:border-b max-xl:border-b-border/60"
 >
 <MobileFieldLabel>Okres</MobileFieldLabel>
 <div className="text-[12px] font-medium leading-4 text-foreground">
 {m.start_date ? fmtDatePl(m.start_date) : <span className={CALM_EMPTY}>—</span>}
 </div>
 <div
 data-testid="contract-period-end"
 className={cn(
 "text-[11px] leading-4",
 periodEnd?.warning ? "text-warning-muted-foreground" : "text-muted-foreground",
 )}
 >
 {periodEnd ? periodEnd.text : <span className={CALM_EMPTY}>—</span>}
 </div>
 </TableCell>

 <TableCell
 data-testid="contract-end-cell"
 title="Data zakończenia umowy"
 className={cn(WIDE_ONLY_CELL, "px-2 py-1.5 align-top whitespace-nowrap text-[12px] leading-4 tabular-nums")}
 >
 {m.end_date ? fmtDatePl(m.end_date) : <span className={CALM_EMPTY}>—</span>}
 </TableCell>
 <TableCell
 data-testid="contract-order-start-cell"
 title="Początek okresu zamówienia — z najnowszego uzupełnionego zamówienia tej osoby."
 className={cn(WIDE_ONLY_CELL, "px-2 py-1.5 align-top whitespace-nowrap text-[12px] leading-4 tabular-nums")}
 >
 {m.client_order_start_date ? (
 fmtDatePl(m.client_order_start_date)
 ) : (
 <span className={CALM_EMPTY}>—</span>
 )}
 </TableCell>

 {canSeeFinance && (
 <>
 <TableCell
 data-label="Stawka kosztowa"
 className="px-2 py-1.5 text-right align-top tabular-nums text-[12px] leading-4 whitespace-nowrap max-xl:block max-xl:border-b max-xl:border-b-border/60 max-xl:text-left"
 >
 <MobileFieldLabel unit={bareAmounts ? DEFAULT_RATE_UNIT_LABEL : undefined}>Stawka kosztowa</MobileFieldLabel>
 {m.rate_candidate != null ? (
 <RateAmount
 value={m.rate_candidate}
 currency={candidateCurrency(m)}
 unit={m.rate_unit}
 bare={bareAmounts}
 />
 ) : (
 <span className={CALM_EMPTY}>—</span>
 )}
 </TableCell>
 <TableCell
 data-label="Stawka przychodowa"
 className="px-2 py-1.5 text-right align-top tabular-nums text-[12px] leading-4 whitespace-nowrap max-xl:block max-xl:border-b max-xl:border-b-border/60 max-xl:text-left"
 >
 <MobileFieldLabel unit={bareAmounts ? DEFAULT_RATE_UNIT_LABEL : undefined}>Stawka przychodowa</MobileFieldLabel>
 {m.rate_client != null ? (
 <RateAmount
 value={m.rate_client}
 currency={clientCurrency(m)}
 unit={m.rate_unit}
 bare={bareAmounts}
 />
 ) : (
 <span className={CALM_EMPTY}>—</span>
 )}
 </TableCell>
 {canSeeMargin && (
 <TableCell
 data-label="Marża"
 className="px-2 py-1.5 text-right align-top tabular-nums text-[12px] leading-4 whitespace-nowrap max-xl:block max-xl:border-b max-xl:border-b-border/60 max-xl:text-left"
 >
 <MobileFieldLabel unit={bareAmounts ? DEFAULT_RATE_UNIT_LABEL : undefined}>Marża</MobileFieldLabel>
 {/* Marża = różnica stawek w jednostce kontraktu — ta sama
 jednostka co przy stawkach obok: w nagłówku (zł/h) albo,
 dla wiersza w innej jednostce, przy kwocie (bez niej
 „43 zł” czytało się jak kwota miesięczna). */}
 <span
 className={marginColor(
 comparableMargin ?? undefined,
 m.rate_client ?? undefined,
 )}
 >
 {comparableMargin != null
 ? bareAmounts
 ? BARE_AMOUNT.format(comparableMargin)
 : formatCurrency(comparableMargin, clientCurrency(m))
 :"—"}
 </span>
 {comparableMargin != null && !bareAmounts && (
 <RateUnitSuffix unit={m.rate_unit} />
 )}
 {marginPct && (
 <span className="block text-[11px] font-normal text-muted-foreground">
 {marginPct}
 </span>
 )}
 </TableCell>
 )}
 </>
 )}

 <TableCell
 data-label="Co dalej"
 className="px-2 py-1.5 align-top max-xl:col-span-2 max-xl:block"
 >
 <MobileFieldLabel>Co dalej</MobileFieldLabel>
 <ContractNextCell steps={steps}>
 {/* Szkic (dawna „Obsługa kontraktorów”): „Uzupełnij · N braki” albo
 „Aktywuj” dla osoby z edycją, sam opis braków dla podglądu. Tylko
 wiersz jednej umowy — w grupie brak jest w panelu umowy. */}
 {draftAction?.kind === "waits-for-rates" ? (
 <span
 className="whitespace-nowrap text-[11px] font-medium leading-tight text-warning-muted-foreground"
 title={`Stawki uzupełnia osoba z uprawnieniem „${permissionLabel("amounts_edit")}”`}
 >
 Czeka na stawki
 </span>
 ) : draftAction && canCompleteDrafts ? (
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 setDraftToComplete(draftFromRow(c));
 }}
 aria-label={
 draftAction.kind === "activate"
 ? "Aktywuj"
 : `Uzupełnij · ${missingCountLabel(draftAction.fields.length)}`
 }
 title={
 draftAction.kind === "activate"
 ? "Szkic ma komplet danych do aktywacji"
 : missingFieldsHint(draftAction.fields)
 }
 className="shrink-0 whitespace-nowrap rounded-md border border-border bg-card px-1.5 py-0.5 text-[11px] font-medium text-primary hover:bg-muted"
 >
 {draftAction.kind === "activate"
 ? "Aktywuj"
 : `Uzupełnij · ${draftAction.fields.length}`}
 </button>
 ) : draftAction ? (
 <span
 className="whitespace-nowrap text-[11px] text-muted-foreground"
 title={
 draftAction.kind === "activate"
 ? "Szkic ma komplet danych — aktywuje osoba z edycją kontraktów"
 : missingFieldsHint(draftAction.fields)
 }
 >
 {draftAction.kind === "activate"
 ? "gotowy"
 : missingCountLabel(draftAction.fields.length)}
 </span>
 ) : null}
 {/* Zgłoszenie zespołu 29.10.2026: rozwiązanie umowy podpisane
 poza NEXUSEM zapisuje się wprost z listy „Umowa nierozwiązana”. */}
 {showAgreementButton && (
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 setRecordAgreementFor({
 id: m.id,
 candidateName: c.candidate_name ?? null,
 projectEnd: m.end_date ?? null,
 existingDocument: facts.termination_document ?? null,
 });
 }}
 className="shrink-0 whitespace-nowrap rounded-md border border-border bg-card px-1.5 py-0.5 text-[11px] font-medium text-primary hover:bg-muted"
 title={
 facts.termination_document
 ? `${terminationDocKind(facts.termination_document)} jest w Dokumentach („${facts.termination_document.filename}”) — zapisz daty z pliku`
 : "Porozumienie albo wypowiedzenie podpisane poza NEXUSEM"
 }
 >
 + Rozwiązanie
 </button>
 )}
 </ContractNextCell>
 </TableCell>
 </TableRow>
 );
 };

 // Status spoza zestawów pigułek (np. same „Zakończone”) stoi jako chip,
 // żeby zawężenie z „Więcej filtrów” było widać bez otwierania okienka.
 const customStatuses =
 activeQuickFilter == null && statusFilter.length > 0
 ? `Status: ${statusFilter.map((value) => contractStatusLabel(value)).join(", ")}`
 : null;
 const moreFiltersCount = typeFilter.length + (customStatuses ? 1 : 0) + (dateChip ? 1 : 0);

 const listContent = (
 <div className="space-y-3">
 {/* Nagłówek zwarty: tytuł i licznik w jednej linii — laptop 1280×720
 ma zobaczyć tabelę w górnych 60% okna. */}
 <div className="flex flex-wrap items-center justify-between gap-2">
 <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5">
 <h1 className="text-lg font-semibold text-foreground">Kontrakty</h1>
 <p className="text-xs text-muted-foreground">
 {activeLoading
 ?"Ładowanie…"
 : failed
 ?"Nie udało się pobrać listy"
 : contractorsCountText(
 contractorsTotal,
 contractsTotal,
 activeOnly,
 futureStartTotal,
 )}
 </p>
 </div>
 <div className="flex flex-wrap items-center gap-2">
 {canSeeContractAnalytics && (
 <Link href="/contracts/analytics">
 <Button size="sm" variant="outline">
 <TrendingUp className="h-4 w-4" /> Analityka
 </Button>
 </Link>
 )}
 {/* E5a (22.11.2026): dane firm z podpisanych umów do potwierdzenia
 przed nową umową B2B — ta sama bramka co trasy API. */}
 {canCompleteDrafts && (
 <Link href="/contracts/dane-firm">
 <Button size="sm" variant="outline">
 <FileText className="h-4 w-4" /> Dane firm z umów
 </Button>
 </Link>
 )}
 {canExport && <Popover>
 <PopoverTrigger asChild>
 <Button size="sm" variant="outline" disabled={exporting}>
 <Download className="h-4 w-4" /> {exporting ? "Eksportuję…" : "Eksport"}
 </Button>
 </PopoverTrigger>
 <PopoverContent align="end" className="w-auto min-w-44 p-1">
 {canSeeContractAnalytics && (
 <>
 <button
 onClick={() => doExport("xlsx")}
 className="block w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-primary/10"
 >
 Excel (.xlsx)
 </button>
 <button
 onClick={() => doExport("csv")}
 className="block w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-primary/10"
 >
 CSV
 </button>
 </>
 )}
 <button
 onClick={() => setPlacementsOpen(true)}
 className="block w-full whitespace-nowrap text-left px-3 py-1.5 text-sm rounded-md hover:bg-primary/10"
 >
 Placementy (.xlsx)
 </button>
 {canSeeOrderlessReport && (
 <>
 <div className="my-1 h-px bg-border" aria-hidden="true" />
 <button
 onClick={() => void doMissingOrdersReport()}
 className="block w-full whitespace-nowrap text-left px-3 py-1.5 text-sm rounded-md hover:bg-primary/10"
 >
 Kontrakty bez zamówienia (.xlsx)
 </button>
 </>
 )}
 </PopoverContent>
 </Popover>}
 {recordAgreementFor && (
 <ContractAgreementRecordDialog
 contractId={recordAgreementFor.id}
 candidateName={recordAgreementFor.candidateName}
 projectEnd={recordAgreementFor.projectEnd}
 existingDocument={recordAgreementFor.existingDocument}
 onClose={() => setRecordAgreementFor(null)}
 />
 )}
 {canCompleteDrafts && draftToComplete && (
 <DraftCompletionModal
 contractor={draftToComplete}
 open={!!draftToComplete}
 onOpenChange={(open) => {
 if (!open) setDraftToComplete(null);
 }}
 onActivated={() => {
 setDraftToComplete(null);
 queryClient.invalidateQueries({ queryKey: ["contracts-v2"] });
 queryClient.invalidateQueries({ queryKey: ["contracts-quick-counts"] });
 queryClient.invalidateQueries({ queryKey: ["contractors-stats-v2"] });
 }}
 />
 )}
 {canExport && (
 <PlacementsExportDialog
 open={placementsOpen}
 onOpenChange={setPlacementsOpen}
 busy={exporting}
 onExport={doPlacementsExport}
 />
 )}
 {canCreateContract && (
 <Link href="/contracts/new">
 <Button size="sm" variant="primary">
 <Plus className="h-4 w-4" /> Nowy kontrakt
 </Button>
 </Link>
 )}
 </div>
 </div>

 <div className="flex flex-wrap items-center gap-2">
 <div
 role="group"
 aria-label="Szybkie filtry kontraktów"
 data-tour="contracts.quick-filters"
 className="flex flex-wrap items-center gap-1.5"
 >
 {QUICK_FILTERS.map((filter) => {
 const selected = activeQuickFilter === filter.key;
 const count = quickCounts.data?.[filter.key];
 if (filter.onlyWhenNotEmpty && !selected && !count) return null;
 const alarming = filter.key === "order_after_end" && !selected;
 return (
 <button
 key={filter.key}
 type="button"
 // Strażnik kotwic nowości czyta kotwicę z linii `data-tour` — jedna linia.
 data-tour={filter.key === "rate_document" ? "contracts.rate-document" : filter.key === "rate_history" ? "contracts.rate-history" : filter.key === "order_after_end" ? "contracts.order-after-end" : filter.key === "ending" ? "contracts.ending-pill" : undefined}
 aria-pressed={selected}
 title={filter.hint}
 onClick={() => selectQuickFilter(filter.key)}
 className={cn(
 "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors pointer-coarse:h-10",
 "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
 selected
 ? "border-primary bg-primary/10 text-primary"
 : "border-border bg-card text-muted-foreground hover:border-primary/50 hover:text-foreground",
 )}
 >
 {filter.label}
 {count !== undefined ? (
 <span
 className={cn(
 "rounded-full px-1.5 text-[11px] font-semibold leading-5 tabular-nums",
 selected
 ? "bg-primary text-primary-foreground"
 : alarming
 ? "bg-destructive/10 text-destructive"
 : "bg-muted text-foreground",
 )}
 >
 {count}
 </span>
 ) : null}
 </button>
 );
 })}
 </div>
 <div className="ml-auto flex flex-wrap items-center gap-2">
 {incompleteDrafts > 0 && activeQuickFilter !== "pending" ? (
 <button
 type="button"
 onClick={() => selectQuickFilter("pending")}
 title="Pokaż szkice do uzupełnienia"
 className="flex h-8 items-center gap-1.5 rounded-md border border-warning/25 bg-warning-muted px-2 text-xs font-semibold text-warning-muted-foreground hover:border-warning/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:h-10"
 >
 <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
 {`${incompleteDrafts} ${pluralPl(incompleteDrafts, "szkic", "szkice", "szkiców")} z brakami`}
 </button>
 ) : null}
 {trailingActions}
 </div>
 </div>

 {/* Filtry — wszystkie kontrolki mają 32 px wysokości (h-8). Status, typ
 i daty są w „Więcej filtrów” (wariant A 20.11.2026): status w pasku
 dublował pigułki („Status: 2” = „Aktywne”). */}
 <div className="flex flex-wrap items-center gap-2">
 {toolbarLead}
 <div className="flex-1 min-w-[220px] max-w-md">
 <Input
 className="h-8"
 leadingIcon={<Search className="h-4 w-4" />}
 placeholder="Szukaj po kandydacie, kliencie, pozycji…"
 value={search}
 onChange={(e) => {
 setSearch(e.target.value);
 setPage(1);
 }}
 />
 </div>
 <ContractsMoreFilters
 statusFilter={statusFilter}
 onStatusChange={(v) => {
 setStatusFilter(v);
 setEndingSoon(false);
 setPage(1);
 }}
 typeFilter={typeFilter}
 onTypeChange={(v) => {
 setTypeFilter(v);
 setPage(1);
 }}
 dateRange={dateRange}
 onDateChange={updateDateRange}
 activeCount={moreFiltersCount}
 />
 {/* „Umowa nierozwiązana” (decyzja Artura 28.10.2026): zaległe rozwiązania
 umów B2B po zakończeniu projektu. Filtr idzie na wszystkie statusy
 (zbiór to Zakończony + Kończący się); wyłączenie wraca do domyślnych. */}
 <Button
 size="sm"
 variant="outline"
 aria-pressed={agreementNotTerminated}
 data-tour="contracts.list.agreement-not-terminated"
 className={cn(
 "gap-1.5",
 agreementNotTerminated &&
 "border-warning/40 bg-warning-muted text-warning-muted-foreground hover:bg-warning-muted",
 )}
 title="Kontrakty B2B zakończone albo kończące się, w których nie zapisano rozwiązania umowy"
 onClick={() => {
 if (agreementNotTerminated) {
 setAgreementNotTerminated(false);
 if (statusFilter.length === 0) {
 setStatusFilter([...DEFAULT_CONTRACT_STATUS_FILTER]);
 }
 } else {
 setAgreementNotTerminated(true);
 setStatusFilter([]);
 setEndingSoon(false);
 setRateDocument(false);
 setRateHistory(false);
 }
 setPage(1);
 }}
 >
 <FileWarning className="h-4 w-4" aria-hidden="true" />
 Umowa nierozwiązana
 {agreementNotTerminated && <X className="h-3.5 w-3.5" aria-hidden="true" />}
 </Button>
 {/* „Grupuj: klient” (wariant B, 20.11.2026): nagłówek grupy z liczbą
 osób, marżą miesięczną i tym, co się kończy albo startuje.
 „Kończące się” mają własny widok, więc tam przełącznika nie ma. */}
 {!endingView && (
 <Button
 size="sm"
 variant="outline"
 aria-pressed={groupByClient}
 data-tour="contracts.group-by-client"
 className={cn("gap-1.5", groupByClient && "border-primary/40 bg-primary/10 text-primary hover:bg-primary/10")}
 title="Wiersze pod klientami: liczba osób, marża miesięczna, kto odchodzi i kto startuje"
 onClick={() => {
 setGroupByClient((current) => !current);
 setPage(1);
 }}
 >
 <Layers className="h-4 w-4" aria-hidden="true" />
 Grupuj: klient
 {groupByClient && <X className="h-3.5 w-3.5" aria-hidden="true" />}
 </Button>
 )}
 {typeFilter.map((type) => (
 <Button
 key={type}
 size="sm"
 variant="outline"
 className="gap-1"
 aria-label={`Usuń filtr typu: ${contractTypeLabel(type)}`}
 onClick={() => {
 setTypeFilter((current) => current.filter((value) => value !== type));
 setPage(1);
 }}
 >
 {contractTypeLabel(type)}
 <X className="h-3.5 w-3.5" />
 </Button>
 ))}
 {customStatuses && (
 <Button
 size="sm"
 variant="outline"
 className="gap-1"
 aria-label={`Usuń filtr statusu: ${customStatuses}`}
 onClick={() => {
 setStatusFilter([...DEFAULT_CONTRACT_STATUS_FILTER]);
 setPage(1);
 }}
 >
 {customStatuses}
 <X className="h-3.5 w-3.5" />
 </Button>
 )}
 {dateChip && (
 <Button
 size="sm"
 variant="outline"
 className="gap-1"
 aria-label={`Usuń filtr dat: ${dateChip}`}
 onClick={() => updateDateRange(EMPTY_DATE_RANGE)}
 >
 {dateChip}
 <X className="h-3.5 w-3.5" />
 </Button>
 )}
 {endingSoon && activeQuickFilter !== "ending" && (
 <Button
 size="sm"
 variant="outline"
 className="gap-1"
 onClick={() => {
 setEndingSoon(false);
 setPage(1);
 }}
 >
 Kończące się
 <X className="h-3.5 w-3.5" />
 </Button>
 )}
 </div>

 {/* Pasek akcji zbiorczych dla posiadaczy przedłużania ALBO zakończenia
 współpracy (każdy przycisk ma własne uprawnienie w samym pasku). Sam
 odczyt Delivery nie dostaje martwych pól wyboru. */}
 {canBulkAct && (
 <ContractsBulkActionsBarV2
 selectedIds={selectedIds}
 onClear={() => setSelectedIds(new Set())}
 onSelectAllVisible={() =>
 setSelectedIds(allVisibleSelected ? new Set() : new Set(visibleIds))
 }
 visibleCount={allRowsMode ? shownIds.length : items.length}
 onDone={(msg) => {
 setToast(msg);
 setTimeout(() => setToast(null), 3500);
 queryClient.invalidateQueries({ queryKey: ["contracts-v2"] });
 queryClient.invalidateQueries({ queryKey: ["contracts-quick-counts"] });
 setSelectedIds(new Set());
 }}
 />
 )}

 {endingView ? (
 /* „Kończące się” (wariant A + oś czasu z B, 20.11.2026): odejścia do
 domknięcia zamiast tej samej tabeli z datą końca drobnym drukiem. */
 <ContractsEndingView
 rows={endingRows}
 state={viewState}
 onRetry={retryList}
 timeline={endingTimeline}
 onTimelineChange={setEndingTimeline}
 today={today}
 canSeeMargin={canSeeMargin}
 canRecordAgreement={canRecordAgreement}
 canBulkAct={canBulkAct}
 selectedIds={selectedIds}
 onToggleSelected={toggleIds}
 openContractId={openContractId}
 onOpen={openContract}
 detailHref={(id) => buildContractDetailHref(id, returnTarget)}
 onDetailLinkClick={() => rememberContractsListScroll(returnTarget)}
 onRecordAgreement={(row) =>
 setRecordAgreementFor({
 id: row.id,
 candidateName: row.candidate_name ?? null,
 projectEnd: row.end_date ?? null,
 existingDocument: row.termination_document ?? null,
 })
 }
 truncated={Boolean(allRowsQuery.data?.truncated)}
 />
 ) : (
 /* Tabela „Aktywne” (wariant A, 20.11.2026): pełne nazwiska, okres
 w jednej kolumnie, „Co dalej” słowami zamiast kolumn „Typ” i „Status”
 (inny typ albo status stoi drobnym drukiem przy kliencie). Szeroka
 tabela (≥ 1700 px) dokłada rekrutację, koniec umowy i start zamówienia
 jako własne kolumny. */
 <div className={WIDE_TABLE_CONTAINER}>
 <Table
 density="compact"
 className="table-fixed text-xs max-xl:block"
 data-contracts-responsive-table
 data-group-by-client={groupView || undefined}
 >
 <colgroup className="max-xl:hidden">
 {canSeeFinance && canSeeMargin ? (
 <>
 <col className="w-[17%] @min-[1700px]:w-[12%]" />
 <col className="w-[16%] @min-[1700px]:w-[11%]" />
 {!groupView && <col className={cn(WIDE_ONLY_COL, "w-[12%]")} />}
 <col className="w-[10%] @min-[1700px]:w-[7%]" />
 <col className={cn(WIDE_ONLY_COL, "w-[6%]")} />
 <col className={cn(WIDE_ONLY_COL, "w-[6%]")} />
 <col className="w-[8%] @min-[1700px]:w-[6%]" />
 <col className="w-[8%] @min-[1700px]:w-[6%]" />
 <col className="w-[8%] @min-[1700px]:w-[6%]" />
 <col />
 </>
 ) : canSeeFinance ? (
 <>
 <col className="w-[18%] @min-[1700px]:w-[13%]" />
 <col className="w-[18%] @min-[1700px]:w-[12%]" />
 {!groupView && <col className={cn(WIDE_ONLY_COL, "w-[13%]")} />}
 <col className="w-[11%] @min-[1700px]:w-[7%]" />
 <col className={cn(WIDE_ONLY_COL, "w-[6%]")} />
 <col className={cn(WIDE_ONLY_COL, "w-[6%]")} />
 <col className="w-[9%] @min-[1700px]:w-[7%]" />
 <col className="w-[9%] @min-[1700px]:w-[7%]" />
 <col />
 </>
 ) : (
 <>
 <col className="w-[22%] @min-[1700px]:w-[15%]" />
 <col className="w-[22%] @min-[1700px]:w-[14%]" />
 {!groupView && <col className={cn(WIDE_ONLY_COL, "w-[16%]")} />}
 <col className="w-[12%] @min-[1700px]:w-[8%]" />
 <col className={cn(WIDE_ONLY_COL, "w-[7%]")} />
 <col className={cn(WIDE_ONLY_COL, "w-[7%]")} />
 <col />
 </>
 )}
 </colgroup>
 <TableHeader className="max-xl:hidden">
 <TableRow>
 <SortableHead label="Osoba" sortKey="candidate" sort={sort} onSort={onSort}>
 {canBulkAct && (
 <Checkbox
 checked={
 allVisibleSelected
 ? true
 : someVisibleSelected
 ?"indeterminate"
 : false
 }
 onCheckedChange={(v) =>
 setSelectedIds(v ? new Set(visibleIds) : new Set())
 }
 aria-label="Zaznacz wszystkie"
 />
 )}
 </SortableHead>
 {groupView ? (
 <TableHead className="px-2">Rekrutacja</TableHead>
 ) : (
 <SortableHead label="Klient" sortKey="client" sort={sort} onSort={onSort} />
 )}
 {!groupView && <TableHead className={cn(WIDE_ONLY_CELL, "px-2")}>Rekrutacja</TableHead>}
 <SortableHead
 label="Okres"
 sortKey="start_date"
 sort={sort}
 onSort={onSort}
 title="Start umowy → koniec bieżącego zamówienia klienta; sortuje po dacie startu"
 />
 <TableHead className={cn(WIDE_ONLY_CELL, "px-2")}>Koniec umowy</TableHead>
 <TableHead className={cn(WIDE_ONLY_CELL, "px-2")}>Start zamówienia</TableHead>
 {canSeeFinance && (
 <>
 <SortableHead
 label="Koszt"
 sortKey="rate_candidate"
 sort={sort}
 onSort={onSort}
 align="right"
 unit={DEFAULT_RATE_UNIT_LABEL}
 title="Stawka kosztowa — konsultant"
 />
 <SortableHead
 label="Przychód"
 sortKey="rate_client"
 sort={sort}
 onSort={onSort}
 align="right"
 unit={DEFAULT_RATE_UNIT_LABEL}
 title="Stawka przychodowa — klient"
 />
 {canSeeMargin && (
 <SortableHead
 label="Marża"
 sortKey="margin"
 sort={sort}
 onSort={onSort}
 align="right"
 unit={DEFAULT_RATE_UNIT_LABEL}
 />
 )}
 </>
 )}
 <SortableHead
 label="Co dalej"
 sortKey="order_end_date"
 sort={sort}
 onSort={onSort}
 title="Co trzeba zrobić — te same progi co pas „Co się dzieje” na kontrakcie; sortuje po końcu zamówienia klienta"
 data-tour="contracts.list.next"
 />
 </TableRow>
 </TableHeader>
 {viewState === "loading" ? (
 <TableBody className="max-xl:block max-xl:w-full">
 <TableRow className="max-xl:block max-xl:h-auto max-xl:w-full">
 <TableCell colSpan={columnCount} className="text-center py-10 text-muted-foreground max-xl:block max-xl:w-full">
 {allRowsMode ? "Ładowanie wszystkich kontraktów zbioru…" : "Ładowanie…"}
 </TableCell>
 </TableRow>
 </TableBody>
 ) : failed ? (
 <TableBody className="max-xl:block max-xl:w-full">
 <TableRow className="max-xl:block max-xl:h-auto max-xl:w-full">
 <TableCell colSpan={columnCount} className="p-0 max-xl:block max-xl:w-full">
 <QueryStateNotice
 state={viewState as "forbidden" | "not_found" | "error"}
 className="border-0"
 description={
 viewState === "forbidden"
 ?"Nie masz uprawnienia do rejestru kontraktów. Rejestr NIE jest pusty — poproś administratora o dostęp (Ustawienia → Zespół i dostęp → Osoby i role)."
 : undefined
 }
 onRetry={retryList}
 />
 </TableCell>
 </TableRow>
 </TableBody>
 ) : viewState === "empty" ? (
 <TableBody className="max-xl:block max-xl:w-full">
 <TableRow className="max-xl:block max-xl:h-auto max-xl:w-full">
 <TableCell colSpan={columnCount} className="text-center py-10 max-xl:block max-xl:w-full">
 <FileText className="h-10 w-10 mx-auto text-muted-foreground mb-2 opacity-40" />
 <p className="text-sm text-muted-foreground">
 Brak kontraktów spełniających kryteria.
 </p>
 </TableCell>
 </TableRow>
 </TableBody>
 ) : groupView ? (
 clientGroups.map((group, index) => {
 const key = clientGroupKey(group.clientId);
 const open = isGroupOpen(key, index);
 const shown = groupRowsShown(group, index);
 return (
 <TableBody
 key={key}
 data-client-group={key}
 className="max-xl:mb-3 max-xl:block max-xl:overflow-hidden max-xl:rounded-lg max-xl:border max-xl:border-border max-xl:bg-card"
 >
 <TableRow className="h-auto border-b border-border bg-muted/40 hover:bg-muted/40 max-xl:block">
 {fullWidthCells(
 <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px]">
 <button
 type="button"
 aria-expanded={open}
 onClick={() => setGroupOpen((current) => ({ ...current, [key]: !open }))}
 className="inline-flex min-w-0 items-center gap-1.5 rounded-sm text-left font-semibold text-foreground hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
 >
 {open ? (
 <ChevronDown className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
 ) : (
 <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
 )}
 <span className="truncate" title={group.name}>{group.name}</span>
 </button>
 <span className="text-muted-foreground">· {peopleLabel(group.people)}</span>
 {canSeeMargin && (
 <span
 className="text-muted-foreground tabular-nums"
 title={group.margin.unpriced ? `Bez ${group.margin.unpriced} umów bez stawki albo w innej walucie` : undefined}
 >
 · marża {formatPlnWhole(group.margin.total)}/mies.
 </span>
 )}
 {group.leaving > 0 && (
 <span className="font-medium text-warning-muted-foreground">· {group.leaving} odchodzi</span>
 )}
 {group.starting > 0 && (
 <span className="font-medium text-info">· {group.starting} startuje</span>
 )}
 {group.clientId != null && (
 <Link
 href={`/clients/${group.clientId}?tab=konsultanci`}
 className="ml-auto text-[12px] font-medium text-primary hover:underline"
 >
 Konsultanci u klienta →
 </Link>
 )}
 </div>,
 "px-2 py-1.5 max-xl:block",
 )}
 </TableRow>
 {shown.map((row) =>
 renderContractLine({
 person: row,
 member: rowAsGroupMember(row),
 facts: row,
 memberIndex: 0,
 memberCount: 1,
 rowIds: [row.id],
 liveClientCount: 0,
 }),
 )}
 {open && !groupShowAll[key] && group.rows.length > shown.length && (
 <TableRow className="h-auto hover:bg-transparent max-xl:block">
 {fullWidthCells(
 <button
 type="button"
 onClick={() => setGroupShowAll((current) => ({ ...current, [key]: true }))}
 className="pl-6 text-[12.5px] font-medium text-primary hover:underline"
 >
 Pokaż wszystkie: {group.rows.length} umów u klienta {group.name} →
 </button>,
 "px-2 py-1.5 max-xl:block",
 )}
 </TableRow>
 )}
 </TableBody>
 );
 })
 ) : (
 items.map((c) => {
 const groupedMembers = c.group_members ?? [];
 const members = groupedMembers.length ? groupedMembers : [rowAsGroupMember(c)];
 const rowIds = members.map((m) => m.id);
 const liveClientCount = new Set(
 groupedMembers
 .filter((m) => m.status === "active" || m.status === "ending")
 .map((m) => m.client_id),
 ).size;
 return (
 <TableBody
 key={c.id}
 data-contract-group={c.id}
 className="max-xl:mb-3 max-xl:block max-xl:overflow-hidden max-xl:rounded-lg max-xl:border max-xl:border-border max-xl:bg-card"
 >
 {members.map((m, memberIndex) =>
 renderContractLine({
 person: c,
 member: m,
 // Wiersz główny niesie fakty zakończenia zawsze; członek grupy —
 // od 20.11.2026 (starszy serwer: tylko daty i stawki).
 facts: m.id === c.id ? { ...m, ...primaryFacts(c) } : m,
 memberIndex,
 memberCount: members.length,
 rowIds,
 liveClientCount,
 }),
 )}
 </TableBody>
 );
 })
 )}
 </Table>
 </div>
 )}

 {/* Pagination */}
 {!allRowsMode && viewState === "ready" && total > pageSize && (
 <div className="flex items-center justify-between text-sm">
 <span className="text-muted-foreground">
 Strona <strong className="text-foreground">{page}</strong> z {totalPages}
 </span>
 <div className="flex gap-2">
 <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
 Poprzednia
 </Button>
 <Button
 size="sm"
 variant="outline"
 disabled={page >= totalPages}
 onClick={() => setPage((p) => p + 1)}
 >
 Następna
 </Button>
 </div>
 </div>
 )}
 {groupView && viewState === "ready" && (
 <p className="text-[12.5px] text-muted-foreground">
 {allRowsQuery.data?.truncated
 ? `Widać pierwsze ${allRows.length} z ${allRowsQuery.data.total} umów — zawęź listę wyszukiwarką albo filtrami.`
 : `${allRows.length} umów u ${clientGroups.length} klientów.`}
 </p>
 )}
 </div>
 );

 const openPreview = openContractId != null ? previews.get(openContractId) : undefined;

 return (
 <div ref={listRef}>
 <ListDetailLayout
 list={listContent}
 onClose={closePanel}
 panelLabel="Szczegóły kontraktu"
 panel={
 openContractId != null ? (
 <ContractSidePanel
 key={openContractId}
 contractId={openContractId}
 onClose={closePanel}
 preview={openPreview}
 returnTarget={returnTarget}
 source="contracts"
 onSelectContract={openContract}
 />
 ) : null
 }
 />
 {toast && (
 <div className="fixed bottom-24 right-4 z-9999 px-4 py-3 rounded-lg shadow-md text-sm bg-card text-foreground">
 {toast}
 </div>
 )}
 </div>
 );
}
