"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { FileText, X } from "lucide-react";
import { useTabsStore } from "@/store/tabs";
import { cn } from "@/lib/utils";

/**
 * JobTabsRail — left-side vertical list of open recruitment "tabs", recreating
 * Traffit's "Otwarte karty" panel. The list is fed by the shared open-tabs
 * store (persisted to localStorage), so it accumulates every recruitment the
 * user opens and survives refreshes. Click a row to switch recruitments, use
 * the per-row × to close one, or the header × to close all of them.
 *
 * Rendered only on recruitment detail routes via app/jobs/layout.tsx. Self-
 * hides when there are no open job tabs. A mount gate avoids a hydration
 * mismatch between the empty server render and the populated client store.
 */
export function JobTabsRail({ className }: { className?: string }) {
  const router = useRouter();
  const pathname = usePathname();

  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const tabs = useTabsStore((s) => s.tabs);
  const closeTab = useTabsStore((s) => s.closeTab);
  const closeTabsByType = useTabsStore((s) => s.closeTabsByType);
  const activateTab = useTabsStore((s) => s.activateTab);

  const jobTabs = tabs.filter((t) => t.type === "job");

  if (!mounted || jobTabs.length === 0) return null;

  // Highlight from the URL (not just activeTabId) so it stays correct after
  // navigations the store didn't originate (back/forward, direct links).
  const match = pathname?.match(/^\/jobs\/(\d+)/);
  const currentId = match ? Number(match[1]) : null;

  const go = (url: string, id: string) => {
    activateTab(id);
    router.push(url);
  };

  return (
    <aside
      className={cn(
        "w-60 shrink-0 flex flex-col rounded-xl border border-border bg-card/60 overflow-hidden",
        className
      )}
      aria-label="Otwarte rekrutacje"
    >
      <div className="px-3 pt-3 pb-2 border-b border-border">
        <h2 className="text-base font-bold leading-tight">Rekrutacje</h2>
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-xs font-medium text-muted-foreground">
            Otwarte karty: {jobTabs.length}
          </span>
          <button
            type="button"
            onClick={() => closeTabsByType("job")}
            aria-label="Zamknij wszystkie karty"
            title="Zamknij wszystkie"
            className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto py-1.5">
        {jobTabs.map((tab) => {
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
              <FileText
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
                    ? "text-primary/70 hover:bg-primary/10 hover:text-primary"
                    : "text-transparent group-hover:text-muted-foreground hover:bg-muted hover:text-foreground"
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
