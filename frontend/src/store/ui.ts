import { create } from "zustand";
import { persist } from "zustand/middleware";

export type UiDensity = "cozy" | "compact";
export type CandidatesView = "list" | "tiles";

interface UiStoreState {
  density: UiDensity;
  sidebarCollapsed: boolean;
  candidatesView: CandidatesView;
  /**
   * Per-entity column preferences.
   *
   * v1/v2 semantics: list of HIDDEN column ids.
   * v3 (Phase 5 columns-modal refactor) will flip this to the ordered list of
   * VISIBLE column ids when the drag-to-reorder modal lands. Do not change
   * semantics without bumping `version` and writing a migrator.
   */
  columnPreferences: Record<string, string[]>;
  setDensity: (d: UiDensity) => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (v: boolean) => void;
  setCandidatesView: (v: CandidatesView) => void;
  setColumnPreference: (entity: string, hidden: string[]) => void;
  clearColumnPreference: (entity: string) => void;
}

export const useUiStore = create<UiStoreState>()(
  persist(
    (set) => ({
      density: "cozy",
      sidebarCollapsed: false,
      candidatesView: "list",
      columnPreferences: {},
      setDensity: (density) => set({ density }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),
      setCandidatesView: (candidatesView) => set({ candidatesView }),
      setColumnPreference: (entity, hidden) =>
        set((s) => ({
          columnPreferences: { ...s.columnPreferences, [entity]: hidden },
        })),
      clearColumnPreference: (entity) =>
        set((s) => {
          const next = { ...s.columnPreferences };
          delete next[entity];
          return { columnPreferences: next };
        }),
    }),
    {
      name: "nexus-ui",
      version: 2,
      migrate: (persisted, fromVersion) => {
        const state = (persisted ?? {}) as Partial<UiStoreState>;
        if (fromVersion < 2) {
          return {
            ...state,
            candidatesView: state.candidatesView ?? "list",
          };
        }
        return state;
      },
    }
  )
);
