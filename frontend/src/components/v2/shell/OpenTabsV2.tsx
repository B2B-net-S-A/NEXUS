"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { X } from "lucide-react";
import { useTabsStore, Tab, TabType } from "@/store/tabs";
import { cn } from "@/lib/utils";

const TYPE_DOT: Record<TabType, string> = {
  candidate: "bg-primary",
  job: "bg-emerald-500",
  client: "bg-zinc-500",
};

const TYPE_ACTIVE_BORDER: Record<TabType, string> = {
  candidate: "bg-primary",
  job: "bg-emerald-500",
  client: "bg-zinc-500",
};

function truncate(str: string, max = 20): string {
  if (str.length <= max) return str;
  return str.slice(0, max - 1) + "…";
}

function TabPill({
  tab,
  isActive,
  onActivate,
  onClose,
}: {
  tab: Tab;
  isActive: boolean;
  onActivate: () => void;
  onClose: (e: React.MouseEvent) => void;
}) {
  return (
    <button
      onClick={onActivate}
      className={cn(
        "group relative flex items-center gap-1.5 px-3 h-8 text-sm rounded-t-md border border-b-0 transition-colors duration-150 select-none whitespace-nowrap shrink-0",
        isActive
          ? "bg-card border-border text-foreground font-medium"
          : "bg-muted/30 border-transparent text-muted-foreground hover:bg-card hover:text-foreground hover:border-border"
      )}
    >
      {isActive && (
        <span
          className={cn("absolute bottom-0 left-0 right-0 h-0.5 rounded-t", TYPE_ACTIVE_BORDER[tab.type])}
        />
      )}
      <span className={cn("w-2 h-2 rounded-full shrink-0", TYPE_DOT[tab.type])} />
      <span>{truncate(tab.title)}</span>
      <span
        role="button"
        onClick={onClose}
        aria-label="Zamknij zakładkę"
        className={cn(
          "ml-0.5 rounded p-0.5 transition-colors",
          isActive
            ? "text-muted-foreground hover:text-foreground hover:bg-muted"
            : "text-transparent group-hover:text-muted-foreground hover:text-foreground hover:bg-muted"
        )}
      >
        <X className="w-3 h-3" />
      </span>
    </button>
  );
}

export function OpenTabsV2() {
  const router = useRouter();
  const pathname = usePathname();
  const tabs = useTabsStore((s) => s.tabs);
  const activeTabId = useTabsStore((s) => s.activeTabId);
  const closeTab = useTabsStore((s) => s.closeTab);
  const activateTab = useTabsStore((s) => s.activateTab);

  // Mount gate: the store rehydrates from localStorage on the client, so the
  // first server render is empty. Render nothing until mounted to avoid a
  // hydration mismatch.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // On recruitment detail pages the left JobTabsRail replaces this bar, so we
  // hide it there to avoid showing the same open recruitments twice.
  const onJobDetail = /^\/jobs\/\d+/.test(pathname ?? "");

  // On the candidate list/detail pages the left CandidateTabsRail shows the
  // candidate tabs, so we drop candidate pills here (keeping any open job/client
  // tabs) to avoid showing the same candidates twice. Must stay in sync with
  // the showRail predicate in app/candidates/layout.tsx.
  const onCandidateRail =
    pathname === "/candidates" || /^\/candidates\/\d+/.test(pathname ?? "");
  const visibleTabs = onCandidateRail
    ? tabs.filter((t) => t.type !== "candidate")
    : tabs;

  if (!mounted || onJobDetail || visibleTabs.length === 0) return null;

  const handleActivate = (tab: Tab) => {
    activateTab(tab.id);
    router.push(tab.url);
  };

  const handleClose = (e: React.MouseEvent, tabId: string) => {
    e.stopPropagation();
    closeTab(tabId);
  };

  return (
    <div className="shrink-0 border-b border-border bg-muted/30 px-4">
      <div className="flex items-end gap-0.5 overflow-x-auto scrollbar-none py-1">
        {visibleTabs.map((tab) => (
          <TabPill
            key={tab.id}
            tab={tab}
            isActive={tab.id === activeTabId}
            onActivate={() => handleActivate(tab)}
            onClose={(e) => handleClose(e, tab.id)}
          />
        ))}
      </div>
    </div>
  );
}
