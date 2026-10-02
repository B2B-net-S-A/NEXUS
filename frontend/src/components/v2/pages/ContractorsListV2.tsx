"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from"react";
import Link from"next/link";
import dynamic from"next/dynamic";
import { useSearchParams } from"next/navigation";
import { useQuery, useQueryClient } from"@tanstack/react-query";
import {
 AlertTriangle,
 CheckCircle2,
 FileText,
 UserCog,
} from"lucide-react";
import {
 contractorsApi,
 type ContractorListItem,
 type ContractorStatus,
} from"@/lib/api";
import { cn, formatCurrency } from"@/lib/utils";
import { formatIsoDatePl } from "@/lib/date-pl";
import { CONTRACT_STATUS_LABEL } from "@/lib/contract-register";
import { lacksCurrentOrder } from "@/lib/client-order-list";
import type { ContractWithOrdersRead } from "@/lib/api/dlPortal";
import {
 httpStatusFromError,
 isBlockingViewState,
 resolveViewState,
 type ViewState,
} from"@/lib/view-state";
import {
 canManageCandidateFinance,
 canManageContractStatus,
 canViewCandidateFinance,
 useAuthStore,
} from"@/store/auth";
import { hasPermission, permissionLabel } from "@/lib/permissions";
import { Badge } from"@/components/ui/badge";
import { Button, buttonVariants } from"@/components/ui/button";
import {
 Table,
 TableBody,
 TableCell,
 TableHead,
 TableHeader,
 TableRow,
} from"@/components/ui/table";
import { TruncatedText } from"@/components/ds/TruncatedText";
import { QueryStateNotice } from"@/components/ds/QueryStateNotice";
import { StatusDot } from"@/components/ds/StatusDot";
import { CALM_AMOUNT, CALM_EMPTY, CALM_SUBLINE, CALM_UNIT } from"@/lib/calm-table";
import { DraftCompletionModal } from"@/components/v2/modals/DraftCompletionModal";
import { ContractTerminationDialog } from"@/components/contracts/ContractTerminationDialog";
import { ListDetailLayout } from"@/components/ds/ListDetailLayout";
import {
 WIDE_HIDDEN,
 WIDE_ONLY_CELL,
 WIDE_ONLY_INLINE,
 WIDE_TABLE_CONTAINER,
} from"@/lib/wide-table";
import { rowActivationProps, useRowNavigation } from"@/hooks/useRowNavigation";
import {
 buildContractDetailHref,
 buildContractorsListUrl,
 parseContractorsListState,
 rememberContractsListScroll,
 restoreContractsListScroll,
 takeContractsListScroll,
} from "@/lib/contracts-list-navigation";

type Tab = Exclude<ContractorStatus, "ready_for_signature">;

// Boczny panel kontraktu (wersja B) — ładowany dopiero po kliknięciu wiersza.
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

const PAGE_SIZE = 50;

const TAB_LABELS: Record<Tab, string> = {
 draft: "Do uzupełnienia",
 active: "Aktywni",
 ending: "Kończący się",
};

// Co naprawdę jest w zakładce (audyt 24.09, S6). Od 0367 status „Kończący
// się” dostaje każda wypowiedziana umowa — także z datą za pół roku — więc
// zakładka to status `ending` ORAZ umowy kończące się w ciągu 30 dni (zanim
// nocny cron przestawi ich status). Liczy to backend (`/api/contractors`).
const TAB_HINTS: Partial<Record<Tab, string>> = {
 ending:
 "Wypowiedziane kontrakty (dowolna data zakończenia) oraz kontrakty kończące się w ciągu 30 dni.",
};

const FIELD_LABELS: Record<string, string> = {
 start_date: "Data start",
 end_date: "Data koniec",
 rate_candidate: "Stawka kandydat",
 rate_client: "Stawka klient",
 contract_type: "Typ umowy",
 work_mode: "Tryb pracy",
};
const FINANCE_COMPLETION_FIELDS = new Set(["rate_candidate","rate_client"]);

/**
 * Okresy zamówień kontraktu z `/api/contractors` (UAT M08-B05). Pole dochodzi
 * w odpowiedzi API; starsza odpowiedź bez niego nie pokazuje dopisku zamiast
 * pokazywać go wszystkim.
 */
type ContractorOrderRef = {
 status: string;
 start_date: string | null;
 end_date: string | null;
};

function contractorLacksCurrentOrder(c: ContractorListItem): boolean {
 const orders = (c as ContractorListItem & { orders?: ContractorOrderRef[] })
 .orders;
 if (!orders) return false;
 if (c.status !== "active" && c.status !== "ending") return false;
 // Ta sama reguła co karta kontraktora w profilu klienta — czyta wyłącznie
 // status i datę końca, więc wąski kształt jest tu wystarczający.
 return lacksCurrentOrder({
 orders: orders as unknown as ContractWithOrdersRead["orders"],
 });
}

function rateUnitLabel(unit: ContractorListItem["rate_unit"]): string {
 if (unit === "hourly") return"/h";
 if (unit === "daily") return"/dz";
 return"/mies";
}

// „zł/h” stoi raz, w nagłówku kolumn kwot. Wiersz w tej jednostce pokazuje
// samą liczbę; każdy inny (zł/dz, zł/mies, inna waluta) — pełny zapis.
const BARE_AMOUNT = new Intl.NumberFormat("pl-PL", {
 minimumFractionDigits: 2,
 maximumFractionDigits: 3,
});

export function ContractorsListV2({
 modeTabs,
}: {
 /** Przełącznik trybów modułu — pod tytułem (makieta B). */
 modeTabs?: ReactNode;
} = {}) {
 const user = useAuthStore((state) => state.user);
 const impersonating = useAuthStore((state) => state.realUser !== null);
 const canManageFinance = canManageCandidateFinance(user);
 const canViewFinance = canViewCandidateFinance(user);
 // „Uzupełnij" / „Aktywuj" szkicu = „Kontrakty i zamówienia: tworzenie
 // i edycja". „Zakończ projekt" to osobne uprawnienie (zakończenie
 // współpracy) — ma je domyślnie także Talent Community Manager.
 const canCompleteDrafts =
 !impersonating && hasPermission(user,"contracts_orders_edit");
 const canTerminate = !impersonating && canManageContractStatus(user);
 const searchParams = useSearchParams();
 const navigationSearch = searchParams.toString();
 const [initialListState] = useState(() => {
 const parsed = parseContractorsListState(navigationSearch);
 return {
 ...parsed,
 returnTarget: buildContractorsListUrl(parsed.state),
 };
 });
 const [tab, setTab] = useState<Tab>(initialListState.state.tab);
 const [page, setPage] = useState(initialListState.state.page);
 const ownNavigationUrl = useRef<string | null>(null);
 const restoredScroll = useRef(false);
 const returnTarget = useMemo(
 () => buildContractorsListUrl({ tab, page }),
 [tab, page],
 );

 useEffect(() => {
 const current = `${window.location.pathname}${window.location.search}`;
 if (current !== returnTarget) {
 ownNavigationUrl.current = returnTarget;
 window.history.replaceState(window.history.state, "", returnTarget);
 }
 }, [returnTarget]);

 useEffect(() => {
 const currentUrl = `/contracts${navigationSearch ? `?${navigationSearch}` : ""}`;
 if (ownNavigationUrl.current === currentUrl) {
 ownNavigationUrl.current = null;
 return;
 }
 const next = parseContractorsListState(navigationSearch).state;
 setTab(next.tab);
 setPage(next.page);
 }, [navigationSearch]);

 // Kontrakt otwarty w bocznym panelu; zmiana zakładki go zamyka (wiersz
 // zniknąłby z listy).
 const [openContractId, setOpenContractId] = useState<number | null>(null);
 const listRef = useRef<HTMLDivElement>(null);
 const selectTab = (next: Tab) => {
 setTab(next);
 setPage(1);
 setOpenContractId(null);
 };
 const [draftToComplete, setDraftToComplete] =
 useState<ContractorListItem | null>(null);
 // „Zakończ projekt" (ticket #5 krok 4) — per wiersz = per kontrakt u jednego
 // klienta, więc wybór klienta jest zbędny; backend synchronizuje zamówienia.
 const [terminating, setTerminating] = useState<ContractorListItem | null>(null);
 const queryClient = useQueryClient();

 const { data, isPending, isError, error, refetch } = useQuery({
 queryKey: ["contractors-v2", tab, page],
 queryFn: () =>
 contractorsApi
 .list({ status: tab, page, page_size: PAGE_SIZE })
 .then((r) => r.data),
 });

 const { data: stats, isError: statsFailed } = useQuery({
 queryKey: ["contractors-stats-v2"],
 queryFn: () => contractorsApi.stats().then((r) => r.data),
 staleTime: 60_000,
 });

 const items = useMemo(() => data?.items ?? [], [data]);
 const rowKeys = useMemo(() => items.map((c) => String(c.contract_id)), [items]);
 useRowNavigation({
 keys: rowKeys,
 activeKey: openContractId != null ? String(openContractId) : null,
 onChange: (key) => setOpenContractId(Number(key)),
 containerRef: listRef,
 enabled: openContractId != null,
 });
 const openItem =
 openContractId != null
 ? items.find((c) => c.contract_id === openContractId) ?? null
 : null;
 const total = data?.total ?? 0;
 const pageSize = data?.page_size ?? PAGE_SIZE;
 const totalPages = Math.max(1, Math.ceil(total / pageSize));

 const onActivated = () => {
 setDraftToComplete(null);
 queryClient.invalidateQueries({ queryKey: ["contractors-v2"] });
 queryClient.invalidateQueries({ queryKey: ["contractors-stats-v2"] });
 };

 const draftCount = stats?.draft ?? 0;
 const incompleteCount = stats?.drafts_incomplete ?? 0;
 const activeCount = stats?.active ?? 0;
 const activeContractsCount = stats?.active_contracts ?? 0;
 const endingCount = stats?.ending ?? 0;
 const visibleFieldLabels = Object.entries(FIELD_LABELS)
 .filter(
 ([field]) =>
 canViewFinance || !["rate_candidate","rate_client"].includes(field)
 )
 .map(([, label]) => label);
 // Z trzema kolumnami szerokiej tabeli (w wąskiej są ukryte).
 const visibleColumnCount = canViewFinance ? 11 : 9;

 // 403 (stawki = uprawnienie finansowe) i 5xx NIE mogą renderować się jako
 // „Brak aktywnych kontraktorów" — to zdanie o delivery, a nie o serwerze
 // (audyt F-20). Pusty stan wisi na sukcesie: `isPending`, nie `isLoading`,
 // bo w przerwie między ponowieniami `isLoading` jest już `false`, a `items`
 // dalej puste.
 const viewState = resolveViewState({
 isLoading: isPending,
 isError,
 error,
 isEmpty: items.length === 0,
 });
 const failed = isBlockingViewState(viewState);

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

 const listContent = (
 <div className="space-y-3">
 <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5">
 <h1 className="text-lg font-semibold text-foreground">Kontrakty</h1>
 <p className="text-xs text-muted-foreground">
 Obsługa kontraktorów — aktywni, kończący się i drafty do uzupełnienia.
 </p>
 </div>

 {modeTabs}

 {/* Wąski pasek ostrzeżenia w jednej linii — duża karta spychała tabelę
 w dół na laptopie. */}
 {incompleteCount > 0 && tab !== "draft" && (
 <div
 role="status"
 className="flex min-h-8 flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-warning/25 bg-warning-muted px-2 py-1 text-xs text-warning-muted-foreground"
 >
 <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
 <span className="min-w-0">
 <span className="font-semibold">
 {incompleteCount} draft{incompleteCount > 1 ?"y" :""} czeka na
 uzupełnienie
 </span>
 {" "}— bez wymaganych danych operacyjnych kontraktu nie możemy go aktywować.
 </span>
 <Button
 size="sm"
 variant="outline"
 className="ml-auto h-6 px-2"
 onClick={() => selectTab("draft")}
 >
 Pokaż drafty
 </Button>
 </div>
 )}

 <div
 role="tablist"
 aria-label="Filtry kontraktorów"
 className="flex gap-1 overflow-x-auto border-b border-border"
 >
 {(["draft","active","ending"] as Tab[]).map((t) => {
 const count =
 t === "draft" ? draftCount : t === "active" ? activeCount : endingCount;
 const isActive = t === tab;
 return (
 <button
 key={t}
 role="tab"
 aria-selected={isActive}
 title={TAB_HINTS[t]}
 onClick={() => selectTab(t)}
 className={cn("shrink-0 whitespace-nowrap px-3 py-1.5 text-[13px] font-medium border-b-2 transition-colors",
 isActive
 ?"border-primary text-foreground"
 :"border-transparent text-muted-foreground hover:text-foreground"
 )}
 >
 {TAB_LABELS[t]}
 <span
 className="ml-2 text-xs text-muted-foreground"
 title={statsFailed ? "Nie udało się pobrać liczników" : undefined}
 >
 {/* Licznik z padniętego zapytania to zero z inicjalizacji, nie pomiar —
 „0 aktywnych" byłoby zmyśleniem o delivery. */}
 {statsFailed
 ?"—"
 : t === "active"
 ?`${activeCount} osób / ${activeContractsCount} umów`
 : count}
 </span>
 </button>
 );
 })}
 </div>
 {TAB_HINTS[tab] && (
 <p className="text-xs text-muted-foreground" data-testid="contractors-tab-hint">
 {TAB_HINTS[tab]}
 </p>
 )}

 {/* Szeroka tabela (≥ 1700 px): e-mail, rekrutacja i data końca mają
 własne kolumny zamiast drugiej linii pod kandydatem, klientem i startem. */}
 <div className={WIDE_TABLE_CONTAINER}>
 <Table density="cozy">
 <TableHeader>
 <TableRow>
 <TableHead className="max-md:sticky max-md:left-0 max-md:z-10 max-md:bg-card">Kandydat</TableHead>
 <TableHead className={WIDE_ONLY_CELL}>E-mail</TableHead>
 <TableHead className="max-w-[240px]">
 Klient
 <span className={WIDE_HIDDEN}> · Rekrutacja</span>
 </TableHead>
 <TableHead className={WIDE_ONLY_CELL}>Rekrutacja</TableHead>
 <TableHead>
 <span className={WIDE_HIDDEN}>Daty</span>
 <span className={WIDE_ONLY_INLINE}>Start</span>
 </TableHead>
 <TableHead className={WIDE_ONLY_CELL}>Koniec</TableHead>
 <TableHead>Tryb</TableHead>
 {canViewFinance && (
 <>
 <TableHead className="text-right">
 Stawka klient <span className={CALM_UNIT}>zł/h</span>
 </TableHead>
 <TableHead className="text-right">
 Marża <span className={CALM_UNIT}>zł/h</span>
 </TableHead>
 </>
 )}
 <TableHead>Status</TableHead>
 <TableHead className="text-right">Akcje</TableHead>
 </TableRow>
 </TableHeader>
 <TableBody>
 {viewState === "loading" ? (
 <TableRow>
 <TableCell
 colSpan={visibleColumnCount}
 className="text-center py-10 text-muted-foreground"
 >
 Ładowanie…
 </TableCell>
 </TableRow>
 ) : failed ? (
 <TableRow>
 <TableCell colSpan={visibleColumnCount} className="p-0">
 <QueryStateNotice
 state={
 viewState as Extract<
 ViewState,
 "forbidden" | "not_found" | "error"
 >
 }
 className="border-0"
 description={
 viewState === "forbidden"
 ? `Lista kontraktorów wymaga uprawnienia „${permissionLabel("delivery_view")}”. Lista NIE jest pusta — poproś administratora o dostęp (Ustawienia → Zespół i dostęp → Osoby i role).`
 : viewState === "error" &&
 httpStatusFromError(error) === undefined
 ?"Nie udało się połączyć z serwerem. Sprawdź internet lub VPN i spróbuj ponownie."
 : undefined
 }
 onRetry={viewState === "error" ? () => void refetch() : undefined}
 />
 </TableCell>
 </TableRow>
 ) : viewState === "empty" ? (
 <TableRow>
 <TableCell colSpan={visibleColumnCount} className="text-center py-10">
 <UserCog className="h-10 w-10 mx-auto text-muted-foreground mb-2 opacity-40" />
 <p className="text-sm text-muted-foreground">
 {tab === "draft"
 ?"Brak draftów do uzupełnienia — wszystko aktywne."
 : tab === "active"
 ?"Brak aktywnych kontraktorów."
 :"Żaden kontrakt nie kończy się w najbliższym czasie."}
 </p>
 </TableCell>
 </TableRow>
 ) : (
 items.map((c) => {
 const isDraft = c.status === "draft";
 const isReadyForSignature = c.status === "ready_for_signature";
 const readyToActivate = isDraft && c.missing_fields.length === 0;
 const visibleMissingFields = c.missing_fields.filter(
 (field) => canViewFinance || !FINANCE_COMPLETION_FIELDS.has(field)
 );
 // Szkic, któremu brakuje stawek, a to konto ich nie zmienia — czeka na
 // osobę z uprawnieniem „Stawki i kwoty: zmiana".
 const waitsForRates =
 isDraft &&
 !canManageFinance &&
 c.missing_fields.some((field) => FINANCE_COMPLETION_FIELDS.has(field));
 const revenueCurrency = c.rate_client_currency ?? c.currency ?? "PLN";
 const costCurrency = c.rate_candidate_currency ?? c.currency ?? "PLN";
 const hasComparableCurrencies =
 revenueCurrency.toUpperCase() === costCurrency.toUpperCase();
 // Jednostka domyślna (zł/h) stoi w nagłówku — wtedy w komórce
 // zostaje sama liczba.
 const bareAmounts =
 c.rate_unit === "hourly" &&
 revenueCurrency.toUpperCase() === "PLN" &&
 costCurrency.toUpperCase() === "PLN";
 return (
 <TableRow
 key={c.contract_id}
 interactive
 {...rowActivationProps(String(c.contract_id), () =>
 setOpenContractId(c.contract_id),
 )}
 aria-selected={openContractId === c.contract_id}
 data-selected={openContractId === c.contract_id || undefined}
 className={cn(
 "h-[50px] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
 openContractId === c.contract_id &&
 "bg-primary/5 shadow-[inset_3px_0_0_0_hsl(var(--primary))]",
 )}
 >
 <TableCell className="max-md:sticky max-md:left-0 max-md:z-10 max-md:bg-card">
 <Link
 href={`/candidates/${c.candidate.id}`}
 className="font-medium text-foreground hover:text-primary"
 >
 {c.candidate.name} {c.candidate.lastname}
 </Link>
 {c.candidate.email && (
 <TruncatedText className={cn(CALM_SUBLINE, "mt-0", WIDE_HIDDEN)}>
 {c.candidate.email}
 </TruncatedText>
 )}
 </TableCell>
 <TableCell className={WIDE_ONLY_CELL} data-testid="contractor-email-cell">
 {c.candidate.email ? (
 <TruncatedText className="text-xs text-muted-foreground">
 {c.candidate.email}
 </TruncatedText>
 ) : (
 <span className={CALM_EMPTY}>—</span>
 )}
 </TableCell>
 <TableCell>
 <TruncatedText className="text-sm">{c.client_name}</TruncatedText>
 <TruncatedText className={cn(CALM_SUBLINE, "mt-0", WIDE_HIDDEN)}>
 {c.job_title}
 </TruncatedText>
 </TableCell>
 <TableCell className={WIDE_ONLY_CELL} data-testid="contractor-job-cell">
 {c.job_title ? (
 <TruncatedText className="text-sm">{c.job_title}</TruncatedText>
 ) : (
 <span className={CALM_EMPTY}>—</span>
 )}
 </TableCell>
 <TableCell>
 <div className="whitespace-nowrap text-xs tabular-nums text-foreground">
 {formatIsoDatePl(c.start_date)}
 </div>
 <div className={cn(CALM_SUBLINE, "mt-0 whitespace-nowrap tabular-nums", WIDE_HIDDEN)}>
 {c.end_date ? `→ ${formatIsoDatePl(c.end_date)}` :"brak daty końca"}
 </div>
 </TableCell>
 <TableCell
 className={cn(WIDE_ONLY_CELL, "whitespace-nowrap text-xs tabular-nums")}
 data-testid="contractor-end-cell"
 >
 {c.end_date ? (
 formatIsoDatePl(c.end_date)
 ) : (
 <span className={CALM_EMPTY}>brak daty końca</span>
 )}
 </TableCell>
 <TableCell className="text-xs">
 {c.work_mode ? (
 <span className="text-muted-foreground">{c.work_mode}</span>
 ) : (
 <span className={CALM_EMPTY}>—</span>
 )}
 </TableCell>
 {canViewFinance && (
 <>
 <TableCell className={cn(CALM_AMOUNT, "text-sm")}>
 {c.rate_client != null ? (
 bareAmounts ? (
 BARE_AMOUNT.format(c.rate_client)
 ) : (
 `${formatCurrency(c.rate_client, revenueCurrency)}${rateUnitLabel(c.rate_unit)}`
 )
 ) : (
 <span className={CALM_EMPTY}>—</span>
 )}
 </TableCell>
 <TableCell className={cn(CALM_AMOUNT, "text-sm")}>
 {c.margin != null && hasComparableCurrencies ? (
 bareAmounts ? (
 BARE_AMOUNT.format(c.margin)
 ) : (
 `${formatCurrency(c.margin, revenueCurrency)}${rateUnitLabel(c.rate_unit)}`
 )
 ) : (
 <span className={CALM_EMPTY}>—</span>
 )}
 </TableCell>
 </>
 )}
 <TableCell>
 {isDraft && visibleMissingFields.length > 0 ? (
 <Badge size="sm" variant="warning">
 {visibleMissingFields.length} brak
 {visibleMissingFields.length === 1 ?"" :"ów"}
 </Badge>
 ) : waitsForRates ? (
 <Badge
 size="sm"
 variant="warning"
 title={`Stawki uzupełnia osoba z uprawnieniem „${permissionLabel("amounts_edit")}”`}
 >
 Czeka na uzupełnienie stawek
 </Badge>
 ) : isReadyForSignature ? (
 <StatusDot tone="info">Do aktywacji</StatusDot>
 ) : readyToActivate ? (
 <StatusDot tone="info">gotowy</StatusDot>
 ) : (
 // Zwykły status to kropka + etykieta; plakietki zostają dla
 // wierszy wymagających uwagi (braki, czekające stawki).
 <StatusDot
 tone={c.status === "active" ?"success" :"warning"}
 note={
 contractorLacksCurrentOrder(c) ? (
 <span className="text-warning-muted-foreground">
 Brak aktywnego zamówienia
 </span>
 ) : undefined
 }
 >
 {CONTRACT_STATUS_LABEL[c.status] ?? c.status}
 </StatusDot>
 )}
 </TableCell>
 <TableCell className="text-right">
 <div className="flex items-center justify-end gap-1">
 {canCompleteDrafts &&
 isDraft &&
 (!waitsForRates || visibleMissingFields.length > 0) ? (
 <Button
 size="sm"
 variant={readyToActivate ?"primary" :"outline"}
 onClick={() => setDraftToComplete(c)}
 >
 {readyToActivate ? (
 <>
 <CheckCircle2 className="h-3.5 w-3.5" /> Aktywuj
 </>
 ) : ("Uzupełnij"
 )}
 </Button>
 ) : null}
 <Link
 href={buildContractDetailHref(c.contract_id, returnTarget, "contractors")}
 onClick={() => rememberContractsListScroll(returnTarget)}
 className={buttonVariants({ size: "sm", variant: "ghost" })}
 >
 <FileText className="h-3.5 w-3.5" /> Szczegóły
 </Link>
 {canTerminate &&
 (c.status === "active" || c.status === "ending") && (
 <Button
 size="sm"
 variant="quiet"
 onClick={() => setTerminating(c)}
 >
 Zakończ projekt
 </Button>
 )}
 </div>
 </TableCell>
 </TableRow>
 );
 })
 )}
 </TableBody>
 </Table>
 </div>

 {/* Stopka milczy przy awarii — „0 wyników" pod komunikatem o błędzie
 mówiłoby, że policzyliśmy i wyszło zero. */}
 {!failed && (
 <div className="text-xs text-muted-foreground pt-2">
 {total} wynik{total === 1 ?"" : total < 5 ?"i" :"ów"} ·{""}
 {tab === "draft" && incompleteCount > 0 && (
 <>braki: {visibleFieldLabels.join(" /")}</>
 )}
 </div>
 )}

 {viewState === "ready" && total > pageSize && (
 <div className="flex items-center justify-between text-sm">
 <span className="text-muted-foreground">
 Strona <strong className="text-foreground">{page}</strong> z {totalPages}
 </span>
 <div className="flex gap-2">
 <Button
 size="sm"
 variant="outline"
 disabled={page <= 1}
 onClick={() => setPage((p) => p - 1)}
 >
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

 return (
 <div ref={listRef} className="md:p-6">
 <ListDetailLayout
 list={listContent}
 onClose={() => setOpenContractId(null)}
 panelLabel="Szczegóły kontraktu"
 panel={
 openContractId != null ? (
 <ContractSidePanel
 key={openContractId}
 contractId={openContractId}
 onClose={() => setOpenContractId(null)}
 preview={
 openItem
 ? {
 candidate_name: `${openItem.candidate.name} ${openItem.candidate.lastname}`.trim(),
 client_name: openItem.client_name,
 job_title: openItem.job_title,
 status: openItem.status,
 }
 : undefined
 }
 returnTarget={returnTarget}
 source="contractors"
 contractorItem={openItem}
 />
 ) : null
 }
 />

 {canTerminate && terminating && (
 <ContractTerminationDialog
 contractIds={[terminating.contract_id]}
 candidateName={`${terminating.candidate.name} ${terminating.candidate.lastname}`.trim()}
 onClose={() => setTerminating(null)}
 onSuccess={() => setTerminating(null)}
 />
 )}

 {canCompleteDrafts && draftToComplete && (
 <DraftCompletionModal
 contractor={draftToComplete}
 open={!!draftToComplete}
 onOpenChange={(open) => {
 if (!open) setDraftToComplete(null);
 }}
 onActivated={onActivated}
 />
 )}
 </div>
 );
}
