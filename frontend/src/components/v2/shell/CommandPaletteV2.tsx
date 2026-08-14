"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Briefcase,
  Building2,
  Calendar,
  FileText,
  GitBranch,
  LayoutDashboard,
  Lightbulb,
  Mail,
  Plus,
  Search,
  Settings,
  Star,
  Radar,
  Wallet,
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
import type { Capability } from "@/lib/capabilities";
import { useCapabilities } from "@/hooks/useCapability";

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
  position?: string | null;
  current_role?: string | null;
  title?: string | null;
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
  const canSearchCandidates = can["nav.candidates"];
  const canSearchClients = can["nav.clients"];
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
              params: { q: term, page_size: 5 },
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
                subtitle: c.position ?? c.current_role ?? null,
              }));
              flush();
            }),
        );
      }
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
                title: j.title ?? `Rekrutacja #${j.id}`,
                subtitle: j.client_name ?? null,
              }),
            );
            flush();
          }),
      );
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
  }, [query, open, canSearchCandidates, canSearchClients]);

  const go = (href: string) => {
    onOpenChange(false);
    router.push(href);
  };

  // Bramki nawigacji pochodzą z tego samego rejestru co sidebar i middleware
  // (audyt F-19). Wcześniej paleta miała własną, uboższą listę — pokazywała
  // „Kandydaci"/„Klienci"/„Kontrakty"/„Talenty" rolom, które middleware
  // odbijał na /403.
  const navItems: Array<{
    href: string;
    label: string;
    icon: typeof LayoutDashboard;
    capability?: Capability;
  }> = useMemo(
    () => [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      {
        href: "/candidates",
        label: "Kandydaci",
        icon: Users,
        capability: "nav.candidates",
      },
      { href: "/jobs", label: "Rekrutacje", icon: Briefcase },
      {
        href: "/clients",
        label: "Klienci",
        icon: Building2,
        capability: "nav.clients",
      },
      {
        href: "/contracts",
        label: "Kontrakty",
        icon: FileText,
        capability: "nav.contracts",
      },
      {
        href: "/talents",
        label: "Talenty",
        icon: Star,
        capability: "nav.talents",
      },
      {
        href: "/talent-radar",
        label: "Talent Radar",
        icon: Radar,
        capability: "nav.talent_radar",
      },
      { href: "/calendar", label: "Kalendarz", icon: Calendar },
      { href: "/insights", label: "Insights", icon: Lightbulb },
      { href: "/settings", label: "Ustawienia", icon: Settings },
      {
        href: "/manager",
        label: "Panel managera",
        icon: GitBranch,
        capability: "nav.manager",
      },
      {
        href: "/finance",
        label: "Finanse",
        icon: Wallet,
        capability: "nav.finance",
      },
    ],
    [],
  );

  const visibleNav = navItems.filter((i) => !i.capability || can[i.capability]);

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
        </CommandEmpty>

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
              <CommandItem onSelect={() => go("/settings")}>
                <Mail className="h-4 w-4" />
                Szablony email
              </CommandItem>
            </CommandGroup>

            <CommandSeparator />

            <CommandGroup heading="Nawigacja">
              {visibleNav.map((item) => {
                const Icon = item.icon;
                return (
                  <CommandItem
                    key={item.href}
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
