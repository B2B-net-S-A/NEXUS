import { create } from "zustand";

export type TabType = "candidate" | "job" | "client";

export interface Tab {
  id: string;
  type: TabType;
  entityId: number;
  title: string;
  url: string;
}

const MAX_TABS = 10;

interface TabsState {
  tabs: Tab[];
  activeTabId: string | null;
  maxTabsWarning: boolean;

  openTab: (type: TabType, entityId: number, title: string) => void;
  closeTab: (id: string) => void;
  activateTab: (id: string) => void;
  dismissWarning: () => void;
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

export const useTabsStore = create<TabsState>((set, get) => ({
  tabs: [],
  activeTabId: null,
  maxTabsWarning: false,

  openTab: (type, entityId, title) => {
    const id = buildTabId(type, entityId);
    const { tabs } = get();

    // Already open — just activate
    const existing = tabs.find((t) => t.id === id);
    if (existing) {
      set({ activeTabId: id });
      return;
    }

    // Max tabs guard
    if (tabs.length >= MAX_TABS) {
      set({ maxTabsWarning: true });
      return;
    }

    const newTab: Tab = {
      id,
      type,
      entityId,
      title,
      url: buildUrl(type, entityId),
    };

    set({ tabs: [...tabs, newTab], activeTabId: id });
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

  activateTab: (id) => {
    set({ activeTabId: id });
  },

  dismissWarning: () => {
    set({ maxTabsWarning: false });
  },
}));
