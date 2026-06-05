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

  // Debounced search
  useEffect(() => {
    if (!open) return;
    if (query.trim().length < 2) {
      setResults([]);
      return;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const [candidates, jobs, clients] = await Promise.allSettled([
          api.get("/api/candidates", {
            params: { q: query, page_size: 5 },
            signal: ctrl.signal,
          }),
          api.get("/api/jobs", {
            params: { q: query, page_size: 5 },
            signal: ctrl.signal,
          }),
          api.get("/api/clients", {
            params: { q: query, page_size: 5 },
            signal: ctrl.signal,
          }),
        ]);
        const r: QuickResult[] = [];
        if (candidates.status === "fulfilled") {
          for (const c of candidates.value.data?.items ?? []) {
            r.push({
              type: "candidate",
              id: c.id,
              title: `${c.name ?? ""} ${c.lastname ?? ""}`.trim() || `Kandydat #${c.id}`,
              subtitle: c.position ?? c.current_role ?? null,
            });
          }
        }
        if (jobs.status === "fulfilled") {
          for (const j of jobs.value.data?.items ?? []) {
            r.push({ type: "job", id: j.id, title: j.title, subtitle: j.client_name ?? null });
          }
        }
        if (clients.status === "fulfilled") {
          for (const cl of clients.value.data?.items ?? []) {
            r.push({
              type: "client",
              id: cl.id,
              title: cl.name,
              subtitle: cl.industry ?? null,
            });
          }
        }
        setResults(r);
      } catch {
        // Ignore aborts / errors — empty state handles it
      }
    }, 250);
    return () => {
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
          {query.length < 2 ? "Zacznij pisać, aby wyszukać." : "Brak wyników."}
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
