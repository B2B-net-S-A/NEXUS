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
import { useAuthStore, hasRole } from "@/store/auth";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onNewCandidate?: () => void;
  onNewJob?: () => void;
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
  const user = useAuthStore((s) => s.user);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<QuickResult[]>([]);
  const [searching, setSearching] = useState(false);

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

    const timer = setTimeout(() => {
      const requests = [
        api
          .get("/api/candidates", {
            params: { q: term, page_size: 5 },
            signal: ctrl.signal,
          })
          .then((res) => {
            buckets.candidate = ((res.data?.items ?? []) as RawSearchItem[]).map(
              (c) => ({
                type: "candidate" as const,
                id: c.id,
                title:
                  `${c.name ?? ""} ${c.lastname ?? ""}`.trim() ||
                  `Kandydat #${c.id}`,
                subtitle: c.position ?? c.current_role ?? null,
              }),
            );
            flush();
          }),
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
                title: j.title ?? `Oferta #${j.id}`,
                subtitle: j.client_name ?? null,
              }),
            );
            flush();
          }),
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
      ];
      // Clear the "searching…" hint only once every request has settled
      // (resolved, rejected, or aborted). A slow or failing endpoint just
      // contributes no rows — the others still render as they arrive.
      void Promise.allSettled(requests).then(() => {
        if (!cancelled) setSearching(false);
      });
    }, 250);

    return () => {
      cancelled = true;
      ctrl.abort();
      clearTimeout(timer);
    };
  }, [query, open]);

  const go = (href: string) => {
    onOpenChange(false);
    router.push(href);
  };

  const navItems = useMemo(
    () => [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      { href: "/candidates", label: "Kandydaci", icon: Users },
      { href: "/jobs", label: "Oferty", icon: Briefcase },
      { href: "/clients", label: "Klienci", icon: Building2 },
      { href: "/contracts", label: "Kontrakty", icon: FileText },
      { href: "/talents", label: "Talenty", icon: Star },
      { href: "/calendar", label: "Kalendarz", icon: Calendar },
      { href: "/insights", label: "Insights", icon: Lightbulb },
      { href: "/settings", label: "Ustawienia", icon: Settings },
      { href: "/manager", label: "Panel managera", icon: GitBranch, roles: ["admin", "delivery_lead"] as const },
    ],
    []
  );

  const visibleNav = navItems.filter((i) => !i.roles || hasRole(user, ...i.roles));

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} shouldFilter={false}>
      <CommandInput
        placeholder="Szukaj kandydatów, ofert, klientów, akcji…"
        value={query}
        onValueChange={setQuery}
      />
      <CommandList>
        <CommandEmpty>
          {query.trim().length < 2
            ? "Zacznij pisać, aby wyszukać."
            : searching
              ? "Szukam…"
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
                  Nowa oferta
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
