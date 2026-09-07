import { create } from "zustand";
import { persist } from "zustand/middleware";

export type UiDensity = "cozy" | "compact";
export type CandidatesView = "list" | "tiles";
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
  /** Pipeline kanban (04 „Pipeline" — flow C2 PR3): ukryj kolumny szablonu bez
   *  kandydatów. Globalne (nie per-job) — świadomie proste, jak `density`. */
  hideEmptyKanbanColumns: boolean;
  setDensity: (d: UiDensity) => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (v: boolean) => void;
  setCandidatesView: (v: CandidatesView) => void;
  setJobsView: (v: JobsView) => void;
  setColumnPreference: (entity: string, hidden: string[]) => void;
  clearColumnPreference: (entity: string) => void;
  setHideEmptyKanbanColumns: (v: boolean) => void;
}

export const useUiStore = create<UiStoreState>()(
  persist(
    (set) => ({
      density: "cozy",
      sidebarCollapsed: false,
      candidatesView: "list",
      jobsView: "list",
      columnPreferences: {},
      hideEmptyKanbanColumns: false,
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
      setHideEmptyKanbanColumns: (hideEmptyKanbanColumns) =>
        set({ hideEmptyKanbanColumns }),
    }),
    {
      name: "nexus-ui",
      version: 5,
      migrate: (persisted, fromVersion) => {
        let state = (persisted ?? {}) as Partial<UiStoreState>;
        if (fromVersion < 2) {
          state = { ...state, candidatesView: state.candidatesView ?? "list" };
        }
        if (fromVersion < 3) {
          state = { ...state, jobsView: state.jobsView ?? "tiles" };
        }
        if (fromVersion < 4) {
          state = {
            ...state,
            hideEmptyKanbanColumns: state.hideEmptyKanbanColumns ?? false,
          };
        }
        if (fromVersion < 5) {
          // Krok 01 „Lista rekrutacji" (flow C2, PR 4/7): widok listy z
          // mini-lejkiem i dokiem gotowości jest teraz domyślny. Jednorazowy
          // reset preferencji — do v4 domyślne „tiles" nie było odróżnialne
          // od świadomego wyboru; kafelki wracają jednym kliknięciem.
          state = { ...state, jobsView: "list" };
        }
        return state;
      },
    }
  )
);
