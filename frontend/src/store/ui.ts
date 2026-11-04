import { create } from "zustand";
import { persist } from "zustand/middleware";

export type CandidatesView = "list" | "tiles";
/** Rozmiar strony listy kandydatów — zapamiętany w przeglądarce. */
export type CandidatesPageSize = 20 | 50 | 100;
export const CANDIDATES_PAGE_SIZES: readonly CandidatesPageSize[] = [20, 50, 100];

interface UiStoreState {
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
  /** Liczba wierszy na stronę listy kandydatów (20 / 50 / 100, domyślnie 50). */
  candidatesPageSize: CandidatesPageSize;
  /** Ukryj postać „Moi ludzie" w rogu — wejście zostaje w topbarze. */
  hideMyPeopleBuddy: boolean;
  setHideMyPeopleBuddy: (v: boolean) => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (v: boolean) => void;
  setCandidatesView: (v: CandidatesView) => void;
  setColumnPreference: (entity: string, hidden: string[]) => void;
  clearColumnPreference: (entity: string) => void;
  setCandidatesPageSize: (v: CandidatesPageSize) => void;
}

export const useUiStore = create<UiStoreState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      candidatesView: "list",
      columnPreferences: {},
      candidatesPageSize: 50,
      hideMyPeopleBuddy: false,
      setHideMyPeopleBuddy: (hideMyPeopleBuddy) => set({ hideMyPeopleBuddy }),
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
      setCandidatesPageSize: (candidatesPageSize) => set({ candidatesPageSize }),
    }),
    {
      name: "nexus-ui",
      version: 11,
      migrate: (persisted, fromVersion) => {
        let state = (persisted ?? {}) as Partial<UiStoreState>;
        if (fromVersion < 2) {
          state = { ...state, candidatesView: state.candidatesView ?? "list" };
        }
        if (fromVersion < 6) {
          // Przegląd UX rekrutera (17.09.2026): lista kandydatów pokazuje
          // 50 wierszy na stronę (jednorazowy reset).
          state = { ...state, candidatesPageSize: 50 };
        }
        if (fromVersion < 8) {
          // 25.09.2026: lista rekrutacji ma pasek filtrów nad tabelą zamiast
          // zwijanej kolumny (v7 `jobsFiltersCollapsed`) — pole znika.
          const { jobsFiltersCollapsed: _dropped, ...rest } = state as Partial<UiStoreState> & {
            jobsFiltersCollapsed?: unknown;
          };
          state = rest;
        }
        if (fromVersion < 9) {
          // 28.09.2026: Tablica rekrutacji nie ma już przełącznika gęstości
          // (cozy/kompaktowa) — pole znika.
          const { density: _dropped, ...rest } = state as Partial<UiStoreState> & {
            density?: unknown;
          };
          state = rest;
        }
        if (fromVersion < 10) {
          // 02.10.2026: lista rekrutacji ma jeden widok (tabela) — wybór
          // „lista / kafelki” (`jobsView`, v3–v9) znika.
          const { jobsView: _dropped, ...rest } = state as Partial<UiStoreState> & {
            jobsView?: unknown;
          };
          state = rest;
        }
        if (fromVersion < 11) {
          // 25.10.2026: Tablica rekrutacji zawsze pokazuje puste kolumny —
          // przełącznik „Ukryj puste kolumny” (`hideEmptyKanbanColumns`,
          // v4–v10) znika.
          const { hideEmptyKanbanColumns: _dropped, ...rest } = state as Partial<UiStoreState> & {
            hideEmptyKanbanColumns?: unknown;
          };
          state = rest;
        }
        return state;
      },
    }
  )
);
