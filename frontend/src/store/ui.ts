import { create } from "zustand";
import { persist } from "zustand/middleware";

export type UiDensity = "cozy" | "compact";

interface UiStoreState {
  density: UiDensity;
  sidebarCollapsed: boolean;
  columnPreferences: Record<string, string[]>; // per-entity hidden column ids
  setDensity: (d: UiDensity) => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (v: boolean) => void;
  setColumnPreference: (entity: string, hidden: string[]) => void;
}

export const useUiStore = create<UiStoreState>()(
  persist(
    (set) => ({
      density: "cozy",
      sidebarCollapsed: false,
      columnPreferences: {},
      setDensity: (density) => set({ density }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),
      setColumnPreference: (entity, hidden) =>
        set((s) => ({
          columnPreferences: { ...s.columnPreferences, [entity]: hidden },
        })),
    }),
    {
      name: "nexus-ui",
      version: 1,
    }
  )
);
