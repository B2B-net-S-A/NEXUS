"use client";

import { useRouter } from "next/navigation";
import { X, AlertCircle } from "lucide-react";
import { useTabsStore, Tab, TabType } from "@/store/tabs";
import { cn } from "@/lib/utils";

const TYPE_DOT: Record<TabType, string> = {
  candidate: "bg-blue-500",
  job: "bg-emerald-500",
  client: "bg-purple-500",
};

const TYPE_ACTIVE_BORDER: Record<TabType, string> = {
  candidate: "border-blue-500",
  job: "border-emerald-500",
  client: "border-purple-500",
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
        "group relative flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-t-lg border border-b-0 transition-all duration-150 select-none whitespace-nowrap flex-shrink-0",
        isActive
          ? "bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 text-gray-900 dark:text-gray-100 shadow-sm"
          : "bg-gray-50 dark:bg-gray-900 border-transparent text-gray-500 dark:text-gray-400 hover:bg-white dark:hover:bg-gray-800 hover:text-gray-800 dark:hover:text-gray-200 hover:border-gray-200 dark:hover:border-gray-700"
      )}
    >
      {isActive && (
        <span
          className={cn(
            "absolute bottom-0 left-0 right-0 h-0.5 rounded-t",
            TYPE_ACTIVE_BORDER[tab.type]
          )}
        />
      )}

      <span
        className={cn(
          "w-2 h-2 rounded-full flex-shrink-0",
          TYPE_DOT[tab.type]
        )}
      />

      <span className="font-medium">{truncate(tab.title)}</span>

      <span
        role="button"
        onClick={onClose}
        title="Zamknij zakładkę"
        className={cn(
          "ml-0.5 rounded p-0.5 transition-colors",
          isActive
            ? "text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700"
            : "text-transparent group-hover:text-gray-400 group-hover:hover:text-gray-700 hover:bg-gray-100 dark:hover:bg-gray-700"
        )}
      >
        <X className="w-3 h-3" />
      </span>
    </button>
  );
}

export function OpenTabs() {
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
    <div className="flex-shrink-0 border-b border-gray-200 dark:border-gray-700 bg-gray-50/80 dark:bg-gray-900/80 px-4">
      {maxTabsWarning && (
        <div className="flex items-center gap-2 py-1.5 text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/30 border-b border-amber-200 dark:border-amber-800 px-2 -mx-4 mb-1">
          <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
          <span>Osiągnięto limit 10 otwartych zakładek. Zamknij jedną, aby otworzyć nową.</span>
          <button
            onClick={dismissWarning}
            title="Zamknij"
            className="ml-auto text-amber-500 hover:text-amber-700"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {tabs.length > 0 && (
        <div className="flex items-end gap-0.5 overflow-x-auto scrollbar-none py-1.5">
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
