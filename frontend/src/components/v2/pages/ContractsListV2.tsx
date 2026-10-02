"use client";

import { useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from"react";
import Link from"next/link";
import dynamic from"next/dynamic";
import { keepPreviousData, useQuery, useQueryClient } from"@tanstack/react-query";
import {
 AlertTriangle,
 ArrowDown,
 ArrowUp,
 CalendarRange,
 ChevronsUpDown,
 Download,
 FileText,
 Plus,
 Search,
 TrendingUp,
 X,
} from"lucide-react";
import api from"@/lib/api";
import { cn, formatCurrency, formatDate } from"@/lib/utils";
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
import {
 WIDE_HIDDEN,
 WIDE_ONLY_CELL,
 WIDE_ONLY_COL,
 WIDE_TABLE_CONTAINER,
} from"@/lib/wide-table";
import { useCapability } from"@/hooks/useCapability";
import { Badge } from"@/components/ui/badge";
import { Button } from"@/components/ui/button";
import { Checkbox } from"@/components/ui/checkbox";
import { Input } from"@/components/ui/input";
import {
 Popover,
 PopoverContent,
 PopoverTrigger,
} from"@/components/ui/popover";
import { ContractsBulkActionsBarV2 } from"@/components/v2/modals/ContractsBulkActionsBar";
import {
 Table,
 TableBody,
 TableCell,
 TableHead,
 TableHeader,
 TableRow,
} from"@/components/ui/table";
import { MultiSelectFilter } from"@/components/v2/filters/MultiSelectFilter";
import {
 CONTRACT_STATUS_OPTIONS,
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
import { hasAnyPermission, hasPermission } from "@/lib/permissions";
import { getAuthenticatedRequestHeaders } from "@/lib/session";
import { hasAnalyticsCapability, useAuthStore } from "@/store/auth";

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
}

interface ContractRow {
 id: number;
 candidate_id?: number | null;
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
 // `group_by_candidate=true`: wszystkie umowy tej osoby (żywe najpierw).
 // Wiersz z >1 członkiem renderuje kolumny okresu/stawek/marży per klient.
 group_members?: ContractGroupMemberRow[];
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
 if (margin == null) return"text-muted-foreground";
 if (rateClient == null || rateClient === 0) return"text-foreground";
 const pct = (margin / rateClient) * 100;
 if (pct < 15) return"text-destructive font-bold";
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

// Polish plural for "kontrakt" + matching verb (1 / 2–4 / 0,5+ forms), so the
// banner reads correctly whether 1 or 45 contracts are expiring.
/** Statusy, w których umowa DZIŚ obowiązuje — „kończąca się" też. */
const RUNNING_CONTRACT_STATUSES: ReadonlySet<ContractStatusValue> = new Set(
 DEFAULT_CONTRACT_STATUS_FILTER,
);

function expiringBannerText(n: number): string {
 const m10 = n % 10;
 const m100 = n % 100;
 const few = m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14);
 const noun = n === 1 ?"kontrakt" : few ?"kontrakty" :"kontraktów";
 const verb = few ?"kończą się" :"kończy się";
 return `${n} ${noun} ${verb} w ciągu 30 dni`;
}

/**
 * „startuje DD.MM" przy umowie „Aktywnej"/„Kończącej się", której start jest
 * jeszcze przed nami. Status tego nie mówi, a rejestr liczył takie umowy jak
 * pracujące (audyt 24.09.2026, U5). Status w bazie bez zmian.
 */
export function futureStartLabel(
 status: string | null | undefined,
 startDate: string | null | undefined,
 todayIso: string,
): string | null {
 if (status !== "active" && status !== "ending") return null;
 const start = startDate?.slice(0, 10);
 if (!start || start <= todayIso) return null;
 return `startuje ${start.slice(8, 10)}.${start.slice(5, 7)}`;
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

/**
 * Globalny `formatDate` zachowuje czterocyfrowy rok. Rejestr kontraktów ma
 * osobny, celowo zwarty format, żeby pełny zestaw kolumn mieścił się na
 * standardowym ekranie roboczym. Pełna data pozostaje w `title`/`aria-label`.
 */
export function formatContractListDate(
 date: string | Date | null | undefined,
): string {
 if (!date) return"—";
 return new Intl.DateTimeFormat("pl-PL", {
 day: "2-digit",
 month: "2-digit",
 year: "2-digit",
 }).format(new Date(date));
}

// Jednostka obok kwoty: kontrakt zmienia ją razem z zamówieniem (120 zł/h →
// 960 zł/MD), więc sama kwota nie mówi, ile kosztuje godzina pracy.
function RateUnitSuffix({ unit }: { unit?: string | null }) {
 const suffix = contractRateUnitSuffix(unit);
 if (!suffix) return null;
 return (
 <span className="ml-0.5 font-sans text-[10px] font-normal text-muted-foreground">
 {suffix}
 </span>
 );
}

function CompactDate({ value }: { value: string }) {
 const fullDate = formatDate(value);
 return (
 <time dateTime={value} title={fullDate} aria-label={fullDate}>
 {formatContractListDate(value)}
 </time>
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
 id: row.id,
 client_id: 0,
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

export interface ContractsDateRange {
 startFrom: string;
 startTo: string;
 orderEndFrom: string;
 orderEndTo: string;
}

export interface ContractsSort {
 by: ContractSortKey | null;
 dir: ContractSortDir;
}

const EMPTY_DATE_RANGE: ContractsDateRange = {
 startFrom: "",
 startTo: "",
 orderEndFrom: "",
 orderEndTo: "",
};

function rangeInverted(from: string, to: string): boolean {
 return Boolean(from && to && from > to);
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
 const f = from ? formatContractListDate(from) : "…";
 const t = to ? formatContractListDate(to) : "…";
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
 children,
}: {
 label: string;
 sortKey: ContractSortKey;
 sort: ContractsSort;
 onSort: (key: ContractSortKey) => void;
 align?: "left" | "right";
 children?: ReactNode;
}) {
 const active = sort.by === sortKey;
 const Icon = !active ? ChevronsUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
 return (
 <TableHead
 className={cn("px-2", align === "right" && "text-right")}
 aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
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
 {label}
 <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />
 </button>
 </span>
 </TableHead>
 );
}

function DateRangeFields({
 legend,
 from,
 to,
 onChange,
}: {
 legend: string;
 from: string;
 to: string;
 onChange: (from: string, to: string) => void;
}) {
 const inverted = rangeInverted(from, to);
 return (
 <fieldset className="space-y-1.5">
 <legend className="text-xs font-semibold text-foreground">{legend}</legend>
 <div className="grid grid-cols-2 gap-2">
 <label className="space-y-1 text-[11px] text-muted-foreground">
 <span>Od</span>
 <Input
 type="date"
 value={from}
 aria-label={`${legend} od`}
 onChange={(e) => onChange(e.target.value, to)}
 />
 </label>
 <label className="space-y-1 text-[11px] text-muted-foreground">
 <span>Do</span>
 <Input
 type="date"
 value={to}
 aria-label={`${legend} do`}
 onChange={(e) => onChange(from, e.target.value)}
 />
 </label>
 </div>
 {inverted && (
 <p role="alert" className="text-[11px] text-destructive">
 Data „od" jest późniejsza niż „do" — popraw zakres, żeby go zastosować.
 </p>
 )}
 </fieldset>
 );
}

function MobileFieldLabel({ children }: { children: string }) {
 return (
 <span className="mb-1 hidden text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground max-xl:block">
 {children}
 </span>
 );
}

interface ContractsListV2Props {
 /** Reactive search string from the App Router; omitted in isolated embeds/tests. */
 navigationSearch?: string;
 /** Przełącznik trybów modułu — pod tytułem, jak w makiecie B. */
 modeTabs?: ReactNode;
 /** Pierwsza kontrolka paska filtrów (wybór klienta). */
 toolbarLead?: ReactNode;
}

export function ContractsListV2({
 navigationSearch,
 modeTabs,
 toolbarLead,
}: ContractsListV2Props = {}) {
 const user = useAuthStore((state) => state.user);
 const impersonating = useAuthStore((state) => state.realUser !== null);
 // Analityka i raport „Kontrakty bez zamówienia" = uprawnienie „Moduł
 // Finanse" (strona i trasa raportu pytają o to samo).
 const canSeeContractAnalytics = hasPermission(user, "finance_module");
 // Eksport = trasa `FinanceReadUser`, czyli capability `view_finance`, którą
 // backend wyprowadza z „Modułu Finanse".
 const canExport =
 canSeeContractAnalytics || hasAnalyticsCapability(user, "view_finance");
 // Kolumny stawek widzi też posiadacz „Stawki i kwoty: podgląd" — kwoty
 // klientów spoza jego zakresu serwer i tak redaguje wiersz po wierszu.
 const canSeeFinance = canExport || hasPermission(user, "amounts_view");
 // Zaznaczanie i pasek akcji zbiorczych: przedłużenie („Kontrakty
 // i zamówienia: tworzenie i edycja") albo „Oznacz zakończone" („Zakończenie
 // współpracy…"). Sam odczyt Delivery nie dostaje martwych pól wyboru.
 const canBulkAct =
 !impersonating &&
 hasAnyPermission(user, "contracts_orders_edit", "contract_status");
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
 // Date-based "ending within 30 days" quick filter, driven by the banner's
 // "Pokaż" button. Decoupled from the stored `ending` status (cron-maintained)
 // so it always matches the date-based /api/contracts/expiring banner.
 const [endingSoon, setEndingSoon] = useState(initialListState.state.endingSoon);
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
 // Kontrakt otwarty w bocznym panelu (`?contract=`). Wybór NIE zeruje strony
 // ani filtrów — to podgląd, nie zawężenie listy.
 const [openContractId, setOpenContractId] = useState<number | null>(
 initialListState.state.selected ?? null,
 );
 const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
 const listRef = useRef<HTMLDivElement>(null);
 const [toast, setToast] = useState<string | null>(null);
 const [exporting, setExporting] = useState(false);
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
 ...dateRange,
 sortBy: sort.by,
 sortDir: sort.dir,
 page,
 selected: openContractId ?? undefined,
 }),
 [search, statusFilter, typeFilter, endingSoon, dateRange, sort, page, openContractId],
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
 setDateRange({
 startFrom: next.startFrom,
 startTo: next.startTo,
 orderEndFrom: next.orderEndFrom,
 orderEndTo: next.orderEndTo,
 });
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
 }, [search, statusFilter, typeFilter, endingSoon, appliedDates, sort, page]);

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
 if (endingSoon) params.set("expiring_in_days", "30");
 if (appliedDates.startFrom) params.set("start_from", appliedDates.startFrom);
 if (appliedDates.startTo) params.set("start_to", appliedDates.startTo);
 if (appliedDates.orderEndFrom) {
 params.set("order_end_from", appliedDates.orderEndFrom);
 }
 if (appliedDates.orderEndTo) params.set("order_end_to", appliedDates.orderEndTo);
 params.set("format", format);
 const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
 const res = await fetch(`${apiBase}/api/contracts/export?${params}`, {
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

 // Bramka „Nowy kontrakt" = POST /api/contracts. Z rejestru capability, NIE
 // z lokalnej reguły — to właśnie ten wzorzec rozjeżdżał się z backendem
 // (audyt F-19).
 const canCreateContract = useCapability("contract.create");

 const { data, isLoading, isError, error, refetch, isPlaceholderData } = useQuery({
 queryKey: [
 "contracts-v2",
 debouncedSearch,
 statusFilter,
 typeFilter,
 endingSoon,
 appliedDates,
 sort,
 page,
 ],
 queryFn: () =>
 api
 .get("/api/contracts", {
 params: {
 q: debouncedSearch || undefined,
 status: statusFilter.length ? statusFilter : undefined,
 contract_type: typeFilter.length ? typeFilter : undefined,
 expiring_in_days: endingSoon ? 30 : undefined,
 start_from: appliedDates.startFrom || undefined,
 start_to: appliedDates.startTo || undefined,
 order_end_from: appliedDates.orderEndFrom || undefined,
 order_end_to: appliedDates.orderEndTo || undefined,
 // Sortuje SERWER — lista jest stronicowana i grupowana po osobie.
 sort_by: sort.by ?? undefined,
 sort_dir: sort.by ? sort.dir : undefined,
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

 const { data: expiring } = useQuery({
 queryKey: ["contracts-expiring-v2"],
 queryFn: () => api.get("/api/contracts/expiring").then((r) => r.data),
 staleTime: 5 * 60 * 1000,
 });

 const items = useMemo<ContractRow[]>(() => data?.items ?? [], [data]);
 const total = data?.total ?? 0;
 const contractorsTotal = data?.contractors_total ?? total;
 const contractsTotal = data?.contracts_total ?? total;
 const futureStartTotal: number = data?.future_start_total ?? 0;
 const todayIso = localTodayIso();
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
 const viewState = resolveViewState({
 isLoading,
 isError,
 error,
 isEmpty: items.length === 0,
 });
 const failed =
 viewState === "forbidden" ||
 viewState === "not_found" ||
 viewState === "error";

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

 // "All selected" is derived by comparing the SET of selected ids against the
 // set of currently-visible ids — never by count equality (which is fragile
 // against stale ids from a previous page/filter). Computed inline (page size
 // is small, and it's only read in render + handlers, never a dep array).
 // Wiersz zgrupowany wnosi WSZYSTKIE swoje umowy (patrz `toggleIds`).
 const visibleIds = items.flatMap((i) =>
 i.group_members?.length ? i.group_members.map((m) => m.id) : [i.id],
 );
 const allVisibleSelected =
 visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
 const someVisibleSelected = visibleIds.some((id) => selectedIds.has(id));

 const expiringCount = useMemo(
 () => (Array.isArray(expiring) ? expiring.length : expiring?.total ?? 0),
 [expiring]
 );

 // Kolejność wierszy na ekranie = kolejność ↑/↓. Wiersz osoby otwiera umowę
 // główną (`c.id`), pas klienta — umowę tego klienta.
 const rowKeys = useMemo(
 () =>
 items.flatMap((i) =>
 i.group_members?.length
 ? i.group_members.map((m) => String(m.id))
 : [String(i.id)],
 ),
 [items],
 );
 const previews = useMemo(() => {
 const map = new Map<
 number,
 { candidate_name?: string | null; client_name?: string | null; job_title?: string | null; status?: string | null }
 >();
 for (const i of items) {
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
 }, [items]);
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
 appliedDates,
 ]);
 const previousFilters = useRef(filtersSignature);
 useEffect(() => {
 if (previousFilters.current === filtersSignature) return;
 previousFilters.current = filtersSignature;
 recheckOpenRow.current = true;
 }, [filtersSignature]);
 useEffect(() => {
 if (!recheckOpenRow.current || isLoading || isPlaceholderData) return;
 recheckOpenRow.current = false;
 if (openContractId == null) return;
 if (!rowKeys.includes(String(openContractId))) setOpenContractId(null);
 }, [rowKeys, isLoading, isPlaceholderData, openContractId, filtersSignature]);

 const listContent = (
 <div className="space-y-3">
 {/* Nagłówek zwarty: tytuł i licznik w jednej linii — laptop 1280×720
 ma zobaczyć tabelę w górnych 60% okna. */}
 <div className="flex flex-wrap items-center justify-between gap-2">
 <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5">
 <h1 className="text-lg font-semibold text-foreground">Kontrakty</h1>
 <p className="text-xs text-muted-foreground">
 {isLoading
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
 {canExport && <Popover>
 <PopoverTrigger asChild>
 <Button size="sm" variant="outline" disabled={exporting}>
 <Download className="h-4 w-4" /> {exporting ? "Eksportuję…" : "Eksport"}
 </Button>
 </PopoverTrigger>
 <PopoverContent align="end" className="w-auto min-w-44 p-1">
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
 {canSeeContractAnalytics && (
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
 {canCreateContract && (
 <Link href="/contracts/new">
 <Button size="sm" variant="primary">
 <Plus className="h-4 w-4" /> Nowy kontrakt
 </Button>
 </Link>
 )}
 </div>
 </div>

 {modeTabs}

 {/* Filtry — wszystkie kontrolki mają 32 px wysokości (h-8). */}
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
 <MultiSelectFilter<ContractStatusValue>
 value={statusFilter}
 onChange={(v) => {
 setStatusFilter(v);
 setEndingSoon(false);
 setPage(1);
 }}
 options={CONTRACT_STATUS_OPTIONS}
 placeholder="Wszystkie statusy"
 searchPlaceholder="Szukaj statusu…"
 triggerWidthClass="w-[170px] h-8 text-xs"
 triggerLabel={(n) =>
 n === 1
 ? (CONTRACT_STATUS_OPTIONS.find((o) => o.value === statusFilter[0])
 ?.label ??"Status")
 : `Status: ${n}`
 }
 />
 <MultiSelectFilter<ContractTypeValue>
 value={typeFilter}
 onChange={(v) => {
 setTypeFilter(v);
 setPage(1);
 }}
 options={CONTRACT_TYPE_OPTIONS}
 placeholder="Typ"
 searchPlaceholder="Szukaj typu…"
 triggerWidthClass="w-[140px] h-8 text-xs"
 triggerLabel={(n) =>
 n === 1
 ? (CONTRACT_TYPE_OPTIONS.find((o) => o.value === typeFilter[0])
 ?.label ??"Typ")
 : `Typ: ${n}`
 }
 />
 <Popover>
 <PopoverTrigger asChild>
 <Button
 size="sm"
 variant="outline"
 className="gap-1.5"
 aria-label="Filtr dat"
 >
 <CalendarRange className="h-4 w-4" />
 Daty
 </Button>
 </PopoverTrigger>
 <PopoverContent align="start" className="w-80 space-y-3">
 <DateRangeFields
 legend="Data rozpoczęcia"
 from={dateRange.startFrom}
 to={dateRange.startTo}
 onChange={(from, to) => updateDateRange({ startFrom: from, startTo: to })}
 />
 <DateRangeFields
 legend="Data zakończenia zamówienia"
 from={dateRange.orderEndFrom}
 to={dateRange.orderEndTo}
 onChange={(from, to) =>
 updateDateRange({ orderEndFrom: from, orderEndTo: to })
 }
 />
 <p className="text-[11px] leading-4 text-muted-foreground">
 Zamówienia bezterminowe i kontrakty bez zamówienia nie mieszczą się
 w zakresie końca zamówienia.
 </p>
 <Button
 size="sm"
 variant="ghost"
 className="w-full"
 onClick={() => updateDateRange(EMPTY_DATE_RANGE)}
 >
 Wyczyść daty
 </Button>
 </PopoverContent>
 </Popover>
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
 {endingSoon && (
 <Button
 size="sm"
 variant="outline"
 className="gap-1"
 onClick={() => {
 setEndingSoon(false);
 setPage(1);
 }}
 >
 Kończące się w ciągu 30 dni
 <X className="h-3.5 w-3.5" />
 </Button>
 )}
 {/* Baner „kończą się w ciągu 30 dni" — w linii paska filtrów, nie jako
 osobna karta nad tabelą. „Pokaż" działa jak dotąd. */}
 {expiringCount > 0 && (
 <div
 role="status"
 className="ml-auto flex h-8 items-center gap-2 rounded-md border border-warning/25 bg-warning-muted px-2 text-xs text-warning-muted-foreground"
 title="Sprawdź, czy wymagają przedłużenia albo wypowiedzenia."
 >
 <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
 <span className="font-semibold">{expiringBannerText(expiringCount)}</span>
 <Button
 size="sm"
 variant="outline"
 className="h-6 px-2"
 onClick={() => {
 // Surface exactly the contracts the banner counts. The banner reads
 // the date-based /api/contracts/expiring (end_date within 30 days),
 // so filter the list the same way via `expiring_in_days` — not the
 // stored `ending` status, which is a cron-maintained set disjoint
 // from the banner's and would show the wrong rows (or none).
 setEndingSoon(true);
 setStatusFilter([]);
 setSearch("");
 setPage(1);
 }}
 >
 Pokaż
 </Button>
 </div>
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
 visibleCount={items.length}
 onDone={(msg) => {
 setToast(msg);
 setTimeout(() => setToast(null), 3500);
 queryClient.invalidateQueries({ queryKey: ["contracts-v2"] });
 queryClient.invalidateQueries({ queryKey: ["contracts-expiring-v2"] });
 setSelectedIds(new Set());
 }}
 />
 )}

 {/* Compact client-band table. One semantic row per contract keeps every
 client/date/rate/status tuple aligned; the candidate cell spans the group. */}
 {/* Szeroka tabela (≥ 1700 px): rekrutacja, koniec umowy i start
 zamówienia mają własne kolumny zamiast drobnego druku pod klientem
 i datami. Szerokości obu układów sumują się do 100%. */}
 <div className={WIDE_TABLE_CONTAINER}>
 <Table
 density="compact"
 className="table-fixed text-xs max-xl:block"
 data-contracts-responsive-table
 >
 <colgroup className="max-xl:hidden">
 {canSeeFinance ? (
 <>
 <col className="w-[15%] @min-[1700px]:w-[13%]" />
 <col className="w-[14%] @min-[1700px]:w-[11%]" />
 <col className={cn(WIDE_ONLY_COL, "w-[13%]")} />
 <col className="w-[9.5%] @min-[1700px]:w-[7%]" />
 <col className={cn(WIDE_ONLY_COL, "w-[7%]")} />
 <col className={cn(WIDE_ONLY_COL, "w-[7%]")} />
 <col className="w-[11%] @min-[1700px]:w-[8%]" />
 <col className="w-[12%] @min-[1700px]:w-[8%]" />
 <col className="w-[12.5%] @min-[1700px]:w-[8.5%]" />
 <col className="w-[9%] @min-[1700px]:w-[7%]" />
 <col className="w-[7%] @min-[1700px]:w-[5%]" />
 <col className="w-[10%] @min-[1700px]:w-[5.5%]" />
 </>
 ) : (
 <>
 <col className="w-[24%] @min-[1700px]:w-[16%]" />
 <col className="w-[24%] @min-[1700px]:w-[14%]" />
 <col className={cn(WIDE_ONLY_COL, "w-[18%]")} />
 <col className="w-[14%] @min-[1700px]:w-[9%]" />
 <col className={cn(WIDE_ONLY_COL, "w-[9%]")} />
 <col className={cn(WIDE_ONLY_COL, "w-[9%]")} />
 <col className="w-[14%] @min-[1700px]:w-[9%]" />
 <col className="w-[10%] @min-[1700px]:w-[7%]" />
 <col className="w-[14%] @min-[1700px]:w-[9%]" />
 </>
 )}
 </colgroup>
 <TableHeader className="max-xl:hidden">
 <TableRow>
 <SortableHead label="Kandydat" sortKey="candidate" sort={sort} onSort={onSort}>
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
 <SortableHead label="Klient" sortKey="client" sort={sort} onSort={onSort} />
 <TableHead className={cn(WIDE_ONLY_CELL, "px-2")}>Rekrutacja</TableHead>
 <SortableHead
 label="Data rozpoczęcia"
 sortKey="start_date"
 sort={sort}
 onSort={onSort}
 />
 <TableHead className={cn(WIDE_ONLY_CELL, "px-2")}>Koniec umowy</TableHead>
 <TableHead className={cn(WIDE_ONLY_CELL, "px-2")}>Start zamówienia</TableHead>
 <SortableHead
 label="Data zakończenia zamówienia"
 sortKey="order_end_date"
 sort={sort}
 onSort={onSort}
 />
 {canSeeFinance && (
 <>
 <SortableHead
 label="Stawka kosztowa"
 sortKey="rate_candidate"
 sort={sort}
 onSort={onSort}
 align="right"
 />
 <SortableHead
 label="Stawka przychodowa"
 sortKey="rate_client"
 sort={sort}
 onSort={onSort}
 align="right"
 />
 <SortableHead
 label="Marża"
 sortKey="margin"
 sort={sort}
 onSort={onSort}
 align="right"
 />
 </>
 )}
 <SortableHead label="Typ" sortKey="contract_type" sort={sort} onSort={onSort} />
 <SortableHead label="Status" sortKey="status" sort={sort} onSort={onSort} />
 </TableRow>
 </TableHeader>
 {viewState === "loading" ? (
 <TableBody className="max-xl:block max-xl:w-full">
 <TableRow className="max-xl:block max-xl:h-auto max-xl:w-full">
 <TableCell colSpan={canSeeFinance ? 12 : 9} className="text-center py-10 text-muted-foreground max-xl:block max-xl:w-full">
 Ładowanie…
 </TableCell>
 </TableRow>
 </TableBody>
 ) : failed ? (
 <TableBody className="max-xl:block max-xl:w-full">
 <TableRow className="max-xl:block max-xl:h-auto max-xl:w-full">
 <TableCell colSpan={canSeeFinance ? 12 : 9} className="p-0 max-xl:block max-xl:w-full">
 <QueryStateNotice
 state={viewState as "forbidden" | "not_found" | "error"}
 className="border-0"
 description={
 viewState === "forbidden"
 ?"Nie masz uprawnienia do rejestru kontraktów. Rejestr NIE jest pusty — poproś administratora o dostęp (Ustawienia → Zespół i dostęp → Osoby i role)."
 : undefined
 }
 onRetry={() => void refetch()}
 />
 </TableCell>
 </TableRow>
 </TableBody>
 ) : viewState === "empty" ? (
 <TableBody className="max-xl:block max-xl:w-full">
 <TableRow className="max-xl:block max-xl:h-auto max-xl:w-full">
 <TableCell colSpan={canSeeFinance ? 12 : 9} className="text-center py-10 max-xl:block max-xl:w-full">
 <FileText className="h-10 w-10 mx-auto text-muted-foreground mb-2 opacity-40" />
 <p className="text-sm text-muted-foreground">
 Brak kontraktów spełniających kryteria.
 </p>
 </TableCell>
 </TableRow>
 </TableBody>
 ) : (
 items.map((c) => {
 const groupedMembers = c.group_members ?? [];
 const members = groupedMembers.length ? groupedMembers : [rowAsGroupMember(c)];
 const multi = members.length > 1;
 const rowIds = members.map((m) => m.id);
 const rowSelected = rowIds.every((id) => selectedIds.has(id));
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
 {members.map((m, memberIndex) => {
 const comparableMargin = hasComparableRateCurrencies(m)
 ? m.margin
 : null;
 const marginPct = marginPercent(comparableMargin, m.rate_client);
 const statusBadge = m.status
 ? CONTRACT_STATUS_BADGE[m.status]
 : undefined;
 const futureStart = futureStartLabel(
 m.status,
 m.start_date,
 todayIso,
 );

 const panelOpen = openContractId === m.id;
 return (
 <TableRow
 key={m.id}
 data-contract-member={m.id}
 interactive
 selected={rowSelected}
 {...rowActivationProps(String(m.id), () => openContract(m.id))}
 aria-selected={panelOpen}
 data-selected={panelOpen || undefined}
 className={cn(
 "h-auto min-h-10 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
 rowSelected
 ?"bg-primary/10!"
 : panelOpen
 ?"bg-primary/5! shadow-[inset_3px_0_0_0_hsl(var(--primary))]"
 : memberIndex % 2 === 0
 ?"bg-info-muted/35"
 :"bg-primary/[0.04]",
 memberIndex === members.length - 1 &&
 "xl:border-border! xl:border-b-2!",
 "max-xl:grid max-xl:h-auto max-xl:grid-cols-2 max-xl:bg-card",
 )}
 >
 {memberIndex === 0 && (
 <TableCell
 rowSpan={members.length}
 data-label="Kandydat"
 className={cn(
 "align-top px-2 py-2 max-xl:col-span-2 max-xl:block max-xl:border-b max-xl:border-border max-xl:bg-muted/40",
 openContractId === c.id ?"bg-primary/5" :"bg-card",
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
 <Link
 href={buildContractDetailHref(c.id, returnTarget)}
 onClick={() => rememberContractsListScroll(returnTarget)}
 className="block truncate text-[13px] font-semibold leading-4 text-foreground hover:text-primary"
 title={c.candidate_name ?? undefined}
 >
 {c.candidate_name ?? `#${c.id}`}
 </Link>
 {liveClientCount > 1 && (
 <div className="mt-0.5 text-[10px] leading-4 text-muted-foreground">
 pracuje u {liveClientCount} klientów
 </div>
 )}
 </div>
 </div>
 </TableCell>
 )}

 <TableCell
 data-label="Klient"
 className={cn(
 "border-l-2 px-2 py-1.5 align-top",
 memberIndex % 2 === 0
 ?"border-l-info/60"
 :"border-l-primary/70",
 "max-xl:block max-xl:min-w-0 max-xl:border-b max-xl:border-b-border/60",
 )}
 >
 <MobileFieldLabel>Klient</MobileFieldLabel>
 <Link
 href={buildContractDetailHref(m.id, returnTarget)}
 onClick={() => rememberContractsListScroll(returnTarget)}
 className="block min-w-0 hover:text-primary"
 >
 <TruncatedText className="max-w-full text-[12px] font-semibold leading-4">
 {m.client_name}
 </TruncatedText>
 </Link>
 {m.job_title && (
 <TruncatedText className={cn("max-w-full text-[10px] leading-4 text-muted-foreground", WIDE_HIDDEN)}>
 {m.job_title}
 </TruncatedText>
 )}
 </TableCell>

 <TableCell
 data-testid="contract-job-cell"
 className={cn(WIDE_ONLY_CELL, "px-2 py-1.5 align-top")}
 >
 {m.job_title ? (
 <TruncatedText className="max-w-full text-[12px] leading-4">
 {m.job_title}
 </TruncatedText>
 ) : (
 <span className="text-[12px] text-muted-foreground">—</span>
 )}
 </TableCell>

 <TableCell
 data-label="Data rozpoczęcia"
 className="px-2 py-1.5 align-top max-xl:block max-xl:border-b max-xl:border-b-border/60"
 >
 <MobileFieldLabel>Data rozpoczęcia</MobileFieldLabel>
 <div className="whitespace-nowrap text-[12px] font-medium leading-4 text-foreground">
 {m.start_date ? <CompactDate value={m.start_date} /> : "—"}
 </div>
 {m.end_date && (
 <div
 className={cn("whitespace-nowrap text-[10px] leading-4 text-muted-foreground", WIDE_HIDDEN)}
 title="Data zakończenia umowy"
 >
 umowa do <CompactDate value={m.end_date} />
 </div>
 )}
 </TableCell>

 <TableCell
 data-testid="contract-end-cell"
 title="Data zakończenia umowy"
 className={cn(WIDE_ONLY_CELL, "px-2 py-1.5 align-top whitespace-nowrap text-[12px] leading-4")}
 >
 {m.end_date ? (
 <CompactDate value={m.end_date} />
 ) : (
 <span className="text-muted-foreground">—</span>
 )}
 </TableCell>
 <TableCell
 data-testid="contract-order-start-cell"
 title="Początek okresu zamówienia — z najnowszego uzupełnionego zamówienia tej osoby."
 className={cn(WIDE_ONLY_CELL, "px-2 py-1.5 align-top whitespace-nowrap text-[12px] leading-4")}
 >
 {m.client_order_start_date ? (
 <CompactDate value={m.client_order_start_date} />
 ) : (
 <span className="text-muted-foreground">—</span>
 )}
 </TableCell>

 <TableCell
 data-label="Data zakończenia zamówienia"
 className="px-2 py-1.5 align-top max-xl:block max-xl:border-b max-xl:border-b-border/60"
 >
 <MobileFieldLabel>Data zakończenia zamówienia</MobileFieldLabel>
 {m.client_order_start_date ? (
 <>
 <div
 className="whitespace-nowrap text-[12px] font-medium leading-4 text-foreground"
 title="Okres zamówienia — z najnowszego uzupełnionego zamówienia tej osoby. Nie zmienia okresu umowy."
 >
 {m.client_order_end_date ? (
 <CompactDate value={m.client_order_end_date} />
 ) : (
 "bezterminowo"
 )}
 </div>
 <div className={cn("whitespace-nowrap text-[10px] leading-4 text-muted-foreground", WIDE_HIDDEN)}>
 zam. od <CompactDate value={m.client_order_start_date} />
 </div>
 </>
 ) : m.latest_order_end_date ? (
 <div
 className="whitespace-nowrap text-[12px] font-medium leading-4 text-warning-muted-foreground"
 title="Aktualne zamówienie klienta kończy się tej daty"
 >
 <CompactDate value={m.latest_order_end_date} />
 </div>
 ) : (
 <span className="text-[12px] text-muted-foreground">—</span>
 )}
 </TableCell>

 {canSeeFinance && (
 <>
 <TableCell
 data-label="Stawka kosztowa"
 className="px-2 py-1.5 text-right align-top font-mono text-[12px] leading-5 whitespace-nowrap max-xl:block max-xl:border-b max-xl:border-b-border/60 max-xl:text-left"
 >
 <MobileFieldLabel>Stawka kosztowa</MobileFieldLabel>
 {m.rate_candidate != null ? (
 <>
 {formatCurrency(m.rate_candidate, candidateCurrency(m))}
 <RateUnitSuffix unit={m.rate_unit} />
 </>
 ) : (
"—"
 )}
 </TableCell>
 <TableCell
 data-label="Stawka przychodowa"
 className="px-2 py-1.5 text-right align-top font-mono text-[12px] font-semibold leading-5 whitespace-nowrap max-xl:block max-xl:border-b max-xl:border-b-border/60 max-xl:text-left"
 >
 <MobileFieldLabel>Stawka przychodowa</MobileFieldLabel>
 {m.rate_client != null ? (
 <>
 {formatCurrency(m.rate_client, clientCurrency(m))}
 <RateUnitSuffix unit={m.rate_unit} />
 </>
 ) : (
"—"
 )}
 </TableCell>
 <TableCell
 data-label="Marża"
 className="px-2 py-1.5 text-right align-top font-mono text-[12px] leading-4 whitespace-nowrap max-xl:block max-xl:border-b max-xl:border-b-border/60 max-xl:text-left"
 >
 <MobileFieldLabel>Marża</MobileFieldLabel>
 <span
 className={marginColor(
 comparableMargin ?? undefined,
 m.rate_client ?? undefined,
 )}
 >
 {comparableMargin != null
 ? formatCurrency(comparableMargin, clientCurrency(m))
 :"—"}
 </span>
 {/* Marża = różnica stawek w jednostce kontraktu — ta sama
 końcówka co przy stawkach obok (bez niej „43 zł” czytało
 się jak kwota miesięczna). */}
 {comparableMargin != null && <RateUnitSuffix unit={m.rate_unit} />}
 {marginPct && (
 <span className="block text-[10px] font-sans text-muted-foreground">
 {marginPct}
 </span>
 )}
 </TableCell>
 </>
 )}

 <TableCell
 data-label="Typ"
 className="px-2 py-1.5 align-top max-xl:block"
 >
 <MobileFieldLabel>Typ</MobileFieldLabel>
 <Badge size="md" variant="soft" className="max-w-full px-1.5 text-[11px]">
 {m.contract_type ??"—"}
 </Badge>
 </TableCell>
 <TableCell
 data-label="Status"
 className="px-2 py-1.5 align-top max-xl:block"
 >
 <MobileFieldLabel>Status</MobileFieldLabel>
 {m.status ? (
 <Badge
 size="md"
 variant={statusBadge?.variant ??"neutral"}
 className="max-w-full px-1.5 text-[11px]"
 >
 {statusBadge?.label ?? m.status}
 </Badge>
 ) : (
 <span className="text-xs text-muted-foreground">—</span>
 )}
 {futureStart && (
 <span
 className="mt-0.5 block text-[11px] font-medium text-info-muted-foreground"
 data-testid="contract-future-start"
 >
 {futureStart}
 </span>
 )}
 </TableCell>
 </TableRow>
 );
 })}
 </TableBody>
 );
 })
 )}
 </Table>
 </div>

 {/* Pagination */}
 {viewState === "ready" && total > pageSize && (
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
