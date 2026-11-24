"use client";

import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  Building2,
  CheckCircle2,
  Download,
  PauseCircle,
  Plus,
  Search,
  SearchX,
  Wrench,
  X,
} from "lucide-react";

import {
  clientListApi,
  type ClientListItem,
  type ClientListState,
} from "@/lib/api";
import { AddClientModal } from "@/components/AppShell";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import {
  AttentionCell,
  CONTRACT_ENDING_DAYS,
  consultantAttention,
  contractAttention,
  daysUntil,
  useClientAttention,
  type AttentionItem,
} from "@/components/clients/ClientAttention";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCapability } from "@/hooks/useCapability";
import { CALM_EMPTY, CALM_HEAD, CALM_SUBLINE } from "@/lib/calm-table";
import { isClientPickerQueryKey } from "@/lib/client-selection";
import {
  CLIENTS_MINE_ROLES,
  clientsMineToggleAvailable,
  resolveClientsMine,
} from "@/lib/clients-workspace";
import { countPl } from "@/lib/plural-pl";
import { getAuthenticatedRequestHeaders } from "@/lib/session";
import { useUrlWriter } from "@/lib/url-selection";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
import { httpStatusFromError, resolveViewState } from "@/lib/view-state";
import { WIDE_HIDDEN, WIDE_ONLY_CELL, WIDE_TABLE_CONTAINER } from "@/lib/wide-table";
import { hasRole, mayExportFiles, useAuthStore } from "@/store/auth";

/**
 * Lista „Klienci” (makieta 19.11.2026, wariant A, decyzja Artura).
 *
 * Jeden wiersz na klienta i stan liczony z faktów zamiast zakładek portfela
 * ustawianych z manifestu albo ręcznym „Przenieś” — tamtych nikt nie
 * rozumiał („czym są klienci relacyjni, czym jest »ręcznie«”), a Tauron
 * z dwiema otwartymi rekrutacjami stał w „Nieaktywnych”. Zakresy, zakładki
 * portfela, ręczne daty i czyszczenie nieaktywnych są w „Porządkach
 * portfela” (`/clients/portfolio`, dawna lista, dla administratora).
 */

const PAGE_SIZE = 50;
const STATES_TOUR = "clients.states"; // data-tour="clients.states"
const STATE_ORDER: ClientListState[] = ["working", "idle", "archive"];
const EMPTY_COUNTS: Record<ClientListState, number> = { working: 0, idle: 0, archive: 0 };

const STATE_META: Record<
  ClientListState,
  { title: string; short: string; definition: string; icon: typeof CheckCircle2 }
> = {
  working: {
    title: "Współpracujemy",
    short: "Współpracujemy",
    definition:
      "Pracuje u nich ktoś od nas, ktoś zaczyna albo trwa rekrutacja. Stan liczy się sam, bez przenoszenia.",
    icon: CheckCircle2,
  },
  idle: {
    title: "Bez bieżącej pracy",
    short: "Bez bieżącej pracy",
    definition:
      "Mamy umowę albo relację, ale dziś nikt od nas u nich nie pracuje i nie ma otwartej rekrutacji.",
    icon: PauseCircle,
  },
  archive: {
    title: "Archiwum",
    short: "Archiwum",
    definition: "Dawni klienci: bez naszych ludzi, rekrutacji i bieżącej relacji.",
    icon: Archive,
  },
};

const EMPTY_CELL = <span className={CALM_EMPTY}>—</span>;

function parseState(value: string | null): ClientListState {
  return STATE_ORDER.includes(value as ClientListState) ? (value as ClientListState) : "working";
}

function parsePage(value: string | null): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 1;
}

function formatDate(value: string | null): string {
  const match = value ? /^(\d{4})-(\d{2})-(\d{2})/.exec(value) : null;
  return match ? `${match[3]}.${match[2]}.${match[1]}` : "—";
}

function initialsFor(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

/** „DL: Martyna Witkowska +1” — główny Delivery Lead pierwszy (jak w nagłówku profilu). */
export function deliveryLeadLabel(leads: ClientListItem["delivery_leads"]): string | null {
  if (leads.length === 0) return null;
  const head = leads.find((lead) => lead.is_head) ?? leads[0];
  return leads.length > 1 ? `${head.name} +${leads.length - 1}` : head.name;
}

/** Znaczniki wiersza: umowa ramowa, konsultanci, raporty i relacje — w tej kolejności. */
export function rowAttention(
  item: ClientListItem,
  reportsAndRelationships: readonly AttentionItem[],
): AttentionItem[] {
  const contract = item.has_framework_period
    ? contractAttention({
        client_id: item.client_id,
        scope_id: item.client_id,
        expiry_date: item.framework_expiry_date,
      })
    : null;
  return [
    ...(contract ? [contract] : []),
    ...(item.state === "working" ? consultantAttention(item) : []),
    ...reportsAndRelationships,
  ];
}

export function ClientsList() {
  const urlWriter = useUrlWriter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);

  const urlState = parseState(searchParams.get("state"));
  const urlSearch = searchParams.get("q") ?? "";
  const urlPage = parsePage(searchParams.get("page"));
  // „Moi / Wszyscy” jak dotąd: tylko osoby z przypisaniem klienta (DL, TAC).
  const mineAvailable = clientsMineToggleAvailable(
    hasRole(user, ...CLIENTS_MINE_ROLES),
    user?.delivery_client_scope,
  );
  const mine = resolveClientsMine(mineAvailable, searchParams.get("mine"));

  const [state, setState] = useState<ClientListState>(urlState);
  const [search, setSearch] = useState(urlSearch);
  const [querySearch, setQuerySearch] = useState(urlSearch.trim());
  const [page, setPage] = useState(urlPage);
  const [counts, setCounts] = useState<Record<ClientListState, number>>(EMPTY_COUNTS);
  const [showAdd, setShowAdd] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const didCanonicalizeUrl = useRef(false);
  const searchSyncTarget = useRef<string | null>(null);

  useEffect(() => setState(urlState), [urlState]);
  useEffect(() => {
    searchSyncTarget.current = urlSearch;
    setSearch(urlSearch);
    setQuerySearch(urlSearch.trim());
  }, [urlSearch]);
  useEffect(() => setPage(urlPage), [urlPage]);

  const writeUrl = useCallback(
    (next: { state: ClientListState; q: string; page: number }, mode: "push" | "replace") => {
      const params = new URLSearchParams(searchParams.toString());
      // Dawne adresy (`?category=…`, `?view=…`) otwierają tę listę — nie wożą ich dalej.
      params.delete("category");
      params.delete("view");
      params.set("state", next.state);
      if (next.q.trim()) params.set("q", next.q.trim());
      else params.delete("q");
      params.set("page", String(next.page));
      const href = `${pathname || "/clients"}?${params.toString()}`;
      if (mode === "push") urlWriter.pushUrl(href);
      else urlWriter.replaceUrl(href);
    },
    [pathname, urlWriter, searchParams],
  );

  // Adres kanoniczny także dla stanu domyślnego (da się go skopiować).
  useEffect(() => {
    if (didCanonicalizeUrl.current) return;
    didCanonicalizeUrl.current = true;
    if (
      searchParams.get("state") === state &&
      searchParams.get("page") === String(page) &&
      !searchParams.has("category") &&
      !searchParams.has("view")
    ) {
      return;
    }
    writeUrl({ state, q: urlSearch, page }, "replace");
  }, [state, page, writeUrl, searchParams, urlSearch]);

  const debouncedSearch = useDebouncedValue(search, 300);
  const previousDebouncedSearch = useRef(debouncedSearch);
  useEffect(() => {
    if (previousDebouncedSearch.current === debouncedSearch) return;
    previousDebouncedSearch.current = debouncedSearch;
    const normalized = debouncedSearch.trim();
    if (searchSyncTarget.current !== null) {
      if (normalized === searchSyncTarget.current.trim()) searchSyncTarget.current = null;
      return;
    }
    setQuerySearch(normalized);
    if (normalized === urlSearch) return;
    writeUrl({ state, q: normalized, page: 1 }, "replace");
  }, [state, debouncedSearch, writeUrl, urlSearch]);

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["clients-directory", "clients", state, querySearch, page, mine],
    queryFn: ({ signal }) =>
      clientListApi
        .list(
          {
            state,
            q: querySearch || undefined,
            page,
            page_size: PAGE_SIZE,
            ...(mine ? { mine: true } : {}),
          },
          signal,
        )
        .then((response) => response.data),
    placeholderData: (previousData, previousQuery) => {
      const key = previousQuery?.queryKey;
      return key?.[2] === state && key?.[3] === querySearch && key?.[5] === mine
        ? previousData
        : undefined;
    },
  });

  useEffect(() => {
    if (data?.state_counts) setCounts(data.state_counts);
  }, [data?.state_counts]);

  const canCreateClient = useCapability("client.create");
  const canManagePortfolio = useCapability("client.portfolio.manage");
  const attention = useClientAttention();

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageSize = data?.page_size ?? PAGE_SIZE;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const searching = querySearch.length > 0;
  // Stany „Bez bieżącej pracy” i „Archiwum” mają z definicji zero ludzi,
  // rekrutacji i marży — kolumny z samymi zerami tylko zabierałyby miejsce.
  const showNumbers = searching || state === "working";
  const showMargin = showNumbers && Boolean(data?.amounts_visible);
  const columnCount = 3 + (showNumbers ? 2 : 0) + (showMargin ? 1 : 0);
  const viewState = resolveViewState({
    isLoading,
    isError,
    error,
    isEmpty: items.length === 0,
  });
  const failed = viewState === "forbidden" || viewState === "not_found" || viewState === "error";

  const selectState = (next: ClientListState) => {
    if (next === state && !searching) return;
    searchSyncTarget.current = null;
    setState(next);
    setSearch("");
    setQuerySearch("");
    setPage(1);
    writeUrl({ state: next, q: "", page: 1 }, "push");
  };

  const handleStateKeyDown = (event: KeyboardEvent<HTMLButtonElement>, current: ClientListState) => {
    const index = STATE_ORDER.indexOf(current);
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % STATE_ORDER.length;
    else if (event.key === "ArrowLeft") nextIndex = (index - 1 + STATE_ORDER.length) % STATE_ORDER.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = STATE_ORDER.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const next = STATE_ORDER[nextIndex];
    selectState(next);
    document.getElementById(`clients-state-${next}`)?.focus();
  };

  const selectMine = (next: boolean) => {
    if (next === mine) return;
    const params = new URLSearchParams(searchParams.toString());
    if (next === mineAvailable) params.delete("mine");
    else params.set("mine", next ? "1" : "0");
    params.set("page", "1");
    setPage(1);
    urlWriter.replaceUrl(`${pathname || "/clients"}?${params.toString()}`);
  };

  const goToPage = (next: number) => {
    setPage(next);
    writeUrl({ state, q: querySearch, page: next }, "push");
  };

  const clearSearch = () => {
    searchSyncTarget.current = null;
    setSearch("");
    setQuerySearch("");
    setPage(1);
    writeUrl({ state, q: "", page: 1 }, "replace");
  };

  const flash = (message: string, ms = 3500) => {
    setToast(message);
    setTimeout(() => setToast(null), ms);
  };

  const onAdded = (message: string) => {
    setShowAdd(false);
    flash(`${message} Klient jest w „Bez bieżącej pracy”, dopóki nie ruszy rekrutacja albo kontrakt.`, 5000);
    void queryClient.invalidateQueries({ queryKey: ["clients-directory"] });
    void queryClient.invalidateQueries({
      predicate: (query) => isClientPickerQueryKey(query.queryKey),
    });
  };

  // „Eksportuj to, co widzę”: ten sam stan i ta sama fraza co lista, bez stron.
  const doExport = async (format: "xlsx" | "csv") => {
    if (exporting) return;
    setExporting(true);
    try {
      const params = new URLSearchParams({ state, format });
      if (querySearch) params.set("q", querySearch);
      if (mine) params.set("mine", "true");
      const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
      const res = await fetch(`${apiBase}/api/clients/directory/clients/export?${params}`, {
        credentials: "include",
        headers: getAuthenticatedRequestHeaders(),
      });
      if (!res.ok) {
        flash("Eksport nie powiódł się. Spróbuj ponownie za chwilę.");
        return;
      }
      const truncated = res.headers.get("X-Export-Truncated") === "true";
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `klienci-${new Date().toISOString().slice(0, 10)}.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      if (truncated) flash("Wyeksportowano część listy — przekroczono limit wierszy.", 4500);
    } finally {
      setExporting(false);
    }
  };

  const headline = isLoading
    ? "Ładowanie klientów…"
    : failed
      ? "Nie udało się pobrać listy klientów"
      : searching
        ? `${countPl(total, "wynik", "wyniki", "wyników")} ze wszystkich klientów`
        : `${counts.working} współpracuje z nami teraz`;

  return (
    <div className="space-y-3">
      {/* Nagłówek zwarty: przy 1280 × 720 tabela ma się zacząć w górnych 60% okna. */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <h1 className="text-lg font-semibold text-foreground">Klienci</h1>
          <p className="text-xs text-muted-foreground" aria-live="polite">
            {headline}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {mayExportFiles(user) ? (
            <Popover>
              <PopoverTrigger asChild>
                <Button size="sm" variant="outline" disabled={exporting}>
                  <Download className="h-4 w-4" aria-hidden="true" />
                  {exporting ? "Eksportuję…" : "Eksport"}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-44 p-1">
                {(
                  [
                    ["xlsx", "Excel (.xlsx)"],
                    ["csv", "CSV"],
                  ] as const
                ).map(([format, label]) => (
                  <button
                    key={format}
                    type="button"
                    onClick={() => void doExport(format)}
                    className="block w-full rounded-md px-3 py-1.5 text-left text-sm hover:bg-primary/10"
                  >
                    {label}
                  </button>
                ))}
              </PopoverContent>
            </Popover>
          ) : null}
          {canCreateClient ? (
            <Button size="sm" variant="primary" onClick={() => setShowAdd(true)}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              Nowy klient
            </Button>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="Stan współpracy" className="flex flex-wrap items-center gap-1.5">
          {STATE_ORDER.map((itemState) => {
            const meta = STATE_META[itemState];
            const Icon = meta.icon;
            const selected = itemState === state && !searching;
            return (
              <button
                id={`clients-state-${itemState}`}
                key={itemState}
                type="button"
                role="tab"
                aria-label={`${meta.title}, ${countPl(counts[itemState], "klient", "klientów", "klientów")}`}
                title={meta.definition}
                aria-selected={selected}
                aria-controls="client-list-panel"
                tabIndex={itemState === state ? 0 : -1}
                onClick={() => selectState(itemState)}
                onKeyDown={(event) => handleStateKeyDown(event, itemState)}
                data-tour={itemState === "working" ? STATES_TOUR : undefined}
                className={cn(
                  "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors pointer-coarse:h-10",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  selected
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border bg-card text-muted-foreground hover:border-primary/50 hover:text-foreground",
                )}
              >
                <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                {meta.short}
                <span
                  className={cn(
                    "rounded-full px-1.5 text-[11px] font-semibold leading-5 tabular-nums",
                    selected ? "bg-primary text-primary-foreground" : "bg-muted text-foreground",
                  )}
                >
                  {counts[itemState]}
                </span>
              </button>
            );
          })}
        </div>
        {mineAvailable ? (
          <div
            role="radiogroup"
            aria-label="Zakres listy klientów"
            className="inline-flex h-8 items-center gap-0.5 rounded-md border border-border bg-muted/40 p-0.5"
          >
            {(
              [
                [true, "Moi klienci"],
                [false, "Wszyscy"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={label}
                type="button"
                role="radio"
                aria-checked={mine === value}
                onClick={() => selectMine(value)}
                className={cn(
                  "h-full rounded px-2.5 text-xs font-medium transition-colors",
                  mine === value
                    ? "bg-background text-foreground shadow-xs"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        ) : null}
        <div className="relative min-w-[220px] max-w-sm flex-1">
          <label htmlFor="client-list-search" className="sr-only">
            Szukaj klienta
          </label>
          <Input
            id="client-list-search"
            leadingIcon={<Search className="h-4 w-4" />}
            className={cn("h-8", search && "pr-10")}
            placeholder="Szukaj we wszystkich klientach: nazwa, branża"
            value={search}
            onChange={(event) => {
              searchSyncTarget.current = null;
              setSearch(event.target.value);
              setPage(1);
            }}
          />
          {search ? (
            <button
              type="button"
              onClick={clearSearch}
              className="absolute right-1 top-1/2 inline-flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:h-9 pointer-coarse:w-9"
              aria-label="Wyczyść wyszukiwanie"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          ) : null}
        </div>
      </div>
      <p className="text-xs text-muted-foreground" data-testid="client-state-definition">
        {searching
          ? "Wyniki ze wszystkich klientów; stan współpracy stoi pod nazwą."
          : STATE_META[state].definition}
      </p>

      <section
        id="client-list-panel"
        role="tabpanel"
        aria-labelledby={`clients-state-${state}`}
        aria-busy={isFetching}
      >
        <div className={WIDE_TABLE_CONTAINER}>
          <Table density="compact" className="min-w-[820px]">
            <TableHeader>
              <TableRow>
                <TableHead className={cn(CALM_HEAD, "sticky left-0 z-10 bg-background")}>Klient</TableHead>
                <TableHead className={cn(CALM_HEAD, WIDE_ONLY_CELL)}>Delivery Lead</TableHead>
                {showNumbers ? (
                  <>
                    <TableHead
                      className={cn(CALM_HEAD, "whitespace-nowrap text-right")}
                      title="Obecni konsultanci; „zaczyna” = umowa ze startem w przyszłości"
                    >
                      Nasi ludzie
                    </TableHead>
                    <TableHead className={cn(CALM_HEAD, "text-right")} title="Otwarte rekrutacje klienta">
                      Rekrutacje
                    </TableHead>
                  </>
                ) : null}
                {showMargin ? (
                  <TableHead
                    className={cn(CALM_HEAD, "text-right")}
                    title="Miesięczna marża obecnych konsultantów — ta sama liczba co „Aktywne MRR” w profilu klienta"
                  >
                    Marża / mc
                  </TableHead>
                ) : null}
                <TableHead className={CALM_HEAD}>Umowa ramowa</TableHead>
                <TableHead className={CALM_HEAD} data-tour="clients.attention">
                  Wymaga uwagi
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {viewState === "loading" ? (
                Array.from({ length: 5 }, (_, index) => (
                  <TableRow key={`client-skeleton-${index}`} className="h-[46px]">
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <Skeleton className="h-8 w-8 rounded-full" />
                        <div className="space-y-1.5">
                          <Skeleton className="h-4 w-40" />
                          <Skeleton className="h-3 w-24" />
                        </div>
                      </div>
                    </TableCell>
                    {Array.from({ length: columnCount - 1 }, (_, cellIndex) => (
                      <TableCell key={cellIndex}>
                        <Skeleton className="h-4 w-20" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : failed ? (
                <TableRow>
                  <TableCell colSpan={columnCount + 1} className="p-0">
                    <QueryStateNotice
                      state={viewState as "forbidden" | "not_found" | "error"}
                      className="border-0"
                      description={
                        viewState === "forbidden"
                          ? "Twoja rola nie ma dostępu do listy klientów. Dane nie są puste — poproś administratora o uprawnienia."
                          : viewState === "error" && httpStatusFromError(error) === undefined
                            ? "Nie udało się połączyć z serwerem. Sprawdź internet lub VPN i spróbuj ponownie."
                            : undefined
                      }
                      onRetry={viewState === "error" ? () => void refetch() : undefined}
                    />
                  </TableCell>
                </TableRow>
              ) : viewState === "empty" ? (
                <TableRow>
                  <TableCell colSpan={columnCount + 1} className="py-12 text-center">
                    <EmptyState
                      searching={searching}
                      mine={mine}
                      state={state}
                      onClearSearch={clearSearch}
                      onShowAll={() => selectMine(false)}
                    />
                  </TableCell>
                </TableRow>
              ) : (
                items.map((item) => {
                  const lead = deliveryLeadLabel(item.delivery_leads);
                  // DL na końcu: w szerokiej tabeli ma własną kolumnę i znika
                  // z drobnego druku bez wiszącej kropki.
                  const subline = [
                    searching ? STATE_META[item.state].short : null,
                    item.industry,
                    lead ? `DL: ${lead}` : null,
                  ].filter((part): part is string => Boolean(part));
                  return (
                    <TableRow key={item.client_id} interactive className="h-[46px]">
                      <TableCell className="sticky left-0 z-10 min-w-[200px] bg-card [tr:hover_&]:bg-[linear-gradient(hsl(var(--primary)/0.1),hsl(var(--primary)/0.1))]">
                        <Link
                          href={`/clients/${item.client_id}`}
                          data-tour="clients.list.row"
                          className="flex min-w-0 items-center gap-3 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <Avatar size="sm">
                            <AvatarFallback>{initialsFor(item.display_name)}</AvatarFallback>
                          </Avatar>
                          <span className="min-w-0">
                            <span className="block max-w-[240px] truncate font-medium text-foreground" title={item.display_name}>
                              {item.display_name}
                            </span>
                            {subline.length > 0 ? (
                              <span className={cn(CALM_SUBLINE, "max-w-[240px] truncate")} title={subline.join(" · ")}>
                                {subline.map((part, index) => (
                                  <span
                                    key={`${index}-${part}`}
                                    className={cn(lead && part === `DL: ${lead}` && WIDE_HIDDEN)}
                                  >
                                    {index > 0 ? <span aria-hidden="true"> · </span> : null}
                                    {part}
                                  </span>
                                ))}
                              </span>
                            ) : null}
                          </span>
                        </Link>
                      </TableCell>
                      <TableCell className={WIDE_ONLY_CELL}>{lead ?? EMPTY_CELL}</TableCell>
                      {showNumbers ? (
                        <>
                          <TableCell className="text-right tabular-nums" data-testid="client-people-cell">
                            {item.active_consultants > 0 || item.planned_consultants > 0 ? (
                              <span className="inline-flex flex-col items-end">
                                <span className="font-medium">{item.active_consultants}</span>
                                {item.planned_consultants > 0 ? (
                                  <span className={cn(CALM_SUBLINE, "whitespace-nowrap")}>+{item.planned_consultants} zaczyna</span>
                                ) : null}
                              </span>
                            ) : (
                              <span className={CALM_EMPTY}>0</span>
                            )}
                          </TableCell>
                          <TableCell className="text-right tabular-nums" data-testid="client-jobs-cell">
                            {item.open_jobs > 0 ? (
                              <Link
                                href={`/clients/${item.client_id}?tab=projekty`}
                                className="rounded-sm font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              >
                                {item.open_jobs}
                              </Link>
                            ) : (
                              <span className={CALM_EMPTY}>0</span>
                            )}
                          </TableCell>
                        </>
                      ) : null}
                      {showMargin ? (
                        <TableCell className="whitespace-nowrap text-right tabular-nums" data-testid="client-margin-cell">
                          <MarginValue item={item} />
                        </TableCell>
                      ) : null}
                      <TableCell className="whitespace-nowrap tabular-nums">
                        <FrameworkCell item={item} />
                      </TableCell>
                      <TableCell className="min-w-[200px]">
                        <AttentionCell
                          items={rowAttention(item, attention.byClient.get(item.client_id) ?? [])}
                          failed={attention.failed}
                        />
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </div>
      </section>

      {viewState === "ready" && total > pageSize ? (
        <nav
          className="flex flex-col gap-3 text-sm sm:flex-row sm:items-center sm:justify-between"
          aria-label="Paginacja klientów"
        >
          <span className="text-muted-foreground">
            Strona <strong className="text-foreground">{page}</strong> z {totalPages}
          </span>
          <div className="flex gap-2">
            <Button
              className="aria-disabled:pointer-events-none aria-disabled:opacity-50"
              size="sm"
              variant="outline"
              aria-disabled={page <= 1 || isFetching}
              onClick={() => {
                if (page > 1 && !isFetching) goToPage(page - 1);
              }}
            >
              Poprzednia
            </Button>
            <Button
              className="aria-disabled:pointer-events-none aria-disabled:opacity-50"
              size="sm"
              variant="outline"
              aria-disabled={page >= totalPages || isFetching}
              onClick={() => {
                if (page < totalPages && !isFetching) goToPage(page + 1);
              }}
            >
              Następna
            </Button>
          </div>
        </nav>
      ) : null}

      {canManagePortfolio ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3 text-xs text-muted-foreground">
          <span>
            Porządki portfela: zakładki i daty umów ustawione ręcznie
            {data ? ` (${data.manually_placed_count})` : ""}, przenoszenie zakresów i czyszczenie nieaktywnych.
          </span>
          <Button asChild size="sm" variant="quiet">
            <Link href="/clients/portfolio">
              <Wrench className="h-4 w-4" aria-hidden="true" />
              Otwórz porządki
            </Link>
          </Button>
        </div>
      ) : null}

      {showAdd ? (
        <AddClientModal
          onClose={() => setShowAdd(false)}
          onSuccess={onAdded}
          category={state === "archive" ? "inactive" : "active"}
        />
      ) : null}
      {toast ? (
        <div
          role="status"
          className="fixed bottom-4 right-4 z-[9999] rounded-lg bg-card px-4 py-3 text-sm text-foreground shadow-md"
        >
          {toast}
        </div>
      ) : null}
    </div>
  );
}

/** „197 588 zł” — marża miesięczna w pełnych złotych, jak „Aktywne MRR” profilu. */
export function formatWholePln(value: number): string {
  return `${new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 0 }).format(value)} zł`;
}

function MarginValue({ item }: { item: ClientListItem }) {
  if (item.monthly_margin === null) return EMPTY_CELL;
  if (item.active_consultants === 0 && item.monthly_margin === 0) return EMPTY_CELL;
  const incomplete = item.monthly_margin_unpriced > 0;
  return (
    <span
      className={cn("inline-flex flex-col items-end", item.monthly_margin < 0 && "text-destructive")}
      title={
        incomplete
          ? `Bez ${countPl(item.monthly_margin_unpriced, "kontraktu", "kontraktów", "kontraktów")} bez stawki — suma niepełna`
          : undefined
      }
    >
      <span className="font-medium">{formatWholePln(item.monthly_margin)}</span>
      {incomplete ? <span className={CALM_SUBLINE}>niepełna</span> : null}
    </span>
  );
}

function FrameworkCell({ item }: { item: ClientListItem }) {
  if (!item.has_framework_period) return EMPTY_CELL;
  const ending =
    item.framework_expiry_date !== null && daysUntil(item.framework_expiry_date) <= CONTRACT_ENDING_DAYS;
  const more = item.framework_count - 1;
  return (
    <span className="flex flex-col">
      <span className={cn(ending && "font-medium text-warning")}>
        {item.framework_expiry_date ? `do ${formatDate(item.framework_expiry_date)}` : "bezterminowa"}
      </span>
      {item.framework_effective_date || more > 0 ? (
        <span className={CALM_SUBLINE}>
          {item.framework_effective_date ? `od ${formatDate(item.framework_effective_date)}` : null}
          {more > 0 ? `${item.framework_effective_date ? " · " : ""}+${countPl(more, "umowa", "umowy", "umów")}` : null}
        </span>
      ) : null}
    </span>
  );
}

function EmptyState({
  searching,
  mine,
  state,
  onClearSearch,
  onShowAll,
}: {
  searching: boolean;
  mine: boolean;
  state: ClientListState;
  onClearSearch: () => void;
  onShowAll: () => void;
}) {
  if (searching) {
    return (
      <>
        <SearchX className="mx-auto mb-3 h-10 w-10 text-muted-foreground" aria-hidden="true" />
        <p className="text-sm font-medium text-foreground">Nie ma takiego klienta</p>
        <p className="mt-1 text-sm text-muted-foreground">Szukamy we wszystkich klientach. Zmień frazę.</p>
        <Button className="mt-4" size="sm" variant="outline" onClick={onClearSearch}>
          Wyczyść wyszukiwanie
        </Button>
      </>
    );
  }
  return (
    <>
      <Building2 className="mx-auto mb-3 h-10 w-10 text-muted-foreground" aria-hidden="true" />
      <p className="text-sm font-medium text-foreground">
        {mine ? "Nie masz tu przypisanych klientów" : "Nie ma tu klientów"} („{STATE_META[state].title}”)
      </p>
      <p className="mt-1 text-sm text-muted-foreground">{STATE_META[state].definition}</p>
      {mine ? (
        <Button className="mt-4" size="sm" variant="outline" onClick={onShowAll}>
          Pokaż wszystkich klientów
        </Button>
      ) : null}
    </>
  );
}

