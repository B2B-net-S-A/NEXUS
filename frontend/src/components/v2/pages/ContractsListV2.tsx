"use client";

import { useMemo, useState } from"react";
import Link from"next/link";
import { useQuery, useQueryClient } from"@tanstack/react-query";
import {
 AlertTriangle,
 Calendar,
 FileText,
 Plus,
 Search,
 TrendingUp,
} from"lucide-react";
import api from"@/lib/api";
import { cn, formatCurrency, formatDate } from"@/lib/utils";
import { Badge } from"@/components/ui/badge";
import { Button } from"@/components/ui/button";
import { Card } from"@/components/ui/card";
import { Checkbox } from"@/components/ui/checkbox";
import { Input } from"@/components/ui/input";
import { ContractsBulkActionsBarV2 } from"@/components/v2/modals/ContractsBulkActionsBar";
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from"@/components/ui/select";
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

interface ContractRow {
 id: number;
 candidate_name?: string;
 client_name?: string;
 job_title?: string;
 start_date?: string;
 end_date?: string;
 contract_type?: string;
 rate_client?: number;
 rate_candidate?: number;
 margin?: number;
 status?: string;
 currency?: string;
}

const STATUS_VARIANT: Record<
 string, "success" |"warning" |"neutral" |"danger" |"soft"
> = {
 active: "success",
 expiring: "warning",
 ended: "neutral",
 terminated: "danger",
 draft: "soft",
};

function marginColor(margin: number | undefined) {
 if (margin == null) return"text-muted-foreground";
 const pct = margin * 100;
 if (pct < 15) return"text-primary font-bold";
 if (pct < 25) return"text-amber-600 font-semibold";
 return"text-[#1d5e31] font-semibold";
}

export function ContractsListV2() {
 const [search, setSearch] = useState("");
 const [statusFilter, setStatusFilter] = useState<ContractStatusValue[]>([]);
 const [typeFilter, setTypeFilter] = useState<ContractTypeValue[]>([]);
 const [page, setPage] = useState(1);
 const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
 const [toast, setToast] = useState<string | null>(null);
 const queryClient = useQueryClient();

 const toggleId = (id: number) => {
 setSelectedIds((prev) => {
 const next = new Set(prev);
 if (next.has(id)) next.delete(id);
 else next.add(id);
 return next;
 });
 };

 const { data, isLoading } = useQuery({
 queryKey: ["contracts-v2", search, statusFilter, typeFilter, page],
 queryFn: () =>
 api
 .get("/api/contracts", {
 params: {
 q: search || undefined,
 status: statusFilter.length ? statusFilter : undefined,
 contract_type: typeFilter.length ? typeFilter : undefined,
 page,
 },
 paramsSerializer: { indexes: null },
 })
 .then((r) => r.data),
 });

 const { data: expiring } = useQuery({
 queryKey: ["contracts-expiring-v2"],
 queryFn: () => api.get("/api/contracts/expiring").then((r) => r.data),
 staleTime: 5 * 60 * 1000,
 });

 const items: ContractRow[] = data?.items ?? [];
 const total = data?.total ?? 0;
 const pageSize = data?.page_size ?? 20;
 const totalPages = Math.max(1, Math.ceil(total / pageSize));

 const expiringCount = useMemo(
 () => (Array.isArray(expiring) ? expiring.length : expiring?.total ?? 0),
 [expiring]
 );

 return (
 <div className="max-w-[1400px] mx-auto space-y-4">
 {/* Header */}
 <div className="flex items-end justify-between flex-wrap gap-3">
 <div>
 <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
 Delivery · Kontrakty
 </p>
 <h1 className="font-semibold text-3xl font-extrabold tracking-[-0.02em] text-foreground mt-1">
 Kontrakty
 </h1>
 <p className="text-sm text-muted-foreground mt-1">
 {isLoading ?"Ładowanie…" : `${total} kontraktów w systemie`}
 </p>
 </div>
 <div className="flex items-center gap-2">
 <Link href="/contracts/analytics">
 <Button size="sm" variant="outline">
 <TrendingUp className="h-4 w-4" /> Analityka
 </Button>
 </Link>
 <Link href="/contracts/new">
 <Button size="sm" variant="primary">
 <Plus className="h-4 w-4" /> Nowy kontrakt
 </Button>
 </Link>
 </div>
 </div>

 {/* Expiring alert */}
 {expiringCount > 0 && (
 <Card className="bg-amber-50 border-amber-200 flex items-center gap-3 !p-4">
 <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0" />
 <div className="flex-1">
 <p className="text-sm font-semibold text-amber-800">
 {expiringCount} kontrakt{expiringCount > 1 ?"y" :""} kończą się w ciągu 30 dni
 </p>
 <p className="text-xs text-amber-700">
 Sprawdź, czy wymagają przedłużenia albo wypowiedzenia.
 </p>
 </div>
 <Button
 size="sm"
 variant="outline"
 onClick={() => {
 // Backend ContractStatus enum uses `ending` (frontend banner reads
 //"Kończące się"). Filter by that single status to surface them.
 setStatusFilter(["ending"]);
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
 </div>

 {/* Bulk actions bar */}
 <ContractsBulkActionsBarV2
 selectedIds={selectedIds}
 onClear={() => setSelectedIds(new Set())}
 onSelectAllVisible={() =>
 setSelectedIds(
 selectedIds.size === items.length
 ? new Set()
 : new Set(items.map((i) => i.id))
 )
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

 {/* Table */}
 <Table density="cozy">
 <TableHeader>
 <TableRow>
 <TableHead className="w-8">
 <Checkbox
 checked={
 items.length > 0 && items.every((i) => selectedIds.has(i.id))
 ? true
 : selectedIds.size > 0
 ?"indeterminate"
 : false
 }
 onCheckedChange={(v) =>
 setSelectedIds(v ? new Set(items.map((i) => i.id)) : new Set())
 }
 aria-label="Zaznacz wszystkie"
 />
 </TableHead>
 <TableHead>Kandydat</TableHead>
 <TableHead>Klient · Oferta</TableHead>
 <TableHead>Daty</TableHead>
 <TableHead>Typ</TableHead>
 <TableHead className="text-right">Stawka klient</TableHead>
 <TableHead className="text-right">Marża</TableHead>
 <TableHead>Status</TableHead>
 </TableRow>
 </TableHeader>
 <TableBody>
 {isLoading ? (
 <TableRow>
 <TableCell colSpan={8} className="text-center py-10 text-muted-foreground">
 Ładowanie…
 </TableCell>
 </TableRow>
 ) : items.length === 0 ? (
 <TableRow>
 <TableCell colSpan={8} className="text-center py-10">
 <FileText className="h-10 w-10 mx-auto text-muted-foreground mb-2 opacity-40" />
 <p className="text-sm text-muted-foreground">
 Brak kontraktów spełniających kryteria.
 </p>
 </TableCell>
 </TableRow>
 ) : (
 items.map((c) => (
 <TableRow key={c.id} interactive selected={selectedIds.has(c.id)}>
 <TableCell onClick={(e) => e.stopPropagation()}>
 <Checkbox
 checked={selectedIds.has(c.id)}
 onCheckedChange={() => toggleId(c.id)}
 aria-label={`Zaznacz kontrakt ${c.id}`}
 />
 </TableCell>
 <TableCell>
 <Link
 href={`/contracts/${c.id}`}
 className="font-medium text-foreground hover:text-primary"
 >
 {c.candidate_name ?? `#${c.id}`}
 </Link>
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
 {c.start_date ? formatDate(c.start_date) : "—"}
 </div>
 {c.end_date && (
 <div className="text-xs text-muted-foreground">
 → {formatDate(c.end_date)}
 </div>
 )}
 </TableCell>
 <TableCell>
 <Badge size="sm" variant="soft">
 {c.contract_type ??"—"}
 </Badge>
 </TableCell>
 <TableCell className="text-right font-mono text-sm">
 {c.rate_client != null ? formatCurrency(c.rate_client, c.currency ??"PLN") : "—"}
 </TableCell>
 <TableCell className={cn("text-right font-mono text-sm", marginColor(c.margin))}>
 {c.margin != null ? `${(c.margin * 100).toFixed(1)}%` :"—"}
 </TableCell>
 <TableCell>
 {c.status ? (
 <Badge size="sm" variant={STATUS_VARIANT[c.status] ??"neutral"}>
 {c.status}
 </Badge>
 ) : (
 <span className="text-xs text-muted-foreground">—</span>
 )}
 </TableCell>
 </TableRow>
 ))
 )}
 </TableBody>
 </Table>

 {toast && (
 <div className="fixed bottom-24 right-4 z-[9999] px-4 py-3 rounded-lg shadow-md text-sm bg-card text-foreground">
 {toast}
 </div>
 )}

 {/* Pagination */}
 {!isLoading && total > pageSize && (
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
