"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { User, X, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useTabsStore } from "@/store/tabs";
import { cn } from "@/lib/utils";

const COLLAPSE_KEY = "nexus.candidateTabsRail.collapsed";

/**
 * CandidateTabsRail — left-side vertical list of recently viewed candidate
 * "tabs", the candidate counterpart to {@link JobTabsRail}. It replaces the
 * former horizontal open-tabs strip for candidates: instead of pills
 * across the top, recently opened candidates stack down the left edge of the
 * candidates list/detail pages, matching the "Rekrutacje" panel.
 *
 * Fed by the shared open-tabs store (persisted to localStorage), so it
 * accumulates every candidate the user opens and survives refreshes. Click a
 * row to jump to that candidate, use the per-row × to close one, or the header
 * × to close all. The whole rail collapses to a thin reopen strip (persisted)
 * so it can be tucked away completely — unlike the old always-on top bar.
 *
 * Rendered via app/candidates/layout.tsx on the list + detail routes. Self-
 * hides when there are no open candidate tabs. A mount gate avoids a hydration
 * mismatch between the empty server render and the populated client store.
 */
export function CandidateTabsRail({ className }: { className?: string }) {
  const router = useRouter();
  const pathname = usePathname();

  const [mounted, setMounted] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    setMounted(true);
    try {
      const stored = localStorage.getItem(COLLAPSE_KEY);
      setCollapsed(
        stored === null ? window.innerWidth < 1600 : stored === "1",
      );
    } catch {
      setCollapsed(window.innerWidth < 1600);
    }
  }, []);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        /* ignore persistence errors */
      }
      return next;
    });
  };

  const tabs = useTabsStore((s) => s.tabs);
  const closeTab = useTabsStore((s) => s.closeTab);
  const closeTabsByType = useTabsStore((s) => s.closeTabsByType);
  const activateTab = useTabsStore((s) => s.activateTab);

  const candidateTabs = tabs.filter((t) => t.type === "candidate");

  if (!mounted || candidateTabs.length === 0) return null;

  // Highlight from the URL (not just activeTabId) so it stays correct after
  // navigations the store didn't originate (back/forward, direct links).
  const match = pathname?.match(/^\/candidates\/(\d+)/);
  const currentId = match ? Number(match[1]) : null;

  const go = (url: string, id: string) => {
    activateTab(id);
    router.push(url);
  };

  // Collapsed: thin strip with a reopen button + count badge.
  if (collapsed) {
    return (
      <aside
        className={cn(
          "w-10 shrink-0 flex flex-col items-center rounded-xl border border-border bg-card/60 py-2",
          className
        )}
        aria-label="Ostatnio wyświetlani kandydaci (zwinięte)"
      >
        <button
          type="button"
          onClick={toggleCollapsed}
          aria-label="Pokaż pasek kandydatów"
          title="Pokaż kandydatów"
          className="relative rounded p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <PanelLeftOpen className="h-5 w-5" />
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold leading-none text-primary-foreground">
            {candidateTabs.length}
          </span>
        </button>
      </aside>
    );
  }

  return (
    <aside
      className={cn(
        "w-60 shrink-0 flex flex-col rounded-xl border border-border bg-card/60 overflow-hidden",
        className
      )}
      aria-label="Ostatnio wyświetlani kandydaci"
    >
      <div className="px-3 pt-3 pb-2 border-b border-border">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-base font-bold leading-tight">Kandydaci</h2>
          <button
            type="button"
            onClick={toggleCollapsed}
            aria-label="Ukryj pasek kandydatów"
            title="Ukryj"
            className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-xs font-medium text-muted-foreground">
            Ostatnio wyświetlani: {candidateTabs.length}
          </span>
          <button
            type="button"
            onClick={() => closeTabsByType("candidate")}
            aria-label="Zamknij wszystkie karty"
            title="Zamknij wszystkie"
            className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto py-1.5">
        {candidateTabs.map((tab) => {
          const isActive = currentId === tab.entityId;
          return (
            <div
              key={tab.id}
              role="button"
              tabIndex={0}
              title={tab.title}
              onClick={() => go(tab.url, tab.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  go(tab.url, tab.id);
                }
              }}
              className={cn(
                "group mx-1.5 flex cursor-pointer items-center gap-2 rounded-md py-1.5 pl-2 pr-1 transition-colors",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-foreground/80 hover:bg-muted hover:text-foreground"
              )}
            >
              <User
                className={cn(
                  "h-4 w-4 shrink-0",
                  isActive ? "text-primary" : "text-muted-foreground"
                )}
              />
              <span className="flex-1 truncate text-sm">{tab.title}</span>
              <button
                type="button"
                aria-label="Zamknij kartę"
                onClick={(e) => {
                  e.stopPropagation();
                  closeTab(tab.id);
                }}
                className={cn(
                  "shrink-0 rounded p-0.5 transition-colors",
                  isActive
                    ? "text-primary/70 hover:bg-accent hover:text-primary"
                    : "text-muted-foreground md:text-transparent md:group-hover:text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:text-foreground"
                )}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
