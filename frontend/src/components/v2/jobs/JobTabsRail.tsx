"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { FileText, X, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useTabsStore } from "@/store/tabs";
import { cn } from "@/lib/utils";
import { useLocalStorageFlag } from "@/lib/use-local-storage-flag";
import {
  JOB_TABS_RAIL_COLLAPSED_DEFAULT,
  JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY,
} from "@/lib/job-tabs-rail-preferences";

/**
 * Od 1536 px rozwinięta szyna zajmuje miejsce w układzie (zapamiętany wybór).
 * Węższe okno — laptop z Windows przy skalowaniu 125–150% — ma 1280–1535 px:
 * szyna 240 px obok przypiętego menu zostawiała rekrutacji ~730 px i nagłówek
 * z Tablicą łamały się w kilka rzędów (produkcja 29.09.2026). Tam szyna jest
 * zawsze paskiem 40 px, a lista kart wysuwa się jako nakładka (bez zapisu).
 */
const WIDE_RAIL_QUERY = "(min-width: 1536px)";

function useWideRail(): boolean {
  const [wide, setWide] = useState(true);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(WIDE_RAIL_QUERY);
    const update = () => setWide(mq.matches);
    update();
    mq.addEventListener?.("change", update);
    return () => mq.removeEventListener?.("change", update);
  }, []);
  return wide;
}

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
  useEffect(() => {
    setMounted(true);
  }, []);

  // `useLocalStorageFlag` odczytuje zapisaną preferencję w swoim własnym
  // `useEffect` (patrz jego docstring) — startuje więc na domyślnej wartości
  // i tuż po zamontowaniu dociąga zapamiętaną. `mounted` wyżej zostaje jako
  // osobna bramka: ukrywa cały pasek, dopóki store otwartych kart (który NIE
  // jest per-viewport-safe na serwerze) się nie zhydratuje.
  const [collapsed, setCollapsed] = useLocalStorageFlag(
    JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY,
    JOB_TABS_RAIL_COLLAPSED_DEFAULT,
  );
  const toggleCollapsed = () => setCollapsed((prev) => !prev);
  const wide = useWideRail();
  const [overlayOpen, setOverlayOpen] = useState(false);
  const overlayRef = useRef<HTMLDivElement>(null);

  const tabs = useTabsStore((s) => s.tabs);
  const closeTab = useTabsStore((s) => s.closeTab);
  const closeTabsByType = useTabsStore((s) => s.closeTabsByType);
  const activateTab = useTabsStore((s) => s.activateTab);

  const jobTabs = tabs.filter((t) => t.type === "job");

  // Nakładka zamyka się po przejściu na inną stronę, Esc i kliknięciu obok.
  useEffect(() => {
    setOverlayOpen(false);
  }, [pathname]);
  useEffect(() => {
    if (!overlayOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOverlayOpen(false);
    };
    const onPointer = (event: MouseEvent) => {
      if (!overlayRef.current?.contains(event.target as Node)) setOverlayOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onPointer);
    };
  }, [overlayOpen]);

  if (!mounted || jobTabs.length === 0) return null;

  // Highlight from the URL (not just activeTabId) so it stays correct after
  // navigations the store didn't originate (back/forward, direct links).
  const match = pathname?.match(/^\/jobs\/(\d+)/);
  const currentId = match ? Number(match[1]) : null;

  const go = (url: string, id: string) => {
    activateTab(id);
    router.push(url);
  };

  // Collapsed: thin strip with a reopen button + count badge.
  const strip = (onToggle: () => void, stripClassName?: string) => (
      <aside
        className={cn(
          "w-10 shrink-0 flex flex-col items-center rounded-xl border border-border bg-card/60 py-2",
          stripClassName
        )}
        aria-label="Otwarte rekrutacje (zwinięte)"
      >
        <button
          type="button"
          onClick={onToggle}
          aria-label="Pokaż pasek rekrutacji"
          title="Pokaż rekrutacje"
          className="relative rounded p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <PanelLeftOpen className="h-5 w-5" />
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold leading-none text-primary-foreground">
            {jobTabs.length}
          </span>
        </button>
      </aside>
  );

  const panel = (onHide: () => void, panelClassName?: string) => (
    <aside
      className={cn(
        "w-60 shrink-0 flex flex-col rounded-xl border border-border bg-card/60 overflow-hidden",
        panelClassName
      )}
      aria-label="Otwarte rekrutacje"
    >
      <div className="px-3 pt-3 pb-2 border-b border-border">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-base font-bold leading-tight">Rekrutacje</h2>
          <button
            type="button"
            onClick={onHide}
            aria-label="Ukryj pasek rekrutacji"
            title="Ukryj"
            className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        </div>
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

  if (!wide) {
    return (
      <div ref={overlayRef} className={cn("relative w-10 shrink-0", className)}>
        {strip(() => setOverlayOpen((open) => !open))}
        {overlayOpen
          ? panel(
              () => setOverlayOpen(false),
              "absolute left-0 top-0 z-30 max-h-[calc(100dvh-7rem)] bg-card shadow-xl",
            )
          : null}
      </div>
    );
  }

  return collapsed ? strip(toggleCollapsed, className) : panel(toggleCollapsed, className);
}
