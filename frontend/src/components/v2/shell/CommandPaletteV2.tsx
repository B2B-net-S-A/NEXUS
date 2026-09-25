"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Briefcase,
  Building2,
  Settings,
  Plus,
  Search,
  Sparkles,
  Users,
} from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command";
import api from "@/lib/api";
import {
  canSeeFeatureFlaggedEntry,
  resolveNavHref,
  visiblePaletteEntries,
} from "@/lib/nav-registry";
import { hasSectionAccess } from "@/lib/section-access";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";
import { useCapabilities } from "@/hooks/useCapability";
import { useAuthStore } from "@/store/auth";
import { openJarvis } from "@/lib/jarvis/events";
import { listedSettingsItems, settingsItemHref } from "@/lib/settings-registry";
import { jobClientLine, jobDisplayTitle } from "@/lib/job-names";

interface Props {
  /** `undefined` = user nie ma capability `candidate.create` (patrz AppShellV2). */
  onNewCandidate?: () => void;
  /** Jw. dla `job.create`. */
  onNewJob?: () => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type QuickResult =
  | { type: "candidate"; id: number; title: string; subtitle: string | null }
  | { type: "job"; id: number; title: string; subtitle: string | null }
  | { type: "client"; id: number; title: string; subtitle: string | null };

// Loose shape of the rows returned by the list endpoints — only the fields the
// palette reads. The three endpoints share a `{ items, total }` envelope but
// each item carries a different subset of these keys.
interface RawSearchItem {
  id: number;
  name?: string | null;
  lastname?: string | null;
  /** Kandydat: stanowisko z LinkedIna i miasto (pola `CandidateResponse`). */
  linkedin_current_title?: string | null;
  city?: string | null;
  title?: string | null;
  working_title?: string | null;
  client_reference?: string | null;
  client_name?: string | null;
  industry?: string | null;
}

export function CommandPaletteV2({
  open,
  onOpenChange,
  onNewCandidate,
  onNewJob,
}: Props) {
  const router = useRouter();
  const can = useCapabilities();
  const user = useAuthStore((state) => state.user);
  const canSearchCandidates =
    hasSectionAccess(user, "sourcing") && can["nav.candidates"];
  const canSearchJobs = hasSectionAccess(user, "pipeline");
  const canSearchClients = hasSectionAccess(user, "delivery");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<QuickResult[]>([]);
  const [searching, setSearching] = useState(false);
  /** Każde dozwolone zapytanie padło → awaria, NIE „brak wyników" (F-20). */
  const [searchFailed, setSearchFailed] = useState(false);

  // Debounced multi-entity search.
  //
  // Each entity type (candidates / jobs / clients) is fetched in parallel but
  // rendered INDEPENDENTLY — we deliberately do NOT await all three together.
  // The candidate search scans large CV / JSONB columns and can take >10s on
  // long queries, while jobs and clients return in ~100ms. Awaiting all three
  // (the previous `Promise.allSettled` + single `setResults`) hid the fast
  // results behind the slow scan, so the palette showed "Brak wyników" for
  // seconds even when an exact recruitment-title match was already available.
  // Streaming each bucket as it resolves keeps recruitment/client lookups
  // instant; the slow candidate rows fill in when (if) they arrive.
  useEffect(() => {
    if (!open) return;
    const term = query.trim();
    if (term.length < 2) {
      setResults([]);
      setSearching(false);
      setSearchFailed(false);
      return;
    }

    const ctrl = new AbortController();
    let cancelled = false;
    const buckets: Record<QuickResult["type"], QuickResult[]> = {
      candidate: [],
      job: [],
      client: [],
    };
    const flush = () => {
      if (cancelled) return;
      setResults([...buckets.candidate, ...buckets.job, ...buckets.client]);
    };

    setResults([]);
    setSearching(true);
    setSearchFailed(false);

    const timer = setTimeout(() => {
      // Zapytania wysyłamy WYŁĄCZNIE dla zasobów, do których user ma
      // capability (audyt F-19). Bez tego rola `user` (read-only viewer)
      // strzelała w /api/candidates i /api/clients tylko po to, żeby dostać
      // 403 połknięte przez `allSettled` — i zobaczyć „Brak wyników".
      const requests: Array<Promise<unknown>> = [];
      if (canSearchCandidates) {
        requests.push(
          api
            .get("/api/candidates", {
              // `sort: "relevance"` jest load-bearing: domyślne `newest` przy
              // zapytaniu pasującym do dziesiątek tysięcy rekordów (np. pełny
              // e-mail rozbity na słowa łapie samą domenę) oddawało piątkę
              // NAJNOWSZYCH, bez szukanej osoby (UAT M00-B01).
              params: { q: term, page_size: 5, sort: "relevance" },
              signal: ctrl.signal,
            })
            .then((res) => {
              buckets.candidate = (
                (res.data?.items ?? []) as RawSearchItem[]
              ).map((c) => ({
                type: "candidate" as const,
                id: c.id,
                title:
                  `${c.name ?? ""} ${c.lastname ?? ""}`.trim() ||
                  `Kandydat #${c.id}`,
                // `position`/`current_role` nie istnieją w `CandidateResponse`,
                // więc podpis był zawsze pusty i imiennicy byli nie do odróżnienia.
                subtitle:
                  [c.linkedin_current_title, c.city].filter(Boolean).join(" · ") ||
                  null,
              }));
              flush();
            }),
        );
      }
      if (canSearchJobs) {
        requests.push(
          api
            .get("/api/jobs", {
              params: { q: term, page_size: 5 },
              signal: ctrl.signal,
            })
            .then((res) => {
              buckets.job = ((res.data?.items ?? []) as RawSearchItem[]).map(
                (j) => ({
                  type: "job" as const,
                  id: j.id,
                  // 0378: tytuł dla rekrutera; pod nim klient, nazwa i numer od klienta.
                  title: jobDisplayTitle(j),
                  subtitle: jobClientLine(j) || null,
                }),
              );
              flush();
            }),
        );
      }
      if (canSearchClients) {
        requests.push(
          api
            .get("/api/clients", {
              params: { q: term, page_size: 5 },
              signal: ctrl.signal,
            })
            .then((res) => {
              buckets.client = ((res.data?.items ?? []) as RawSearchItem[]).map(
                (cl) => ({
                  type: "client" as const,
                  id: cl.id,
                  title: cl.name ?? `Klient #${cl.id}`,
                  subtitle: cl.industry ?? null,
                }),
              );
              flush();
            }),
        );
      }
      // Clear the "searching…" hint only once every request has settled
      // (resolved, rejected, or aborted). Odróżniamy przy tym awarię od pustki:
      // gdy KAŻDE zapytanie padło, pokazujemy komunikat o błędzie zamiast
      // „Brak wyników" (audyt F-20 — 5xx nie może udawać zera trafień).
      void Promise.allSettled(requests).then((settled) => {
        if (cancelled) return;
        setSearching(false);
        const failed = settled.filter((s) => s.status === "rejected");
        setSearchFailed(failed.length > 0 && failed.length === settled.length);
      });
    }, 250);

    return () => {
      cancelled = true;
      ctrl.abort();
      clearTimeout(timer);
    };
  }, [query, open, canSearchCandidates, canSearchJobs, canSearchClients]);

  const go = (href: string) => {
    onOpenChange(false);
    router.push(href);
  };

  // Jarvis słucha zdarzenia `nexus:jarvis-open` (JarvisRoot). Wpisana fraza
  // trafia do pola wiadomości — wysyła ją człowiek, nie paleta.
  const askJarvis = (prompt: string) => {
    onOpenChange(false);
    openJarvis({ prompt: prompt.trim() || undefined });
  };

  // Pozycje pochodzą z tego samego rejestru co sidebar (`lib/nav-registry`),
  // z tymi samymi bramkami: sekcja + role + akcja + flaga kolejki telefonów
  // (audyt F-19). Wcześniej paleta miała własną, uboższą listę — z adresem `/`
  // zamiast dashboardu roli i pozycją `/manager`, której w menu nie ma — więc
  // każda zmiana menu rozjeżdżała obie powierzchnie. Capability jest tu
  // DODATKOWYM filtrem: paleta nigdy nie pokaże więcej niż sidebar.
  const contactFeature = useCandidateContactFeature({
    queryEnabled: canSeeFeatureFlaggedEntry(user, "contactQueue"),
  });
  // Każda pozycja Ustawień, którą ta osoba widzi — ⌘K „reguły CV" prowadzi
  // prosto do ekranu (przebudowa Ustawień 22.09.2026).
  const settingsItems = useMemo(() => listedSettingsItems(user), [user]);
  const visibleNav = useMemo(
    () =>
      visiblePaletteEntries(
        user,
        { contactQueueEnabled: contactFeature.enabled },
        (capability) => can[capability],
      ).map((entry) => ({
        id: entry.id,
        href: resolveNavHref(entry, user),
        label: entry.label,
        icon: entry.icon,
        keywords: entry.paletteKeywords ?? [],
      })),
    [user, contactFeature.enabled, can],
  );

  // Po wpisaniu ≥2 znaków pozycje nawigacji pasujące do zapytania zostają
  // widoczne NAD wynikami wyszukiwania (UAT M00-B03) — „kand” + Enter ma
  // przenieść do Kandydatów, a nie czekać na skan bazy. Filtrujemy sami, bo
  // `shouldFilter={false}` wyłącza filtr cmdk.
  const searchTerm = query.trim();
  const matchedNav =
    searchTerm.length < 2
      ? []
      : visibleNav.filter((item) =>
          [item.label, ...item.keywords].some((text) =>
            navMatches(text, searchTerm),
          ),
        );

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} shouldFilter={false}>
      <CommandInput
        placeholder="Szukaj kandydatów, rekrutacji, klientów, akcji…"
        value={query}
        onValueChange={setQuery}
      />
      <CommandList>
        <CommandEmpty>
          {query.trim().length < 2
            ? "Zacznij pisać, aby wyszukać."
            : searching
              ? "Szukam…"
              : searchFailed
                ? "Nie udało się wyszukać — spróbuj ponownie za chwilę."
                : "Brak wyników."}
          {query.trim().length >= 2 && !searching && (
            <button
              type="button"
              className="mx-auto mt-3 flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium text-primary hover:bg-muted"
              onClick={() => askJarvis(query)}
            >
              <Sparkles className="h-4 w-4" />
              Zapytaj Jarvisa
            </button>
          )}
        </CommandEmpty>

        {matchedNav.length > 0 && (
          <CommandGroup heading="Nawigacja">
            {matchedNav.map((item) => {
              const Icon = item.icon;
              return (
                <CommandItem
                  key={item.id}
                  value={`go ${item.label}`}
                  onSelect={() => go(item.href)}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </CommandItem>
              );
            })}
          </CommandGroup>
        )}

        {query.trim().length >= 2 && (results.length > 0 || matchedNav.length > 0) && (
          <CommandGroup heading="Asystent">
            <CommandItem value={`jarvis ${query}`} onSelect={() => askJarvis(query)}>
              <Sparkles className="h-4 w-4" />
              <span className="truncate">Zapytaj Jarvisa: „{query.trim()}”</span>
            </CommandItem>
          </CommandGroup>
        )}

        {results.length > 0 && (
          <CommandGroup heading="Wyniki">
            {results.map((r) => (
              <CommandItem
                key={`${r.type}-${r.id}`}
                value={`${r.type} ${r.title} ${r.subtitle ?? ""}`}
                onSelect={() => go(resultHref(r))}
              >
                {r.type === "candidate" ? (
                  <Users className="h-4 w-4" />
                ) : r.type === "job" ? (
                  <Briefcase className="h-4 w-4" />
                ) : (
                  <Building2 className="h-4 w-4" />
                )}
                <span className="truncate">{r.title}</span>
                {r.subtitle && (
                  <span className="ml-2 text-xs text-muted-foreground truncate">
                    · {r.subtitle}
                  </span>
                )}
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {/* Static groups only in browse mode (empty query). When searching,
            shouldFilter={false} makes cmdk render exactly the server results
            above — no client-side re-filtering that could drop async rows. */}
        {query.trim().length < 2 && (
          <>
            <CommandGroup heading="Akcje">
              {onNewCandidate && (
                <CommandItem
                  onSelect={() => {
                    onOpenChange(false);
                    onNewCandidate();
                  }}
                >
                  <Plus className="h-4 w-4" />
                  Nowy kandydat
                  <CommandShortcut>N</CommandShortcut>
                </CommandItem>
              )}
              {onNewJob && (
                <CommandItem
                  onSelect={() => {
                    onOpenChange(false);
                    onNewJob();
                  }}
                >
                  <Briefcase className="h-4 w-4" />
                  Nowa rekrutacja
                  <CommandShortcut>J</CommandShortcut>
                </CommandItem>
              )}
              <CommandItem onSelect={() => askJarvis("")}>
                <Sparkles className="h-4 w-4" />
                Zapytaj Jarvisa
                <CommandShortcut>⌘J</CommandShortcut>
              </CommandItem>
            </CommandGroup>

            {settingsItems.length > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup heading="Ustawienia">
                  {settingsItems.map((item) => (
                    <CommandItem
                      key={item.id}
                      value={`Ustawienia ${item.title} ${item.keywords}`}
                      onSelect={() => go(settingsItemHref(item))}
                    >
                      <Settings className="h-4 w-4" />
                      {item.title}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}

            <CommandSeparator />

            <CommandGroup heading="Nawigacja">
              {visibleNav.map((item) => {
                const Icon = item.icon;
                return (
                  <CommandItem
                    key={item.id}
                    value={`go ${item.label}`}
                    onSelect={() => go(item.href)}
                  >
                    <Icon className="h-4 w-4" />
                    {item.label}
                  </CommandItem>
                );
              })}
            </CommandGroup>

            <CommandSeparator />

            <CommandGroup heading="Wskazówka">
              <CommandItem disabled>
                <Search className="h-4 w-4" />
                <span className="text-xs text-muted-foreground">
                  Minimum 2 znaki, aby zobaczyć wyniki wyszukiwania
                </span>
              </CommandItem>
            </CommandGroup>
          </>
        )}
      </CommandList>
    </CommandDialog>
  );
}

function foldForMatch(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ł/g, "l")
    .replace(/Ł/g, "L")
    .toLowerCase();
}

/** Pozycja nawigacji pasuje, gdy jej nazwa zawiera zapytanie (bez polskich znaków i wielkości liter). */
export function navMatches(label: string, term: string): boolean {
  const needle = foldForMatch(term.trim());
  return needle.length > 0 && foldForMatch(label).includes(needle);
}

function resultHref(r: QuickResult): string {
  switch (r.type) {
    case "candidate":
      return `/candidates/${r.id}`;
    case "job":
      return `/jobs/${r.id}`;
    case "client":
      return `/clients/${r.id}`;
  }
}
