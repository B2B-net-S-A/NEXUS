"use client";

import { useEffect, useMemo, useRef, useState } from"react";
import Link from"next/link";
import { keepPreviousData, useQuery, useQueryClient } from"@tanstack/react-query";
import {
 AlertTriangle,
 Download,
 FileText,
 Plus,
 Search,
 TrendingUp,
 X,
} from"lucide-react";
import api from"@/lib/api";
import { cn, formatCurrency, formatDate } from"@/lib/utils";
import { useDebouncedValue } from"@/lib/use-debounced-value";
import { resolveViewState } from"@/lib/view-state";
import {
 CONTRACT_STATUS_LABEL,
 CONTRACT_STATUS_VARIANT,
} from"@/lib/contract-register";
import { QueryStateNotice } from"@/components/ds/QueryStateNotice";
import { TruncatedText } from"@/components/ds/TruncatedText";
import { useCapability } from"@/hooks/useCapability";
import { Badge } from"@/components/ui/badge";
import { Button } from"@/components/ui/button";
import { Card } from"@/components/ui/card";
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
 buildContractDetailHref,
 buildContractsListUrl,
 parseContractsListState,
 rememberContractsListScroll,
 restoreContractsListScroll,
 takeContractsListScroll,
} from "@/lib/contracts-list-navigation";
import { getAccessToken } from "@/lib/session";
import {
 hasAnalyticsCapability,
 hasRole,
 useAuthStore,
} from "@/store/auth";

interface ContractGroupMemberRow {
 id: number;
 client_id: number;
 client_name?: string | null;
 job_title?: string | null;
 start_date?: string | null;
 end_date?: string | null;
 latest_order_end_date?: string | null;
 contract_type?: string;
 rate_client?: number | null;
 rate_candidate?: number | null;
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
 contract_type?: string;
 rate_client?: number;
 rate_candidate?: number;
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
function expiringBannerText(n: number): string {
 const m10 = n % 10;
 const m100 = n % 100;
 const few = m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14);
 const noun = n === 1 ?"kontrakt" : few ?"kontrakty" :"kontraktów";
 const verb = few ?"kończą się" :"kończy się";
 return `${n} ${noun} ${verb} w ciągu 30 dni`;
}

function contractorsCountText(
 contractors: number,
 contracts: number,
 activeOnly: boolean,
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
 return `${contractors} ${contractorNoun} / ${contracts} ${contractNoun}`;
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
 contract_type: row.contract_type,
 rate_client: row.rate_client,
 rate_candidate: row.rate_candidate,
 margin: row.margin,
 status: row.status,
 currency: row.currency,
 rate_client_currency: row.rate_client_currency,
 rate_candidate_currency: row.rate_candidate_currency,
 };
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
}

export function ContractsListV2({ navigationSearch }: ContractsListV2Props = {}) {
 const user = useAuthStore((state) => state.user);
 const canSeeFinance =
 hasRole(user, "admin") || hasAnalyticsCapability(user, "view_finance");
 const canSeeContractAnalytics = hasRole(user, "admin", "finance");
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
 const [page, setPage] = useState(initialListState.state.page);
 const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
 const [toast, setToast] = useState<string | null>(null);
 const [exporting, setExporting] = useState(false);
 const queryClient = useQueryClient();
 const restoredScroll = useRef(false);
 const ownNavigationUrl = useRef<string | null>(null);

 const returnTarget = useMemo(
 () =>
 buildContractsListUrl(
 { search, statusFilter, typeFilter, endingSoon, page },
 ),
 [
 search,
 statusFilter,
 typeFilter,
 endingSoon,
 page,
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
 setPage(next.page);
 }, [navigationSearch]);

 // Do zapytania idzie wartość zdebouncowana, do inputa surowa — inaczej każde
 // naciśnięcie klawisza wysyłało request (a zapytanie listy robi sześć
 // `selectinload`) i przerzucało tabelę w stan ładowania.
 const debouncedSearch = useDebouncedValue(search, 300);

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
 }, [search, statusFilter, typeFilter, endingSoon, page]);

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
 params.set("format", format);
 const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
 const token = getAccessToken();
 const res = await fetch(`${apiBase}/api/contracts/export?${params}`, {
 headers: token ? { Authorization: `Bearer ${token}` } : {},
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

 // Bramka „Nowy kontrakt" = POST /api/contracts (TacPlus). Z rejestru, NIE
 // z lokalnej listy ról — to właśnie ten wzorzec rozjeżdżał się z backendem
 // (audyt F-19).
 const canCreateContract = useCapability("contract.create");

 const { data, isLoading, isError, error, refetch } = useQuery({
 queryKey: ["contracts-v2", debouncedSearch, statusFilter, typeFilter, endingSoon, page],
 queryFn: () =>
 api
 .get("/api/contracts", {
 params: {
 q: debouncedSearch || undefined,
 status: statusFilter.length ? statusFilter : undefined,
 contract_type: typeFilter.length ? typeFilter : undefined,
 expiring_in_days: endingSoon ? 30 : undefined,
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

 const items: ContractRow[] = data?.items ?? [];
 const total = data?.total ?? 0;
 const contractorsTotal = data?.contractors_total ?? total;
 const contractsTotal = data?.contracts_total ?? total;
 const pageSize = data?.page_size ?? 20;
 const totalPages = Math.max(1, Math.ceil(total / pageSize));
 const activeOnly = statusFilter.length === 1 && statusFilter[0] === "active";

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

 return (
 <div className="max-w-[1400px] mx-auto space-y-4">
 {/* Header */}
 <div className="flex items-end justify-between flex-wrap gap-3">
 <div>
 <p className="text-xs font-semibold uppercase tracking-eyebrow text-primary">
 Delivery · Kontrakty
 </p>
 <h1 className="font-semibold text-3xl font-extrabold tracking-heading-tight text-foreground mt-1">
 Kontrakty
 </h1>
 <p className="text-sm text-muted-foreground mt-1">
 {isLoading
 ?"Ładowanie…"
 : failed
 ?"Nie udało się pobrać listy"
 : contractorsCountText(contractorsTotal, contractsTotal, activeOnly)}
 </p>
 </div>
 <div className="flex items-center gap-2">
 {canSeeContractAnalytics && (
 <Link href="/contracts/analytics">
 <Button size="sm" variant="outline">
 <TrendingUp className="h-4 w-4" /> Analityka
 </Button>
 </Link>
 )}
 {canSeeFinance && <Popover>
 <PopoverTrigger asChild>
 <Button size="sm" variant="outline" disabled={exporting}>
 <Download className="h-4 w-4" /> {exporting ? "Eksportuję…" : "Eksport"}
 </Button>
 </PopoverTrigger>
 <PopoverContent align="end" className="w-44 p-1">
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

 {/* Expiring alert */}
 {expiringCount > 0 && (
 <Card className="flex items-center gap-3 border-warning/25 bg-warning-muted p-4!">
 <AlertTriangle className="h-5 w-5 shrink-0 text-warning-muted-foreground" />
 <div className="flex-1">
 <p className="text-sm font-semibold text-warning-muted-foreground">
 {expiringBannerText(expiringCount)}
 </p>
 <p className="text-xs text-warning-muted-foreground">
 Sprawdź, czy wymagają przedłużenia albo wypowiedzenia.
 </p>
 </div>
 <Button
 size="sm"
 variant="outline"
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
 </Card>
 )}

 {/* Filters */}
 <div className="flex gap-2 flex-wrap">
 <div className="flex-1 min-w-[240px] max-w-lg">
 <Input
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
 triggerWidthClass="w-[180px]"
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
 triggerWidthClass="w-[180px]"
 triggerLabel={(n) =>
 n === 1
 ? (CONTRACT_TYPE_OPTIONS.find((o) => o.value === typeFilter[0])
 ?.label ??"Typ")
 : `Typ: ${n}`
 }
 />
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
 </div>

 {/* Bulk actions bar */}
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

 {/* Compact client-band table. One semantic row per contract keeps every
 client/date/rate/status tuple aligned; the candidate cell spans the group. */}
 <Table
 density="compact"
 className="table-fixed text-xs max-xl:block"
 data-contracts-responsive-table
 >
 <colgroup className="max-xl:hidden">
 {canSeeFinance ? (
 <>
 <col className="w-[18%]" />
 <col className="w-[15%]" />
 <col className="w-[13%]" />
 <col className="w-[13.5%]" />
 <col className="w-[14%]" />
 <col className="w-[10%]" />
 <col className="w-[7.5%]" />
 <col className="w-[9%]" />
 </>
 ) : (
 <>
 <col className="w-[26%]" />
 <col className="w-[26%]" />
 <col className="w-[22%]" />
 <col className="w-[10%]" />
 <col className="w-[16%]" />
 </>
 )}
 </colgroup>
 <TableHeader className="max-xl:hidden">
 <TableRow>
 <TableHead className="px-2">
 <span className="flex items-center gap-2">
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
 Kandydat
 </span>
 </TableHead>
 <TableHead className="px-2">Klient</TableHead>
 <TableHead className="px-2">Daty</TableHead>
 {canSeeFinance && (
 <>
 <TableHead className="px-2 text-right">Stawka kosztowa</TableHead>
 <TableHead className="px-2 text-right">Stawka przychodowa</TableHead>
 <TableHead className="px-2 text-right">Marża</TableHead>
 </>
 )}
 <TableHead className="px-2">Typ</TableHead>
 <TableHead className="px-2">Status</TableHead>
 </TableRow>
 </TableHeader>
 {viewState === "loading" ? (
 <TableBody className="max-xl:block max-xl:w-full">
 <TableRow className="max-xl:block max-xl:h-auto max-xl:w-full">
 <TableCell colSpan={canSeeFinance ? 8 : 5} className="text-center py-10 text-muted-foreground max-xl:block max-xl:w-full">
 Ładowanie…
 </TableCell>
 </TableRow>
 </TableBody>
 ) : failed ? (
 <TableBody className="max-xl:block max-xl:w-full">
 <TableRow className="max-xl:block max-xl:h-auto max-xl:w-full">
 <TableCell colSpan={canSeeFinance ? 8 : 5} className="p-0 max-xl:block max-xl:w-full">
 <QueryStateNotice
 state={viewState as "forbidden" | "not_found" | "error"}
 className="border-0"
 description={
 viewState === "forbidden"
 ?"Twoja rola nie ma dostępu do rejestru kontraktów (stawki i marże). Rejestr NIE jest pusty."
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
 <TableCell colSpan={canSeeFinance ? 8 : 5} className="text-center py-10 max-xl:block max-xl:w-full">
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

 return (
 <TableRow
 key={m.id}
 data-contract-member={m.id}
 interactive
 selected={rowSelected}
 className={cn(
 "h-auto min-h-10",
 rowSelected
 ?"bg-primary/10!"
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
 className="align-top bg-card px-2 py-2 max-xl:col-span-2 max-xl:block max-xl:border-b max-xl:border-border max-xl:bg-muted/40"
 onClick={(e) => e.stopPropagation()}
 >
 <div className="flex min-w-0 items-start gap-2">
 <Checkbox
 checked={rowSelected}
 onCheckedChange={() => toggleIds(rowIds)}
 aria-label={
 multi
 ? `Zaznacz wszystkie kontrakty: ${c.candidate_name ?? c.id}`
 : `Zaznacz kontrakt ${c.id}`
 }
 />
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
 <TruncatedText className="max-w-full text-[10px] leading-4 text-muted-foreground">
 {m.job_title}
 </TruncatedText>
 )}
 </TableCell>

 <TableCell
 data-label="Daty"
 className="px-2 py-1.5 align-top max-xl:block max-xl:border-b max-xl:border-b-border/60"
 >
 <MobileFieldLabel>Daty</MobileFieldLabel>
 <div className="text-[12px] font-medium leading-4 text-foreground">
 <span className="block whitespace-nowrap">
 {m.start_date ? <CompactDate value={m.start_date} /> : "—"}
 </span>
 <span className="block whitespace-nowrap text-muted-foreground">
 <span className="mr-1" aria-hidden="true">→</span>
 {m.end_date ? <CompactDate value={m.end_date} /> : "bezterminowo"}
 </span>
 </div>
 {m.latest_order_end_date &&
 m.latest_order_end_date !== m.end_date && (
 <div
 className="whitespace-nowrap text-[10px] leading-4 text-warning-muted-foreground"
 title="Aktualne zamówienie klienta kończy się tej daty"
 >
 zam. do <CompactDate value={m.latest_order_end_date} />
 </div>
 )}
 </TableCell>

 {canSeeFinance && (
 <>
 <TableCell
 data-label="Stawka kosztowa"
 className="px-2 py-1.5 text-right align-top font-mono text-[12px] leading-5 whitespace-nowrap max-xl:block max-xl:border-b max-xl:border-b-border/60 max-xl:text-left"
 >
 <MobileFieldLabel>Stawka kosztowa</MobileFieldLabel>
 {m.rate_candidate != null
 ? formatCurrency(m.rate_candidate, candidateCurrency(m))
 :"—"}
 </TableCell>
 <TableCell
 data-label="Stawka przychodowa"
 className="px-2 py-1.5 text-right align-top font-mono text-[12px] font-semibold leading-5 whitespace-nowrap max-xl:block max-xl:border-b max-xl:border-b-border/60 max-xl:text-left"
 >
 <MobileFieldLabel>Stawka przychodowa</MobileFieldLabel>
 {m.rate_client != null
 ? formatCurrency(m.rate_client, clientCurrency(m))
 :"—"}
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
 </TableCell>
 </TableRow>
 );
 })}
 </TableBody>
 );
 })
 )}
 </Table>

 {toast && (
 <div className="fixed bottom-24 right-4 z-9999 px-4 py-3 rounded-lg shadow-md text-sm bg-card text-foreground">
 {toast}
 </div>
 )}

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
}
