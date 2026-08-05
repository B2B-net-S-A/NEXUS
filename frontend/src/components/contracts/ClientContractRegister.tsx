"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Calendar, Clock, Download, FileText, Pencil, Plus } from "lucide-react";
import api, { contractsApi } from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { getAccessToken } from "@/lib/session";
import { useAuthStore, hasRole } from "@/store/auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FilterBar } from "@/components/ds/FilterBar";
import { MultiSelectFilter } from "@/components/v2/filters/MultiSelectFilter";
import {
  CONTRACT_STATUS_OPTIONS,
  type ContractStatusValue,
} from "@/lib/filter-options";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  CONTRACT_STATUS_LABEL,
  CONTRACT_STATUS_VARIANT,
  ENGAGEMENT_MODEL_LABEL,
  PROLONGATION_LABEL,
  PROLONGATION_OPTIONS,
  PROLONGATION_VARIANT,
  type ProlongationStatus,
  type RegisterContractRow,
} from "@/lib/contract-register";
import { ContractRegisterDialog } from "./ContractRegisterDialog";

const PROLONGATION_TEXT_CLASS: Record<string, string> = {
  soft: "text-muted-foreground",
  success: "text-[#1d5e31]",
  warning: "text-amber-700",
  danger: "text-[#6b1120]",
  neutral: "text-foreground",
};

const PROLONGATION_DOT_CLASS: Record<string, string> = {
  soft: "bg-muted-foreground/50",
  success: "bg-[#1d5e31]",
  warning: "bg-amber-600",
  danger: "bg-[#6b1120]",
  neutral: "bg-foreground",
};

/** Liczba kontraktów na stronę w rejestrze klienta. */
const PAGE_SIZE = 50;

interface RegisterResponse {
  items: RegisterContractRow[];
  total: number;
  page: number;
  page_size: number;
}

/** Klucz React Query rejestru — współdzielony przez listę i optimistic update
 * prolongaty. Sygnatura filtrów (status + okres) jest częścią klucza, więc
 * optimistic update trafia dokładnie w cache aktualnie widocznej listy. */
type RegisterQueryKey = readonly [
  "client-register",
  number, // clientId
  number, // page
  string, // search
  string, // statusFilter.join(",")
  string, // periodFrom
  string, // periodTo
];

/** Inline-editowalny status przedłużenia (Select) lub read-only Badge. */
function ProlongationCell({
  row,
  queryKey,
  canEdit,
}: {
  row: RegisterContractRow;
  queryKey: RegisterQueryKey;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (value: ProlongationStatus) =>
      contractsApi.update(row.id, { prolongation_status: value }),
    onMutate: async (value) => {
      await queryClient.cancelQueries({ queryKey });
      const prev = queryClient.getQueryData<RegisterResponse>(queryKey);
      queryClient.setQueryData<RegisterResponse>(queryKey, (old) =>
        old
          ? {
              ...old,
              items: old.items.map((it) =>
                it.id === row.id ? { ...it, prolongation_status: value } : it,
              ),
            }
          : old,
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(queryKey, ctx.prev);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey });
    },
  });

  const variant = PROLONGATION_VARIANT[row.prolongation_status] ?? "soft";

  if (!canEdit) {
    return (
      <Badge size="sm" variant={variant}>
        {PROLONGATION_LABEL[row.prolongation_status] ?? row.prolongation_status}
      </Badge>
    );
  }

  return (
    <Select
      value={row.prolongation_status}
      onValueChange={(v) => mutation.mutate(v as ProlongationStatus)}
    >
      <SelectTrigger
        className={cn(
          "h-8 w-[150px] font-medium",
          PROLONGATION_TEXT_CLASS[variant],
        )}
      >
        <span className="flex items-center gap-2">
          <span
            className={cn(
              "h-2 w-2 rounded-full shrink-0",
              PROLONGATION_DOT_CLASS[variant],
            )}
          />
          <SelectValue />
        </span>
      </SelectTrigger>
      <SelectContent>
        {PROLONGATION_OPTIONS.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Komórka „Okres / Pula godzin" — różna wg engagement_model. */
function PeriodCell({ row }: { row: RegisterContractRow }) {
  if (row.engagement_model === "hours_pool") {
    const total = row.hours_pool_total ?? 0;
    const consumed = row.hours_pool_consumed ?? 0;
    const remaining = row.hours_pool_remaining ?? total - consumed;
    const pct = row.hours_pool_usage_pct ?? (total ? (consumed / total) * 100 : 0);
    const over = pct > 100;
    return (
      <div className="min-w-[160px]">
        <div className="flex items-center gap-1 text-xs text-foreground">
          <Clock className="h-3 w-3 shrink-0" />
          <span className="font-medium">{consumed}</span>
          <span className="text-muted-foreground">/ {total} h</span>
          <span
            className={cn(
              "ml-1 tabular-nums",
              over ? "text-destructive font-semibold" : "text-muted-foreground",
            )}
          >
            ({Math.round(pct)}%)
          </span>
        </div>
        <div className="mt-1 h-1.5 w-full rounded-full bg-muted overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full",
              over ? "bg-destructive" : "bg-primary",
            )}
            style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
          />
        </div>
        <div className="mt-0.5 text-[11px] text-muted-foreground">
          {remaining >= 0
            ? `${remaining} h pozostało`
            : `${Math.abs(remaining)} h ponad budżet`}
        </div>
      </div>
    );
  }
  // time_based
  return (
    <div className="min-w-[120px]">
      <div className="flex items-center gap-1 text-xs text-foreground">
        <Calendar className="h-3 w-3 shrink-0" />
        {row.start_date ? formatDate(row.start_date) : "—"}
      </div>
      <div className="text-xs text-muted-foreground">
        {row.end_date ? `→ ${formatDate(row.end_date)}` : "bezterminowo"}
      </div>
    </div>
  );
}

export function ClientContractRegister({
  clientId,
  clientName,
}: {
  clientId: number;
  clientName?: string;
}) {
  const user = useAuthStore((s) => s.user);
  const canEdit = hasRole(user, "admin", "delivery_lead", "tac");

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<RegisterContractRow | null>(null);
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput.trim(), 300);
  // Filtry łączone logiką AND (server-side): status (multi) + „Okres" (overlap).
  const [statusFilter, setStatusFilter] = useState<ContractStatusValue[]>([]);
  const [periodFrom, setPeriodFrom] = useState("");
  const [periodTo, setPeriodTo] = useState("");
  const [exporting, setExporting] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  // Każda zmiana filtra (fraza, status, okres) cofa do pierwszej strony wyników,
  // inaczej można utknąć na stronie N, której przefiltrowany wynik już nie ma.
  useEffect(() => {
    setPage(1);
  }, [search, statusFilter, periodFrom, periodTo]);

  const statusKey = statusFilter.join(",");
  const queryKey: RegisterQueryKey = [
    "client-register",
    clientId,
    page,
    search,
    statusKey,
    periodFrom,
    periodTo,
  ];
  const { data, isLoading, isFetching } = useQuery({
    queryKey,
    queryFn: () =>
      api
        .get<RegisterResponse>("/api/contracts", {
          params: {
            client_id: clientId,
            page,
            page_size: PAGE_SIZE,
            q: search || undefined,
            status: statusFilter.length ? statusFilter : undefined,
            period_from: periodFrom || undefined,
            period_to: periodTo || undefined,
          },
          // Powtarzany `status` jako status=a&status=b (backend: list[ContractStatus]).
          paramsSerializer: { indexes: null },
        })
        .then((r) => r.data),
    placeholderData: keepPreviousData,
  });

  const hasActiveFilters =
    statusFilter.length > 0 || Boolean(periodFrom) || Boolean(periodTo);

  const flashToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3500);
  };

  const clearFilters = () => {
    setStatusFilter([]);
    setPeriodFrom("");
    setPeriodTo("");
  };

  // Eksport do Excela — zawsze zawężony do WYBRANEGO klienta (ten komponent
  // renderuje się tylko z klientem) i honoruje aktualne filtry, więc plik
  // odpowiada temu, co widać na liście („eksportuj to, co widzę"). Fraza to
  // wartość zdebouncowana (`search`) — ta sama, którą karmiona jest lista.
  const doExport = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      const params = new URLSearchParams();
      params.set("client_id", String(clientId));
      if (search) params.set("q", search);
      statusFilter.forEach((s) => params.append("status", s));
      if (periodFrom) params.set("period_from", periodFrom);
      if (periodTo) params.set("period_to", periodTo);
      const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
      const token = getAccessToken();
      const res = await fetch(
        `${apiBase}/api/contracts/register/export?${params}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      );
      if (!res.ok) {
        flashToast("Eksport nie powiódł się.");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const slug =
        (clientName ?? "klient")
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-+|-+$/g, "") || "klient";
      a.download = `rejestr-kontraktow-${slug}-${new Date()
        .toISOString()
        .slice(0, 10)}.xlsx`;
      // Anchor musi być w DOM, by a.click() zadziałał we wszystkich przeglądarkach;
      // obiekt URL zwalniany leniwie, żeby duże pliki zdążyły się pobrać.
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } finally {
      setExporting(false);
    }
  };

  const items = useMemo(() => data?.items ?? [], [data]);
  const total = data?.total ?? 0;
  const pageSize = data?.page_size ?? PAGE_SIZE;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const resolvedName = clientName ?? items[0]?.candidate_name ?? undefined;

  const openNew = () => {
    setEditing(null);
    setDialogOpen(true);
  };
  const openEdit = (row: RegisterContractRow) => {
    setEditing(row);
    setDialogOpen(true);
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-eyebrow text-primary">
            Delivery · Kontrakty klienta
          </p>
          <h1 className="font-semibold text-3xl font-extrabold tracking-heading-tight text-foreground mt-1">
            {clientName ?? "Kontrakty"}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {isLoading
              ? "Ładowanie…"
              : `${total} kontrakt${total === 1 ? "" : total > 1 && total < 5 ? "y" : "ów"}`}
          </p>
        </div>
        {canEdit && (
          <Button size="sm" variant="primary" onClick={openNew}>
            <Plus className="h-4 w-4" /> Nowy kontrakt
          </Button>
        )}
      </div>

      {/* Panel filtrów (logika AND, server-side) + eksport. Wyszukiwarka filtruje
          po nazwisku konsultanta; „Status" i „Okres" (overlap) zawężają listę
          w czasie rzeczywistym. Eksport bierze dokładnie to, co widać na liście. */}
      <FilterBar
        search={{
          value: searchInput,
          onChange: setSearchInput,
          placeholder: "Szukaj po nazwisku konsultanta…",
        }}
        filters={
          <>
            <MultiSelectFilter<ContractStatusValue>
              value={statusFilter}
              onChange={setStatusFilter}
              options={CONTRACT_STATUS_OPTIONS}
              placeholder="Wszystkie statusy"
              searchPlaceholder="Szukaj statusu…"
              triggerWidthClass="w-[170px]"
              triggerLabel={(n) =>
                n === 1
                  ? (CONTRACT_STATUS_OPTIONS.find(
                      (o) => o.value === statusFilter[0],
                    )?.label ?? "Status")
                  : `Status: ${n}`
              }
            />
            <div
              className="flex items-center gap-1.5"
              role="group"
              aria-label="Okres (zakres dat)"
            >
              <Input
                type="date"
                aria-label="Okres od"
                value={periodFrom}
                onChange={(e) => setPeriodFrom(e.target.value)}
                className="h-9 w-[150px]"
              />
              <span className="text-sm text-muted-foreground" aria-hidden>
                –
              </span>
              <Input
                type="date"
                aria-label="Okres do"
                value={periodTo}
                onChange={(e) => setPeriodTo(e.target.value)}
                className="h-9 w-[150px]"
              />
            </div>
            {hasActiveFilters && (
              <Button size="sm" variant="ghost" onClick={clearFilters}>
                Wyczyść
              </Button>
            )}
          </>
        }
        actions={
          <Button
            size="sm"
            variant="outline"
            onClick={doExport}
            disabled={exporting}
          >
            <Download className="h-4 w-4" />
            {exporting ? "Eksportuję…" : "Eksportuj do Excela"}
          </Button>
        }
      />

      {/* Table */}
      <Table density="cozy">
        <TableHeader>
          <TableRow>
            <TableHead>Nr projektu</TableHead>
            <TableHead>Projekt</TableHead>
            <TableHead>Konsultant</TableHead>
            <TableHead>Model</TableHead>
            <TableHead>Okres / Pula godzin</TableHead>
            <TableHead>Prolongata</TableHead>
            <TableHead>Status</TableHead>
            {canEdit && <TableHead className="w-10" />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow>
              <TableCell
                colSpan={canEdit ? 8 : 7}
                className="text-center py-10 text-muted-foreground"
              >
                Ładowanie…
              </TableCell>
            </TableRow>
          ) : items.length === 0 ? (
            <TableRow>
              <TableCell colSpan={canEdit ? 8 : 7} className="text-center py-12">
                <FileText className="h-10 w-10 mx-auto text-muted-foreground mb-2 opacity-40" />
                <p className="text-sm text-muted-foreground">
                  {search
                    ? `Brak konsultantów pasujących do „${search}”.`
                    : hasActiveFilters
                      ? "Brak kontraktów pasujących do wybranych filtrów."
                      : "Brak kontraktów dla tego klienta."}
                </p>
                {canEdit && !search && !hasActiveFilters && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="mt-3"
                    onClick={openNew}
                  >
                    <Plus className="h-4 w-4" /> Dodaj pierwszy kontrakt
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ) : (
            items.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-mono text-xs">
                  {row.project_code ? (
                    <span className="text-foreground">{row.project_code}</span>
                  ) : (
                    <span className="text-muted-foreground">#{row.id}</span>
                  )}
                </TableCell>
                <TableCell className="max-w-[220px]">
                  <span className="text-sm text-foreground truncate block">
                    {row.project_name ?? "—"}
                  </span>
                </TableCell>
                <TableCell>
                  <Link
                    href={`/contracts/${row.id}`}
                    className="font-medium text-foreground hover:text-primary"
                  >
                    {row.candidate_name ?? `#${row.candidate_id}`}
                  </Link>
                </TableCell>
                <TableCell>
                  <Badge
                    size="sm"
                    variant={
                      row.engagement_model === "hours_pool" ? "warning" : "soft"
                    }
                  >
                    {ENGAGEMENT_MODEL_LABEL[row.engagement_model] ??
                      row.engagement_model}
                  </Badge>
                </TableCell>
                <TableCell>
                  <PeriodCell row={row} />
                </TableCell>
                <TableCell>
                  <ProlongationCell
                    row={row}
                    queryKey={queryKey}
                    canEdit={canEdit}
                  />
                </TableCell>
                <TableCell>
                  {row.status ? (
                    <Badge
                      size="sm"
                      variant={CONTRACT_STATUS_VARIANT[row.status] ?? "neutral"}
                    >
                      {CONTRACT_STATUS_LABEL[row.status] ?? row.status}
                    </Badge>
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </TableCell>
                {canEdit && (
                  <TableCell>
                    <Button
                      size="icon"
                      variant="ghost"
                      title="Edytuj kontrakt"
                      onClick={() => openEdit(row)}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                  </TableCell>
                )}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      {/* Paginacja — widoczna tylko gdy wyników jest więcej niż jedna strona. */}
      {!isLoading && totalPages > 1 && (
        <div className="flex items-center justify-between gap-3 text-sm">
          <span className="text-muted-foreground">
            Strona <strong className="text-foreground">{page}</strong> z{" "}
            {totalPages}
            {isFetching && <span className="ml-2 opacity-60">· ładowanie…</span>}
          </span>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
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

      {toast && (
        <div className="fixed bottom-24 right-4 z-9999 rounded-lg bg-card px-4 py-3 text-sm text-foreground shadow-md">
          {toast}
        </div>
      )}

      {canEdit && (
        <ContractRegisterDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          clientId={clientId}
          clientName={resolvedName ?? clientName}
          contract={editing}
          onSaved={() => setEditing(null)}
        />
      )}
    </div>
  );
}
