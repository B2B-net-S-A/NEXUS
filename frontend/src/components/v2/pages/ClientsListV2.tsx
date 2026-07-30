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
  Handshake,
  Info,
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
} from "@/lib/api";
import { cn } from "@/lib/utils";
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

function contractEndLabel(item: ClientDirectoryItem): string {
  if (item.msa_id === null) return "—";
  if (item.expiry_date === null) return "Bezterminowa";
  return formatDirectoryDate(item.expiry_date);
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
                <TableHead>Aktywni konsultanci</TableHead>
                <TableHead>Start umowy</TableHead>
                <TableHead>Koniec umowy</TableHead>
                <TableHead>Status klienta</TableHead>
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
                    {Array.from({ length: 5 }, (_, cellIndex) => (
                      <TableCell key={cellIndex}>
                        <Skeleton className="h-4 w-24" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : failed ? (
                <TableRow>
                  <TableCell colSpan={6} className="p-0">
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
                  <TableCell colSpan={6} className="py-12 text-center">
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
                  return (
                    <TableRow key={item.scope_id} interactive>
                      <TableCell>
                        <Link
                          href={`/clients/${item.client_id}`}
                          className="flex items-center gap-3 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
                      </TableCell>
                      <TableCell>{item.industry || "—"}</TableCell>
                      <TableCell>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span
                              className="inline-flex cursor-help items-center gap-1.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              tabIndex={0}
                              aria-label={`${item.active_consultants_count} aktywnych konsultantów u klienta, łącznie we wszystkich zakresach`}
                            >
                              <span className="font-medium tabular-nums">
                                {item.active_consultants_count}
                              </span>
                              <Info
                                className="h-3.5 w-3.5 text-muted-foreground"
                                aria-hidden="true"
                              />
                            </span>
                          </TooltipTrigger>
                          <TooltipContent>
                            Liczba dla całego klienta: aktywni konsultanci
                            łącznie we wszystkich zakresach.
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
