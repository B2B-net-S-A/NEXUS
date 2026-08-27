"use client";

import { useEffect, useMemo, useRef, useState } from"react";
import Link from"next/link";
import { useSearchParams } from"next/navigation";
import { useQuery, useQueryClient } from"@tanstack/react-query";
import {
 AlertTriangle,
 Calendar,
 CheckCircle2,
 FileText,
 UserCog,
} from"lucide-react";
import {
 contractorsApi,
 type ContractorListItem,
 type ContractorStatus,
} from"@/lib/api";
import { cn, formatCurrency, formatDate } from"@/lib/utils";
import {
 httpStatusFromError,
 isBlockingViewState,
 resolveViewState,
 type ViewState,
} from"@/lib/view-state";
import {
 canManageCandidateFinance,
 useAuthStore,
} from"@/store/auth";
import { Badge } from"@/components/ui/badge";
import { Button, buttonVariants } from"@/components/ui/button";
import { Card } from"@/components/ui/card";
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
import { DraftCompletionModal } from"@/components/v2/modals/DraftCompletionModal";
import { TerminateContractModal } from"@/components/client-profile/actions/TerminateContractModal";
import {
 buildContractDetailHref,
 buildContractorsListUrl,
 parseContractorsListState,
 rememberContractsListScroll,
 restoreContractsListScroll,
 takeContractsListScroll,
} from "@/lib/contracts-list-navigation";

type Tab = Exclude<ContractorStatus, "ready_for_signature">;

const PAGE_SIZE = 50;

const TAB_LABELS: Record<Tab, string> = {
 draft: "Do uzupełnienia",
 active: "Aktywni",
 ending: "Kończący się",
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

function rateUnitLabel(unit: ContractorListItem["rate_unit"]): string {
 if (unit === "hourly") return"/h";
 if (unit === "daily") return"/dz";
 return"/mies";
}

export function ContractorsListV2() {
 const user = useAuthStore((state) => state.user);
 const canManageFinance = canManageCandidateFinance(user);
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

 const selectTab = (next: Tab) => {
 setTab(next);
 setPage(1);
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
 canManageFinance || !["rate_candidate","rate_client"].includes(field)
 )
 .map(([, label]) => label);
 const visibleColumnCount = canManageFinance ? 8 : 6;

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

 return (
 <div className="max-w-[1400px] mx-auto space-y-4 p-6">
 <div className="flex items-end justify-between flex-wrap gap-3">
 <div>
 <p className="text-xs font-semibold uppercase tracking-eyebrow text-primary">
 Delivery · Kontraktorzy
 </p>
 <h1 className="font-semibold text-3xl font-extrabold tracking-heading-tight text-foreground mt-1">
 Kontraktorzy
 </h1>
 <p className="text-sm text-muted-foreground mt-1">
 Zatrudnieni kandydaci — aktywni, kończący się i drafty do uzupełnienia.
 </p>
 </div>
 </div>

 {incompleteCount > 0 && tab !== "draft" && (
 <Card className="bg-warning-muted border-warning/25 flex items-center gap-3 p-4!">
 <AlertTriangle className="h-5 w-5 text-warning-muted-foreground shrink-0" />
 <div className="flex-1">
 <p className="text-sm font-semibold text-warning-muted-foreground">
 {incompleteCount} draft{incompleteCount > 1 ?"y" :""} czeka na
 uzupełnienie
 </p>
 <p className="text-xs text-warning-muted-foreground">
 Bez wymaganych danych operacyjnych kontraktu nie możemy go aktywować.
 </p>
 </div>
 <Button
 size="sm"
 variant="outline"
 onClick={() => selectTab("draft")}
 >
 Pokaż drafty
 </Button>
 </Card>
 )}

 <div
 role="tablist"
 aria-label="Filtry kontraktorów"
 className="flex gap-1 border-b border-border"
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
 onClick={() => selectTab(t)}
 className={cn("px-4 py-2 text-sm font-medium border-b-2 transition-colors",
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

 <Table density="cozy">
 <TableHeader>
 <TableRow>
 <TableHead>Kandydat</TableHead>
 <TableHead className="max-w-[240px]">Klient · Rekrutacja</TableHead>
 <TableHead>Daty</TableHead>
 <TableHead>Tryb</TableHead>
 {canManageFinance && (
 <>
 <TableHead className="text-right">Stawka klient</TableHead>
 <TableHead className="text-right">Marża</TableHead>
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
 ?"Twoja rola nie ma dostępu do listy kontraktorów. Lista NIE jest pusta — poproś administratora o uprawnienia."
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
 (field) => canManageFinance || !FINANCE_COMPLETION_FIELDS.has(field)
 );
 const waitsForAdmin =
 isDraft &&
 !canManageFinance &&
 c.missing_fields.some((field) => FINANCE_COMPLETION_FIELDS.has(field));
 const revenueCurrency = c.rate_client_currency ?? c.currency ?? "PLN";
 const costCurrency = c.rate_candidate_currency ?? c.currency ?? "PLN";
 const hasComparableCurrencies =
 revenueCurrency.toUpperCase() === costCurrency.toUpperCase();
 return (
 <TableRow key={c.contract_id} interactive>
 <TableCell>
 <Link
 href={`/candidates/${c.candidate.id}`}
 className="font-medium text-foreground hover:text-primary"
 >
 {c.candidate.name} {c.candidate.lastname}
 </Link>
 {c.candidate.email && (
 <TruncatedText className="text-xs text-muted-foreground">
 {c.candidate.email}
 </TruncatedText>
 )}
 </TableCell>
 <TableCell>
 <TruncatedText className="text-sm">{c.client_name}</TruncatedText>
 <TruncatedText className="text-xs text-muted-foreground">
 {c.job_title}
 </TruncatedText>
 </TableCell>
 <TableCell>
 <div className="flex items-center gap-1 text-xs text-foreground">
 <Calendar className="h-3 w-3" />
 {formatDate(c.start_date)}
 </div>
 <div className="text-xs text-muted-foreground">
 {c.end_date ? `→ ${formatDate(c.end_date)}` :"brak daty końca"}
 </div>
 </TableCell>
 <TableCell>
 <Badge size="sm" variant="soft">
 {c.work_mode ??"—"}
 </Badge>
 </TableCell>
 {canManageFinance && (
 <>
 <TableCell className="text-right font-mono text-sm">
 {c.rate_client != null
 ? `${formatCurrency(c.rate_client, revenueCurrency)}${rateUnitLabel(c.rate_unit)}`
 :"—"}
 </TableCell>
 <TableCell className="text-right font-mono text-sm">
 {c.margin != null && hasComparableCurrencies
 ? formatCurrency(c.margin, revenueCurrency) : "—"}
 </TableCell>
 </>
 )}
 <TableCell>
 {isDraft && visibleMissingFields.length > 0 ? (
 <Badge size="sm" variant="warning">
 {visibleMissingFields.length} brak
 {visibleMissingFields.length === 1 ?"" :"ów"}
 </Badge>
 ) : waitsForAdmin ? (
 <Badge size="sm" variant="warning">
 Wymaga uzupełnienia przez Admina
 </Badge>
 ) : isReadyForSignature ? (
 <Badge size="sm" variant="soft">
 Do aktywacji
 </Badge>
 ) : readyToActivate ? (
 <Badge size="sm" variant="soft">
 gotowy
 </Badge>
 ) : (
 <Badge
 size="sm"
 variant={c.status === "active" ?"success" :"warning"}
 >
 {c.status}
 </Badge>
 )}
 </TableCell>
 <TableCell className="text-right">
 <div className="flex items-center justify-end gap-1">
 {isDraft && (!waitsForAdmin || visibleMissingFields.length > 0) ? (
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
 {(c.status === "active" || c.status === "ending") && (
 <Button
 size="sm"
 variant="ghost"
 className="text-destructive hover:bg-destructive/10"
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

 {terminating && (
 <TerminateContractModal
 contractId={terminating.contract_id}
 candidateName={`${terminating.candidate.name} ${terminating.candidate.lastname}`.trim()}
 clientId={terminating.client_id ?? 0}
 onClose={() => setTerminating(null)}
 onTerminated={() => {
 queryClient.invalidateQueries({ queryKey: ["contractors-v2"] });
 queryClient.invalidateQueries({ queryKey: ["contractors-stats-v2"] });
 }}
 />
 )}

 {draftToComplete && (
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
