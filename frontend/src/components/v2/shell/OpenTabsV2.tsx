"use client";

import { useRouter } from "next/navigation";
import { X, AlertCircle } from "lucide-react";
import { useTabsStore, Tab, TabType } from "@/store/tabs";
import { cn } from "@/lib/utils";

const TYPE_DOT: Record<TabType, string> = {
  candidate: "bg-[hsl(var(--accent))]",
  job: "bg-emerald-500",
  client: "bg-plum-500",
};

const TYPE_ACTIVE_BORDER: Record<TabType, string> = {
  candidate: "bg-[hsl(var(--accent))]",
  job: "bg-emerald-500",
  client: "bg-plum-500",
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
        "group relative flex items-center gap-1.5 px-3 h-8 text-sm rounded-t-v2-s border border-b-0 transition-all duration-150 select-none whitespace-nowrap shrink-0",
        isActive
          ? "bg-[hsl(var(--bg-surface))] border-[hsl(var(--border-subtle))] text-[hsl(var(--text-title))] font-medium shadow-v2-xs"
          : "bg-[hsl(var(--bg-canvas))]/60 border-transparent text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg-surface))] hover:text-[hsl(var(--text-title))] hover:border-[hsl(var(--border-subtle))]"
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
            ? "text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text-title))] hover:bg-[hsl(var(--border-subtle))]"
            : "text-transparent group-hover:text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text-title))] hover:bg-[hsl(var(--border-subtle))]"
        )}
      >
        <X className="w-3 h-3" />
      </span>
    </button>
  );
}

export function OpenTabsV2() {
  const router = useRouter();
  const { tabs, activeTabId, maxTabsWarning, closeTab, activateTab, dismissWarning } =
    useTabsStore();

  if (tabs.length === 0 && !maxTabsWarning) return null;

  const handleActivate = (tab: Tab) => {
    activateTab(tab.id);
    router.push(tab.url);
  };

  const handleClose = (e: React.MouseEvent, tabId: string) => {
    e.stopPropagation();
    closeTab(tabId);
  };

  return (
    <div className="shrink-0 border-b border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-canvas))]/40 px-4">
      {maxTabsWarning && (
        <div className="flex items-center gap-2 py-1.5 text-xs text-[hsl(var(--accent-strong))] bg-[hsl(var(--accent-soft))] border-b border-[hsl(var(--border-subtle))] px-2 -mx-4 mb-1">
          <AlertCircle className="w-3.5 h-3.5 shrink-0" />
          <span>Osiągnięto limit 10 otwartych zakładek. Zamknij jedną, aby otworzyć nową.</span>
          <button onClick={dismissWarning} aria-label="Zamknij" className="ml-auto">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
      {tabs.length > 0 && (
        <div className="flex items-end gap-0.5 overflow-x-auto scrollbar-none py-1">
          {tabs.map((tab) => (
            <TabPill
              key={tab.id}
              tab={tab}
              isActive={tab.id === activeTabId}
              onActivate={() => handleActivate(tab)}
              onClose={(e) => handleClose(e, tab.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
