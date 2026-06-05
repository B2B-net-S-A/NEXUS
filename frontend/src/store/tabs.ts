import { create } from "zustand";
import { persist } from "zustand/middleware";

export type TabType = "candidate" | "job" | "client";

export interface Tab {
  id: string;
  type: TabType;
  entityId: number;
  title: string;
  url: string;
}

// High ceiling so the rail accumulates like Traffit's "Otwarte karty" instead
// of blocking at a small number. On overflow we silently evict the oldest tab
// (preferring a non-active one) rather than refusing to open the new one.
const MAX_TABS = 50;

interface TabsState {
  tabs: Tab[];
  activeTabId: string | null;

  openTab: (type: TabType, entityId: number, title: string) => void;
  closeTab: (id: string) => void;
  /** Close every tab of a given type (used by the rail's "close all"). */
  closeTabsByType: (type: TabType) => void;
  activateTab: (id: string) => void;
}

function buildTabId(type: TabType, entityId: number): string {
  return `${type}-${entityId}`;
}

function buildUrl(type: TabType, entityId: number): string {
  const map: Record<TabType, string> = {
    candidate: "/candidates",
    job: "/jobs",
    client: "/clients",
  };
  return `${map[type]}/${entityId}`;
}

export const useTabsStore = create<TabsState>()(
  persist(
    (set, get) => ({
      tabs: [],
      activeTabId: null,

      openTab: (type, entityId, title) => {
        const id = buildTabId(type, entityId);
        const { tabs, activeTabId } = get();

        // Already open — activate it and refresh the title if the entity was
        // renamed. No reordering, so the rail stays positionally stable.
        const existing = tabs.find((t) => t.id === id);
        if (existing) {
          set({
            activeTabId: id,
            tabs:
              existing.title === title
                ? tabs
                : tabs.map((t) => (t.id === id ? { ...t, title } : t)),
          });
          return;
        }

        const newTab: Tab = {
          id,
          type,
          entityId,
          title,
          url: buildUrl(type, entityId),
        };

        let next = [...tabs, newTab];
        if (next.length > MAX_TABS) {
          // Evict the oldest tab, preferring one that isn't currently active.
          const victim =
            next.find((t) => t.id !== id && t.id !== activeTabId) ??
            next.find((t) => t.id !== id);
          if (victim) next = next.filter((t) => t.id !== victim.id);
        }

        set({ tabs: next, activeTabId: id });
      },

      closeTab: (id) => {
        const { tabs, activeTabId } = get();
        const idx = tabs.findIndex((t) => t.id === id);
        if (idx === -1) return;

        const newTabs = tabs.filter((t) => t.id !== id);

        let newActiveId: string | null = activeTabId;
        if (activeTabId === id) {
          // Activate previous tab, or next if no previous
          if (newTabs.length === 0) {
            newActiveId = null;
          } else {
            const prevIdx = Math.max(0, idx - 1);
            newActiveId = newTabs[prevIdx].id;
          }
        }

        set({ tabs: newTabs, activeTabId: newActiveId });
      },

      closeTabsByType: (type) => {
        const { tabs, activeTabId } = get();
        const newTabs = tabs.filter((t) => t.type !== type);
        const activeStillOpen = newTabs.some((t) => t.id === activeTabId);
        set({ tabs: newTabs, activeTabId: activeStillOpen ? activeTabId : null });
      },

      activateTab: (id) => {
        set({ activeTabId: id });
      },
    }),
    {
      name: "nexus-open-tabs",
      version: 1,
      // Only persist the data, not the action functions.
      partialize: (s) => ({ tabs: s.tabs, activeTabId: s.activeTabId }),
    }
  )
);
