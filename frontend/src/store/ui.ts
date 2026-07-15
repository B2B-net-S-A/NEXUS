import { create } from "zustand";
import { persist } from "zustand/middleware";

export type UiDensity = "cozy" | "compact";
export type CandidatesView = "list" | "tiles" | "split";
export type JobsView = "tiles" | "list";

interface UiStoreState {
  density: UiDensity;
  sidebarCollapsed: boolean;
  candidatesView: CandidatesView;
  /** Jobs list presentation — tile grid (default) vs. compact table. */
  jobsView: JobsView;
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
  setJobsView: (v: JobsView) => void;
  setColumnPreference: (entity: string, hidden: string[]) => void;
  clearColumnPreference: (entity: string) => void;
}

export const useUiStore = create<UiStoreState>()(
  persist(
    (set) => ({
      density: "cozy",
      sidebarCollapsed: false,
      candidatesView: "list",
      jobsView: "tiles",
      columnPreferences: {},
      setDensity: (density) => set({ density }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),
      setCandidatesView: (candidatesView) => set({ candidatesView }),
      setJobsView: (jobsView) => set({ jobsView }),
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
      version: 3,
      migrate: (persisted, fromVersion) => {
        let state = (persisted ?? {}) as Partial<UiStoreState>;
        if (fromVersion < 2) {
          state = { ...state, candidatesView: state.candidatesView ?? "list" };
        }
        if (fromVersion < 3) {
          state = { ...state, jobsView: state.jobsView ?? "tiles" };
        }
        return state;
      },
    }
  )
);
