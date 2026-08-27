"use client";

import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  Building2,
  CheckCircle2,
  Download,
  Handshake,
  Info,
  PenLine,
  Plus,
  Search,
  SearchX,
  X,
} from "lucide-react";

import {
  clientsDirectoryApi,
  type ClientDirectoryCategory,
  type ClientDirectoryCategoryCounts,
  type ClientDirectoryItem,
  type PortfolioScopePlacementUpdate,
} from "@/lib/api";
import { AppModal } from "@/components/ds/AppModal";
import { cn } from "@/lib/utils";
import { getAccessToken } from "@/lib/session";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import {
  httpStatusFromError,
  resolveViewState,
  type ViewState,
} from "@/lib/view-state";
import { useCapability } from "@/hooks/useCapability";
import { AddClientModal } from "@/components/AppShell";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const PAGE_SIZE = 50;
const CATEGORY_ORDER: ClientDirectoryCategory[] = [
  "active",
  "relationship",
  "inactive",
];

const EMPTY_COUNTS: ClientDirectoryCategoryCounts = {
  active: 0,
  relationship: 0,
  inactive: 0,
};

const CATEGORY_META: Record<
  ClientDirectoryCategory,
  {
    title: string;
    description: string;
    icon: typeof CheckCircle2;
    iconClassName: string;
  }
> = {
  active: {
    title: "Aktywni klienci",
    description: "Klienci z podpisaną współpracą",
    icon: CheckCircle2,
    iconClassName: "bg-success-muted text-success-muted-foreground",
  },
  relationship: {
    title: "Klienci relacyjni",
    description: "Utrzymywany kontakt, brak aktywnych zleceń",
    icon: Handshake,
    iconClassName: "bg-primary/10 text-primary",
  },
  inactive: {
    title: "Nieaktywni klienci",
    description: "Brak kontaktu / zakończona współpraca",
    icon: Archive,
    iconClassName: "bg-muted text-muted-foreground",
  },
};

const STATUS_META: Record<
  ClientDirectoryItem["client_status"],
  { label: string; variant: "success" | "neutral" | "soft" }
> = {
  active: { label: "Aktywny", variant: "success" },
  inactive: { label: "Nieaktywny", variant: "neutral" },
  prospect: { label: "Prospekt", variant: "soft" },
};

function parseCategory(value: string | null): ClientDirectoryCategory {
  return CATEGORY_ORDER.includes(value as ClientDirectoryCategory)
    ? (value as ClientDirectoryCategory)
    : "active";
}

function parsePage(value: string | null): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 1;
}

function formatDirectoryDate(value: string | null): string {
  if (!value) return "—";
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (dateOnly) return `${dateOnly[3]}.${dateOnly[2]}.${dateOnly[1]}`;
  return "—";
}

/** A row has a contract period if it links an MSA or pins either date manually. */
function hasContractPeriod(item: ClientDirectoryItem): boolean {
  return (
    item.msa_id !== null ||
    item.contract_start_override !== null ||
    item.contract_end_override !== null
  );
}

function contractEndLabel(item: ClientDirectoryItem): string {
  if (!hasContractPeriod(item)) return "—";
  if (item.expiry_date === null) return "Bezterminowa";
  return formatDirectoryDate(item.expiry_date);
}

/** Short tab labels for the placement dialog (distinct from the status badge). */
const CATEGORY_SHORT_LABEL: Record<ClientDirectoryCategory, string> = {
  active: "Aktywni",
  relationship: "Relacyjni",
  inactive: "Nieaktywni",
};

function initialsFor(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function countLabel(
  count: number,
  singular: string,
  paucal: string,
  plural: string,
): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  const noun =
    count === 1
      ? singular
      : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)
        ? paucal
        : plural;
  return `${count} ${noun}`;
}

export function ClientsListV2() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  const urlCategory = parseCategory(searchParams.get("category"));
  const urlSearch = searchParams.get("q") ?? "";
  const urlPage = parsePage(searchParams.get("page"));

  const [category, setCategory] =
    useState<ClientDirectoryCategory>(urlCategory);
  const [search, setSearch] = useState(urlSearch);
  const [querySearch, setQuerySearch] = useState(urlSearch.trim());
  const [page, setPage] = useState(urlPage);
  const [counts, setCounts] =
    useState<ClientDirectoryCategoryCounts>(EMPTY_COUNTS);
  const [showAdd, setShowAdd] = useState(false);
  const [placementTarget, setPlacementTarget] =
    useState<ClientDirectoryItem | null>(null);
  const [exporting, setExporting] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const didCanonicalizeUrl = useRef(false);
  const searchSyncTarget = useRef<string | null>(null);

  // Back/forward and external deep-link changes remain authoritative.
  useEffect(() => setCategory(urlCategory), [urlCategory]);
  useEffect(() => {
    searchSyncTarget.current = urlSearch;
    setSearch(urlSearch);
    setQuerySearch(urlSearch.trim());
  }, [urlSearch]);
  useEffect(() => setPage(urlPage), [urlPage]);

  const replaceUrl = useCallback(
    (
      next: {
        category: ClientDirectoryCategory;
        q: string;
        page: number;
      },
      mode: "push" | "replace",
    ) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("category", next.category);
      if (next.q.trim()) params.set("q", next.q.trim());
      else params.delete("q");
      params.set("page", String(next.page));
      const href = `${pathname || "/clients"}?${params.toString()}`;
      router[mode](href, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  // Canonical URL makes the default state copyable too, while invalid or
  // missing category/page values fail closed to active + page 1.
  useEffect(() => {
    if (didCanonicalizeUrl.current) return;
    didCanonicalizeUrl.current = true;
    if (
      searchParams.get("category") === category &&
      searchParams.get("page") === String(page)
    ) {
      return;
    }
    replaceUrl({ category, q: urlSearch, page }, "replace");
  }, [category, page, replaceUrl, searchParams, urlSearch]);

  const debouncedSearch = useDebouncedValue(search, 300);
  const previousDebouncedSearch = useRef(debouncedSearch);

  useEffect(() => {
    if (previousDebouncedSearch.current === debouncedSearch) return;
    previousDebouncedSearch.current = debouncedSearch;
    const normalized = debouncedSearch.trim();
    if (searchSyncTarget.current !== null) {
      if (normalized === searchSyncTarget.current.trim()) {
        searchSyncTarget.current = null;
      }
      return;
    }
    setQuerySearch(normalized);
    if (normalized === urlSearch) return;
    replaceUrl({ category, q: normalized, page: 1 }, "replace");
  }, [category, debouncedSearch, replaceUrl, urlSearch]);

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["clients-directory", category, querySearch, page],
    queryFn: ({ signal }) =>
      clientsDirectoryApi
        .list(
          {
            category,
            q: querySearch || undefined,
            page,
            page_size: PAGE_SIZE,
          },
          signal,
        )
        .then((response) => response.data),
    placeholderData: (previousData, previousQuery) => {
      const previousKey = previousQuery?.queryKey;
      if (
        previousKey?.[1] === category &&
        previousKey?.[2] === querySearch
      ) {
        return previousData;
      }
      return undefined;
    },
  });

  useEffect(() => {
    if (data?.category_counts) setCounts(data.category_counts);
  }, [data?.category_counts]);

  const canCreateClient = useCapability("client.create");
  const canManagePortfolio = useCapability("client.portfolio.manage");
  // The actions column only exists for portfolio managers, so table-wide
  // colSpans (skeleton, empty, error) must track it.
  const columnCount = canManagePortfolio ? 7 : 6;
  const items = data?.items ?? [];
  const totalRows = data?.total_rows ?? 0;
  const totalClients = data?.total_clients ?? 0;
  const pageSize = data?.page_size ?? PAGE_SIZE;
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));
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

  const selectCategory = (next: ClientDirectoryCategory) => {
    if (next === category) return;
    const normalizedSearch = search.trim();
    setCategory(next);
    setQuerySearch(normalizedSearch);
    setPage(1);
    replaceUrl({ category: next, q: normalizedSearch, page: 1 }, "push");
  };

  const handleCategoryKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    current: ClientDirectoryCategory,
  ) => {
    const currentIndex = CATEGORY_ORDER.indexOf(current);
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") {
      nextIndex = (currentIndex + 1) % CATEGORY_ORDER.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex =
        (currentIndex - 1 + CATEGORY_ORDER.length) % CATEGORY_ORDER.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = CATEGORY_ORDER.length - 1;
    }
    if (nextIndex === null) return;
    event.preventDefault();
    const next = CATEGORY_ORDER[nextIndex];
    selectCategory(next);
    document.getElementById(`clients-category-${next}`)?.focus();
  };

  const goToPage = (next: number) => {
    setPage(next);
    replaceUrl({ category, q: search, page: next }, "push");
  };

  const clearSearch = () => {
    searchSyncTarget.current = null;
    setSearch("");
    setQuerySearch("");
    setPage(1);
    replaceUrl({ category, q: "", page: 1 }, "replace");
  };

  const onAdded = (message: string) => {
    setShowAdd(false);
    setToast(message);
    void queryClient.invalidateQueries({ queryKey: ["clients-directory"] });
    setTimeout(() => setToast(null), 3000);
  };

  const onPlacementSaved = (message: string) => {
    setPlacementTarget(null);
    setToast(message);
    void queryClient.invalidateQueries({ queryKey: ["clients-directory"] });
    setTimeout(() => setToast(null), 3000);
  };

  // Export the currently-visible directory (same category + committed search as
  // the list) to Excel/CSV, so "eksportuj to, co widzę" holds. Uses `querySearch`
  // — the debounced value that drives the list — not the raw input, so the file
  // matches the screen within the 300 ms search window. Pagination is dropped;
  // the endpoint returns every matching scope up to its cap.
  const doExport = async (format: "xlsx" | "csv") => {
    if (exporting) return;
    setExporting(true);
    try {
      const params = new URLSearchParams();
      params.set("category", category);
      if (querySearch) params.set("q", querySearch);
      params.set("format", format);
      const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
      const token = getAccessToken();
      const res = await fetch(
        `${apiBase}/api/clients/directory/export?${params}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      );
      if (!res.ok) {
        setToast("Eksport nie powiódł się.");
        setTimeout(() => setToast(null), 3500);
        return;
      }
      // The backend caps the row count and flags a partial file in this header.
      const truncated = res.headers.get("X-Export-Truncated") === "true";
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `klienci-${new Date().toISOString().slice(0, 10)}.${format}`;
      // Anchor must be in the DOM for click() to fire across browsers; the
      // object URL is revoked lazily so large downloads finish first.
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      if (truncated) {
        setToast("Wyeksportowano częściowy widok — przekroczono limit wierszy.");
        setTimeout(() => setToast(null), 4500);
      }
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1400px] space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-eyebrow text-primary">
            Delivery · Klienci
          </p>
          <h1 className="mt-1 text-3xl font-extrabold tracking-heading-tight text-foreground">
            Klienci
          </h1>
          <p
            className="mt-1 text-sm text-muted-foreground"
            aria-live="polite"
          >
            {isLoading
              ? "Ładowanie portfela…"
              : failed
                ? "Nie udało się pobrać portfela klientów"
                : `${countLabel(
                    totalRows,
                    "zakres",
                    "zakresy",
                    "zakresów",
                  )} dla ${countLabel(
                    totalClients,
                    "klienta",
                    "klientów",
                    "klientów",
                  )}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Popover>
            <PopoverTrigger asChild>
              <Button size="sm" variant="outline" disabled={exporting}>
                <Download className="h-4 w-4" aria-hidden="true" />
                {exporting ? "Eksportuję…" : "Eksport"}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-44 p-1">
              <button
                type="button"
                onClick={() => void doExport("xlsx")}
                className="block w-full rounded-md px-3 py-1.5 text-left text-sm hover:bg-primary/10"
              >
                Excel (.xlsx)
              </button>
              <button
                type="button"
                onClick={() => void doExport("csv")}
                className="block w-full rounded-md px-3 py-1.5 text-left text-sm hover:bg-primary/10"
              >
                CSV
              </button>
            </PopoverContent>
          </Popover>
          {canCreateClient ? (
            <Button
              size="sm"
              variant="primary"
              onClick={() => setShowAdd(true)}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Nowy klient
            </Button>
          ) : null}
        </div>
      </div>

      <div className="max-w-lg">
        <label
          htmlFor="client-directory-search"
          className="mb-1.5 block text-sm font-medium text-foreground"
        >
          Wyszukaj klienta
        </label>
        <div className="relative">
          <Input
            id="client-directory-search"
            leadingIcon={<Search className="h-4 w-4" />}
            className={cn(search && "pr-10")}
            placeholder="Nazwa firmy lub branża"
            value={search}
            onChange={(event) => {
              searchSyncTarget.current = null;
              setSearch(event.target.value);
              setPage(1);
            }}
            aria-describedby="client-directory-search-help"
          />
          {search ? (
            <button
              type="button"
              onClick={clearSearch}
              className="absolute right-2 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Wyczyść wyszukiwanie"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          ) : null}
        </div>
        <p
          id="client-directory-search-help"
          className="mt-1.5 text-xs text-muted-foreground"
        >
          Wyszukiwanie obejmuje tylko aktualnie wybraną kategorię.
        </p>
      </div>

      <div
        role="tablist"
        aria-label="Kategorie klientów"
        className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3"
      >
        {CATEGORY_ORDER.map((itemCategory) => {
          const meta = CATEGORY_META[itemCategory];
          const Icon = meta.icon;
          const selected = itemCategory === category;
          return (
            <button
              id={`clients-category-${itemCategory}`}
              key={itemCategory}
              type="button"
              role="tab"
              aria-label={`${meta.title}, ${countLabel(
                counts[itemCategory],
                "klient",
                "klientów",
                "klientów",
              )}`}
              aria-selected={selected}
              aria-controls="client-directory-panel"
              tabIndex={selected ? 0 : -1}
              onClick={() => selectCategory(itemCategory)}
              onKeyDown={(event) =>
                handleCategoryKeyDown(event, itemCategory)
              }
              className={cn(
                "flex min-h-24 items-center gap-3 rounded-xl border bg-card p-4 text-left transition-colors",
                "hover:border-primary/50 hover:bg-primary/5",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                selected
                  ? "border-primary bg-primary/5 shadow-sm"
                  : "border-border",
              )}
            >
              <span
                className={cn(
                  "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl",
                  meta.iconClassName,
                )}
              >
                <Icon className="h-5 w-5" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-foreground">
                  {meta.title}
                </span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {meta.description}
                </span>
              </span>
              <span
                className={cn(
                  "text-xl font-semibold tabular-nums",
                  selected ? "text-primary" : "text-foreground",
                )}
              >
                {counts[itemCategory]}
              </span>
            </button>
          );
        })}
      </div>

      <section
        id="client-directory-panel"
        role="tabpanel"
        aria-labelledby={`clients-category-${category}`}
        aria-busy={isFetching}
      >
        <TooltipProvider delayDuration={200}>
          <Table density="cozy" className="min-w-[900px]">
            <TableHeader>
              <TableRow>
                <TableHead>Firma</TableHead>
                <TableHead>Branża</TableHead>
                <TableHead>Aktywni konsultanci / kontrakty</TableHead>
                <TableHead>Start umowy</TableHead>
                <TableHead>Koniec umowy</TableHead>
                <TableHead>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span
                        className="inline-flex cursor-help items-center gap-1 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        tabIndex={0}
                      >
                        Status klienta
                        <Info
                          className="h-3.5 w-3.5 text-muted-foreground"
                          aria-hidden="true"
                        />
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>
                      Status handlowy (etykieta) — niezależny od zakładki. O tym,
                      w której zakładce jest klient, decyduje kategoria portfela.
                    </TooltipContent>
                  </Tooltip>
                </TableHead>
                {canManagePortfolio ? (
                  <TableHead className="text-right">Akcje</TableHead>
                ) : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {viewState === "loading" ? (
                Array.from({ length: 5 }, (_, index) => (
                  <TableRow key={`client-skeleton-${index}`}>
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
                        <Skeleton className="h-4 w-24" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : failed ? (
                <TableRow>
                  <TableCell colSpan={columnCount} className="p-0">
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
                          ? "Twoja rola nie ma dostępu do portfela klientów. Dane nie są puste — poproś administratora o uprawnienia."
                          : viewState === "error" &&
                              httpStatusFromError(error) === undefined
                            ? "Nie udało się połączyć z serwerem. Sprawdź internet lub VPN i spróbuj ponownie."
                            : undefined
                      }
                      onRetry={
                        viewState === "error"
                          ? () => void refetch()
                          : undefined
                      }
                    />
                  </TableCell>
                </TableRow>
              ) : viewState === "empty" ? (
                <TableRow>
                  <TableCell colSpan={columnCount} className="py-12 text-center">
                    {querySearch ? (
                      <>
                        <SearchX
                          className="mx-auto mb-3 h-10 w-10 text-muted-foreground"
                          aria-hidden="true"
                        />
                        <p className="text-sm font-medium text-foreground">
                          Brak wyników w kategorii „
                          {CATEGORY_META[category].title}”
                        </p>
                        <p className="mt-1 text-sm text-muted-foreground">
                          Zmień frazę lub wyczyść wyszukiwanie.
                        </p>
                        <Button
                          className="mt-4"
                          size="sm"
                          variant="outline"
                          onClick={clearSearch}
                        >
                          Wyczyść wyszukiwanie
                        </Button>
                      </>
                    ) : (
                      <>
                        <Building2
                          className="mx-auto mb-3 h-10 w-10 text-muted-foreground"
                          aria-hidden="true"
                        />
                        <p className="text-sm font-medium text-foreground">
                          Brak klientów w kategorii „
                          {CATEGORY_META[category].title}”
                        </p>
                        <p className="mt-1 text-sm text-muted-foreground">
                          Klienci pojawią się tutaj po przypisaniu zakresu do tej
                          kategorii.
                        </p>
                        {canCreateClient ? (
                          <Button
                            className="mt-4"
                            size="sm"
                            variant="outline"
                            onClick={() => setShowAdd(true)}
                          >
                            <Plus className="h-4 w-4" aria-hidden="true" />
                            Dodaj klienta
                          </Button>
                        ) : null}
                      </>
                    )}
                  </TableCell>
                </TableRow>
              ) : (
                items.map((item) => {
                  const status = STATUS_META[item.client_status];
                  // A row is "manually placed" when its effective tab differs
                  // from the manifest base, or a contract date was pinned — not
                  // merely when a (possibly redundant) override column is set.
                  const manuallyPlaced =
                    item.category !== item.category_base ||
                    item.contract_start_override !== null ||
                    item.contract_end_override !== null;
                  return (
                    <TableRow key={item.scope_id} interactive>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Link
                            href={`/clients/${item.client_id}`}
                            className="flex min-w-0 items-center gap-3 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            <Avatar size="sm">
                              <AvatarFallback>
                                {initialsFor(item.display_name)}
                              </AvatarFallback>
                            </Avatar>
                            <span className="min-w-0">
                              <span className="block font-medium text-foreground">
                                {item.display_name}
                              </span>
                              {item.scope_label ? (
                                <span className="mt-0.5 block text-xs text-muted-foreground">
                                  {item.scope_label}
                                </span>
                              ) : null}
                            </span>
                          </Link>
                          {manuallyPlaced ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span tabIndex={0} className="shrink-0">
                                  <Badge size="sm" variant="soft">
                                    ręcznie
                                  </Badge>
                                </span>
                              </TooltipTrigger>
                              <TooltipContent>
                                Ustawienia portfela (zakładka / daty) nadpisane
                                ręcznie — inaczej niż w manifeście.
                              </TooltipContent>
                            </Tooltip>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>{item.industry || "—"}</TableCell>
                      <TableCell>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span
                              className="inline-flex cursor-help items-center gap-1.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              tabIndex={0}
                              aria-label={`${item.active_consultants_count} aktywnych konsultantów i ${item.active_contracts_count} aktywnych kontraktów u klienta, łącznie we wszystkich zakresach`}
                            >
                              <span className="font-medium tabular-nums">
                                {item.active_consultants_count} / {item.active_contracts_count}
                              </span>
                              <Info
                                className="h-3.5 w-3.5 text-muted-foreground"
                                aria-hidden="true"
                              />
                            </span>
                          </TooltipTrigger>
                          <TooltipContent>
                            Liczba dla całego klienta: aktywni konsultanci /
                            aktywne kontrakty, łącznie we wszystkich zakresach.
                          </TooltipContent>
                        </Tooltip>
                      </TableCell>
                      <TableCell>
                        {formatDirectoryDate(item.effective_date)}
                      </TableCell>
                      <TableCell>{contractEndLabel(item)}</TableCell>
                      <TableCell>
                        <Badge size="sm" variant={status.variant}>
                          {status.label}
                        </Badge>
                      </TableCell>
                      {canManagePortfolio ? (
                        <TableCell className="text-right">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setPlacementTarget(item)}
                          >
                            <PenLine className="h-4 w-4" aria-hidden="true" />
                            Przenieś
                          </Button>
                        </TableCell>
                      ) : null}
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </TooltipProvider>
      </section>

      {viewState === "ready" && totalRows > pageSize ? (
        <nav
          className="flex flex-col gap-3 text-sm sm:flex-row sm:items-center sm:justify-between"
          aria-label="Paginacja klientów"
        >
          <span className="text-muted-foreground">
            Strona <strong className="text-foreground">{page}</strong> z{" "}
            {totalPages}
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

      {showAdd ? (
        <AddClientModal
          onClose={() => setShowAdd(false)}
          onSuccess={onAdded}
          category={category}
        />
      ) : null}
      {placementTarget ? (
        <PlacementDialog
          item={placementTarget}
          onClose={() => setPlacementTarget(null)}
          onSaved={onPlacementSaved}
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

// ── Placement dialog (manifest-safe curation) ─────────────────────────────────
// Moves a scope between the Aktywni/Relacyjni/Nieaktywni tabs and/or pins a
// contract period by writing the scope's *_override columns. It never edits the
// manifest base columns, so it can't cause portfolio drift / an unhealthy
// /api/health/deep. Category is separate from the "Status klienta" badge.

const PLACEMENT_INPUT_CLASS =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function PlacementDialog({
  item,
  onClose,
  onSaved,
}: {
  item: ClientDirectoryItem;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [selectedCategory, setSelectedCategory] =
    useState<ClientDirectoryCategory>(item.category);
  const [startOverride, setStartOverride] = useState(
    item.contract_start_override ?? "",
  );
  const [endOverride, setEndOverride] = useState(
    item.contract_end_override ?? "",
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasOverride =
    item.category_override !== null ||
    item.contract_start_override !== null ||
    item.contract_end_override !== null;

  const submit = async (payload: PortfolioScopePlacementUpdate) => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      await clientsDirectoryApi.updateScopePlacement(
        item.client_id,
        item.scope_id,
        payload,
      );
      const moved =
        payload.category !== undefined &&
        payload.category !== null &&
        payload.category !== item.category;
      onSaved(
        moved
          ? `Przeniesiono „${item.display_name}” do: ${CATEGORY_SHORT_LABEL[payload.category as ClientDirectoryCategory]}.`
          : `Zapisano ustawienie portfela dla „${item.display_name}”.`,
      );
    } catch (err) {
      const detail = (
        err as { response?: { data?: { detail?: string } } }
      )?.response?.data?.detail;
      setError(detail ?? "Nie udało się zapisać. Spróbuj ponownie.");
      setSaving(false);
    }
  };

  const handleSave = () => {
    if (startOverride && endOverride && endOverride < startOverride) {
      setError("Data zakończenia nie może być wcześniejsza niż rozpoczęcia.");
      return;
    }
    const payload: PortfolioScopePlacementUpdate = {};
    if (selectedCategory !== item.category) {
      // Picking the manifest's own category clears the override instead of
      // pinning a redundant one (which would keep the "ręcznie" flag forever).
      payload.category =
        selectedCategory === item.category_base ? null : selectedCategory;
    }
    if (startOverride !== (item.contract_start_override ?? "")) {
      payload.contract_start = startOverride || null;
    }
    if (endOverride !== (item.contract_end_override ?? "")) {
      payload.contract_end = endOverride || null;
    }
    if (Object.keys(payload).length === 0) {
      onClose();
      return;
    }
    void submit(payload);
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open && !saving) onClose();
      }}
      title="Kategoria portfela (zakładka)"
      description={`Ręczne ustawienie dla „${item.display_name}”. Nadpisuje manifest tylko w tym widoku — nie zmienia „Statusu klienta”.`}
      footer={
        <>
          {hasOverride ? (
            <Button
              variant="ghost"
              className="mr-auto"
              disabled={saving}
              onClick={() =>
                void submit({
                  category: null,
                  contract_start: null,
                  contract_end: null,
                })
              }
            >
              Przywróć z manifestu
            </Button>
          ) : null}
          <Button variant="outline" disabled={saving} onClick={onClose}>
            Anuluj
          </Button>
          <Button variant="primary" disabled={saving} onClick={handleSave}>
            {saving ? "Zapisuję…" : "Zapisz"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error ? (
          <p
            role="alert"
            className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {error}
          </p>
        ) : null}

        <div className="space-y-1.5">
          <label
            htmlFor="placement-category"
            className="block text-sm font-medium text-foreground"
          >
            Zakładka portfela
          </label>
          <select
            id="placement-category"
            className={PLACEMENT_INPUT_CLASS}
            value={selectedCategory}
            onChange={(event) =>
              setSelectedCategory(event.target.value as ClientDirectoryCategory)
            }
          >
            {CATEGORY_ORDER.map((value) => (
              <option key={value} value={value}>
                {CATEGORY_SHORT_LABEL[value]}
              </option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label
              htmlFor="placement-start"
              className="block text-sm font-medium text-foreground"
            >
              Start umowy
            </label>
            <input
              id="placement-start"
              type="date"
              className={PLACEMENT_INPUT_CLASS}
              value={startOverride}
              onChange={(event) => setStartOverride(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <label
              htmlFor="placement-end"
              className="block text-sm font-medium text-foreground"
            >
              Koniec umowy
            </label>
            <input
              id="placement-end"
              type="date"
              className={PLACEMENT_INPUT_CLASS}
              value={endOverride}
              onChange={(event) => setEndOverride(event.target.value)}
            />
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Puste daty = użyj dat z umowy ramowej (jeśli podpięta). Ustawione daty
          nadpisują widok w katalogu, nie zmieniając samej umowy ramowej.
        </p>
      </div>
    </AppModal>
  );
}
