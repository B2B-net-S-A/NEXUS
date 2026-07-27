"use client";

import { useMemo, useState } from"react";
import Link from"next/link";
import { keepPreviousData, useQuery } from"@tanstack/react-query";
import { ArrowDown, ArrowUp, Building2, Plus, Search, Shield, ShieldCheck } from"lucide-react";
import api from"@/lib/api";
import { formatRelativeTime } from"@/lib/utils";
import { useDebouncedValue } from"@/lib/use-debounced-value";
import { resolveViewState } from"@/lib/view-state";
import { useCapability } from"@/hooks/useCapability";
import { AddClientModal } from"@/components/AppShell";
import { QueryStateNotice } from"@/components/ds/QueryStateNotice";
import { Avatar, AvatarFallback } from"@/components/ui/avatar";
import { Badge } from"@/components/ui/badge";
import { Button } from"@/components/ui/button";
import { Input } from"@/components/ui/input";
import {
 Table,
 TableBody,
 TableCell,
 TableHead,
 TableHeader,
 TableRow,
} from"@/components/ui/table";

interface ClientRow {
 id: number;
 name: string;
 industry?: string | null;
 status?: string;
 nda_signed?: boolean;
 created_at?: string;
}

interface HitRatioRow {
 client_id: number;
 closed_jobs: number;
 filled_jobs: number;
 lost_jobs: number;
 hit_ratio: number; // 0..100
 fill_rate: number;
 placements: number;
 active_jobs: number;
 target_achieved: boolean;
}

interface HitRatioResponse {
 period: string;
 clients: HitRatioRow[];
 overall: { avg_hit_ratio: number; hit_ratio_target_pct: number };
}

const STATUS_VARIANT: Record<string, "success" |"neutral" |"soft"> = {
 active: "success",
 inactive: "neutral",
 prospect: "soft",
};

const MIN_CLOSED_FOR_RATIO = 3;

type HitSortDir ="asc" |"desc" | null;

function HitRatioCell({ row }: { row: HitRatioRow | undefined }) {
 if (!row || row.closed_jobs === 0) {
 return <span className="text-xs text-muted-foreground">—</span>;
 }
 if (row.closed_jobs < MIN_CLOSED_FOR_RATIO) {
 return (
 <span
 className="text-xs text-muted-foreground"
 title={`Za mało danych (min. ${MIN_CLOSED_FOR_RATIO} zamkniętych). ${row.filled_jobs} z ${row.closed_jobs}.`}
 >
 {row.filled_jobs} / {row.closed_jobs}
 </span>
 );
 }
 // Color bands — >=50% zielony, 20-49% amber, <20% czerwony
 const tone =
 row.hit_ratio >= 50
 ?"bg-[#dcfce7] text-[#166534]"
 : row.hit_ratio >= 20
 ?"bg-[#fef3c7] text-[#92400e]"
 :"bg-[#fee2e2] text-[#991b1b]";
 return (
 <span
 className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${tone}`}
 title={`${row.filled_jobs} z ${row.closed_jobs} zamkniętych · ${row.placements} zatrudnień`}
 >
 {row.hit_ratio.toFixed(1)}%
 </span>
 );
}

export function ClientsListV2() {
 const [search, setSearch] = useState("");
 const [page, setPage] = useState(1);
 const [showAdd, setShowAdd] = useState(false);
 const [toast, setToast] = useState<string | null>(null);
 const [hitSort, setHitSort] = useState<HitSortDir>(null);

 // Bramka „Nowy klient" = POST /api/clients (TacPlus). Ta sama capability
 // steruje przyciskiem w nagłówku i akcją w pustym stanie — wcześniej empty
 // state był nieobramkowany i rekruter dostawał tam „Dodaj pierwszego"
 // prowadzące w 403 (audyt F-19).
 const canCreateClient = useCapability("client.create");

 // Do zapytania idzie wartość zdebouncowana, do inputa surowa — inaczej każde
 // naciśnięcie klawisza wysyłało request i przerzucało tabelę w stan ładowania.
 const debouncedSearch = useDebouncedValue(search, 300);

 const { data, isLoading, isError, error, refetch } = useQuery({
 queryKey: ["clients-v2", debouncedSearch, page],
 queryFn: () =>
 api
 .get("/api/clients", {
 params: { q: debouncedSearch || undefined, page, page_size: 50 },
 })
 .then((r) => r.data),
 // Poprzednia strona wyników zostaje na ekranie do czasu przyjścia nowej —
 // bez tego lista migocze pustym stanem ładowania przy każdej zmianie filtra.
 placeholderData: keepPreviousData,
 });

 // Hit ratio per client (12m) — joined by client_id on render.
 // RBAC: admin/delivery_lead/tac/HoR. Recruiter/sourcer see undefined →"—".
 const { data: ratioData } = useQuery<HitRatioResponse>({
 queryKey: ["clients-hit-ratio","year"],
 queryFn: () =>
 api
 .get("/api/reports/clients", { params: { period: "year", min_closed: 0 } })
 .then((r) => r.data),
 staleTime: 5 * 60 * 1000, // backend cache is 5min, match it
 retry: false, // 403 for recruiters — just hide the column data
 });

 const ratioByClient = useMemo(() => {
 const map = new Map<number, HitRatioRow>();
 ratioData?.clients.forEach((r) => map.set(r.client_id, r));
 return map;
 }, [ratioData]);

 const rawItems: ClientRow[] = data?.items ?? [];
 const items = useMemo(() => {
 if (!hitSort) return rawItems;
 // Client-side sort by hit_ratio. Clients without data go to the end.
 const withRatio: Array<{ c: ClientRow; r?: HitRatioRow }> = rawItems.map((c) => ({
 c,
 r: ratioByClient.get(c.id),
 }));
 withRatio.sort((a, b) => {
 const aHas = a.r && a.r.closed_jobs >= MIN_CLOSED_FOR_RATIO;
 const bHas = b.r && b.r.closed_jobs >= MIN_CLOSED_FOR_RATIO;
 if (!aHas && !bHas) return 0;
 if (!aHas) return 1;
 if (!bHas) return -1;
 const diff = (a.r!.hit_ratio ?? 0) - (b.r!.hit_ratio ?? 0);
 return hitSort === "asc" ? diff : -diff;
 });
 return withRatio.map((x) => x.c);
 }, [rawItems, hitSort, ratioByClient]);
 const total = data?.total ?? 0;
 const pageSize = data?.page_size ?? 50;
 const totalPages = Math.max(1, Math.ceil(total / pageSize));

 // 403/404/5xx NIE mogą renderować się jako pusta lista (audyt F-20).
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

 const toggleHitSort = () =>
 setHitSort((prev) => (prev === "desc" ?"asc" : prev === "asc" ? null : "desc"));

 const onAdded = (msg: string) => {
 setShowAdd(false);
 setToast(msg);
 setTimeout(() => setToast(null), 3000);
 };

 return (
 <div className="max-w-[1400px] mx-auto space-y-4">
 {/* Header */}
 <div className="flex items-end justify-between flex-wrap gap-3">
 <div>
 <p className="text-xs font-semibold uppercase tracking-eyebrow text-primary">
 Delivery · Klienci
 </p>
 <h1 className="font-semibold text-3xl font-extrabold tracking-heading-tight text-foreground mt-1">
 Klienci
 </h1>
 <p className="text-sm text-muted-foreground mt-1" aria-live="polite">
 {isLoading
 ?"Ładowanie…"
 : failed
 ?"Nie udało się pobrać listy"
 : `${total} firm w portfelu`}
 </p>
 </div>
 {/* Capability `client.create` = backendowy TacPlus. Świadomie NIE ranga:
    head_of_recruitment (ROLE_RANK 4.5 > tac) przechodził przez hasMinRole,
    a backend firm mu zakładać nie pozwala. */}
 {canCreateClient && (
 <Button size="sm" variant="primary" onClick={() => setShowAdd(true)}>
 <Plus className="h-4 w-4" /> Nowy klient
 </Button>
 )}
 </div>

 {/* Search */}
 <div className="max-w-md">
 <Input
 leadingIcon={<Search className="h-4 w-4" />}
 placeholder="Szukaj po nazwie firmy, branży, emailu…"
 value={search}
 onChange={(e) => {
 setSearch(e.target.value);
 setPage(1);
 }}
 />
 </div>

 {/* Table */}
 <Table density="cozy">
 <TableHeader>
 <TableRow>
 <TableHead>Firma</TableHead>
 <TableHead>Branża</TableHead>
 <TableHead>Status</TableHead>
 <TableHead>
 <button
 onClick={toggleHitSort}
 className="inline-flex items-center gap-1 text-inherit font-inherit cursor-pointer select-none hover:opacity-80"
 title="Hit ratio = % zamkniętych zapytań z co najmniej jednym zatrudnieniem (ostatnie 12 mies.)"
 >
 Hit ratio
 {hitSort === "desc" && <ArrowDown className="h-3.5 w-3.5" />}
 {hitSort === "asc" && <ArrowUp className="h-3.5 w-3.5" />}
 </button>
 </TableHead>
 <TableHead>NDA</TableHead>
 <TableHead>Dodano</TableHead>
 </TableRow>
 </TableHeader>
 <TableBody>
 {viewState === "loading" ? (
 <TableRow>
 <TableCell colSpan={7} className="text-center py-10 text-muted-foreground">
 Ładowanie…
 </TableCell>
 </TableRow>
 ) : failed ? (
 <TableRow>
 <TableCell colSpan={7} className="p-0">
 <QueryStateNotice
 state={viewState as "forbidden" | "not_found" | "error"}
 className="border-0"
 description={
 viewState === "forbidden"
 ?"Twoja rola nie ma dostępu do bazy klientów. Lista NIE jest pusta — poproś administratora o uprawnienia."
 : undefined
 }
 onRetry={() => void refetch()}
 />
 </TableCell>
 </TableRow>
 ) : viewState === "empty" ? (
 <TableRow>
 <TableCell colSpan={7} className="text-center py-10">
 <Building2 className="h-10 w-10 mx-auto text-muted-foreground mb-2 opacity-40" />
 <p className="text-sm text-muted-foreground">
 Brak klientów.{" "}
 {canCreateClient && (
 <>
 <button
 onClick={() => setShowAdd(true)}
 className="text-primary hover:underline"
 >
 Dodaj pierwszego
 </button>
 .
 </>
 )}
 </p>
 </TableCell>
 </TableRow>
 ) : (
 items.map((c) => {
 const initials = c.name
 .split(/\s+/)
 .map((w) => w[0])
 .slice(0, 2)
 .join("")
 .toUpperCase();
 return (
 <TableRow key={c.id} interactive>
 <TableCell>
 <Link href={`/clients/${c.id}`} className="flex items-center gap-3">
 <Avatar size="sm">
 <AvatarFallback>{initials}</AvatarFallback>
 </Avatar>
 <span className="font-medium text-foreground">{c.name}</span>
 </Link>
 </TableCell>
 <TableCell>{c.industry ??"—"}</TableCell>
 <TableCell>
 {c.status ? (
 <Badge size="sm" variant={STATUS_VARIANT[c.status] ??"neutral"}>
 {c.status}
 </Badge>
 ) : (
 <span className="text-xs text-muted-foreground">—</span>
 )}
 </TableCell>
 <TableCell>
 <HitRatioCell row={ratioByClient.get(c.id)} />
 </TableCell>
 <TableCell>
 {c.nda_signed ? (
 <span className="inline-flex items-center gap-1 text-xs text-[#1d5e31]">
 <ShieldCheck className="h-3.5 w-3.5" /> Podpisana
 </span>
 ) : (
 <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
 <Shield className="h-3.5 w-3.5" /> Brak
 </span>
 )}
 </TableCell>
 <TableCell className="text-xs text-muted-foreground">
 {c.created_at ? formatRelativeTime(c.created_at) : "—"}
 </TableCell>
 </TableRow>
 );
 })
 )}
 </TableBody>
 </Table>

 {/* Pagination */}
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

 {showAdd && <AddClientModal onClose={() => setShowAdd(false)} onSuccess={onAdded} />}
 {toast && (
 <div className="fixed bottom-4 right-4 z-9999 px-4 py-3 rounded-lg shadow-md text-sm bg-card text-foreground">
 {toast}
 </div>
 )}
 </div>
 );
}
