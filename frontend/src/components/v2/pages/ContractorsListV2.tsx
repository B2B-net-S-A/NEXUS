"use client";

import { useMemo, useState } from"react";
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
import { DraftCompletionModal } from"@/components/v2/modals/DraftCompletionModal";

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

function rateUnitLabel(unit: ContractorListItem["rate_unit"]): string {
 if (unit === "hourly") return"/h";
 if (unit === "daily") return"/dz";
 return"/mies";
}

export function ContractorsListV2() {
 const searchParams = useSearchParams();
 const initialTab = (searchParams.get("tab") as Tab) ||"active";
 const [tab, setTab] = useState<Tab>(
 ["draft","active","ending"].includes(initialTab) ? initialTab : "active"
 );
 const [page, setPage] = useState(1);
 const selectTab = (next: Tab) => {
 setTab(next);
 setPage(1);
 // Persist the active tab in the URL (preserving ?view=operations from the
 // /contracts shell) so the operations mode is deep-linkable and survives a
 // reload. Read once on mount via searchParams below; written via the History
 // API to avoid a Next router navigation.
 const params = new URLSearchParams(window.location.search);
 params.set("tab", next);
 window.history.replaceState(
 null,
 "",
 `${window.location.pathname}?${params.toString()}`
 );
 };
 const [draftToComplete, setDraftToComplete] =
 useState<ContractorListItem | null>(null);
 const queryClient = useQueryClient();

 const { data, isLoading } = useQuery({
 queryKey: ["contractors-v2", tab, page],
 queryFn: () =>
 contractorsApi
 .list({ status: tab, page, page_size: PAGE_SIZE })
 .then((r) => r.data),
 });

 const { data: stats } = useQuery({
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
 const endingCount = stats?.ending ?? 0;

 return (
 <div className="max-w-[1400px] mx-auto space-y-4 p-6">
 <div className="flex items-end justify-between flex-wrap gap-3">
 <div>
 <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
 Delivery · Kontraktorzy
 </p>
 <h1 className="font-semibold text-3xl font-extrabold tracking-[-0.02em] text-foreground mt-1">
 Kontraktorzy
 </h1>
 <p className="text-sm text-muted-foreground mt-1">
 Zatrudnieni kandydaci — aktywni, kończący się i drafty do uzupełnienia.
 </p>
 </div>
 </div>

 {incompleteCount > 0 && tab !== "draft" && (
 <Card className="bg-warning-muted border-warning/25 flex items-center gap-3 !p-4">
 <AlertTriangle className="h-5 w-5 text-warning-muted-foreground shrink-0" />
 <div className="flex-1">
 <p className="text-sm font-semibold text-warning-muted-foreground">
 {incompleteCount} draft{incompleteCount > 1 ?"y" :""} czeka na
 uzupełnienie
 </p>
 <p className="text-xs text-warning-muted-foreground">
 Bez stawek, dat, typu umowy i trybu pracy nie możemy aktywować
 kontraktu.
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
 <span className="ml-2 text-xs text-muted-foreground">
 {count}
 </span>
 </button>
 );
 })}
 </div>

 <Table density="cozy">
 <TableHeader>
 <TableRow>
 <TableHead>Kandydat</TableHead>
 <TableHead>Klient · Oferta</TableHead>
 <TableHead>Daty</TableHead>
 <TableHead>Tryb</TableHead>
 <TableHead className="text-right">Stawka klient</TableHead>
 <TableHead className="text-right">Marża</TableHead>
 <TableHead>Status</TableHead>
 <TableHead className="text-right">Akcje</TableHead>
 </TableRow>
 </TableHeader>
 <TableBody>
 {isLoading ? (
 <TableRow>
 <TableCell
 colSpan={8}
 className="text-center py-10 text-muted-foreground"
 >
 Ładowanie…
 </TableCell>
 </TableRow>
 ) : items.length === 0 ? (
 <TableRow>
 <TableCell colSpan={8} className="text-center py-10">
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
 <div className="text-xs text-muted-foreground">
 {c.candidate.email}
 </div>
 )}
 </TableCell>
 <TableCell>
 <div className="text-sm">{c.client_name ??"—"}</div>
 <div className="text-xs text-muted-foreground truncate max-w-[200px]">
 {c.job_title ??"—"}
 </div>
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
 <TableCell className="text-right font-mono text-sm">
 {c.rate_client != null
 ? `${formatCurrency(c.rate_client, c.currency ?? "PLN")}${rateUnitLabel(c.rate_unit)}`
 :"—"}
 </TableCell>
 <TableCell className="text-right font-mono text-sm">
 {c.margin != null
 ? formatCurrency(c.margin, c.currency ?? "PLN") : "—"}
 </TableCell>
 <TableCell>
 {isDraft && c.missing_fields.length > 0 ? (
 <Badge size="sm" variant="warning">
 {c.missing_fields.length} brak
 {c.missing_fields.length === 1 ?"" :"ów"}
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
 {isDraft ? (
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
 href={`/contracts/${c.contract_id}?from=contractors`}
 className={buttonVariants({ size: "sm", variant: "ghost" })}
 >
 <FileText className="h-3.5 w-3.5" /> Szczegóły
 </Link>
 </div>
 </TableCell>
 </TableRow>
 );
 })
 )}
 </TableBody>
 </Table>

 <div className="text-xs text-muted-foreground pt-2">
 {total} wynik{total === 1 ?"" : total < 5 ?"i" :"ów"} ·{""}
 {tab === "draft" && incompleteCount > 0 && (
 <>braki: {Object.keys(FIELD_LABELS).join(" /")}</>
 )}
 </div>

 {!isLoading && total > pageSize && (
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
