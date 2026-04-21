import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ThemeState {
  theme: "light" | "dark";
  toggleTheme: () => void;
  setTheme: (theme: "light" | "dark") => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: "light",
      toggleTheme: () => set((s) => ({ theme: s.theme === "light" ? "dark" : "light" })),
      setTheme: (theme) => set({ theme }),
    }),
    {
      name: "nexus-theme",
      version: 2,
      // Phase 0 migration: V2 ships light-only. Any persisted `dark` from v1
      // would inject `.dark` on <html> and fight v2 CSS vars while the user
      // sees v2 pages. Reset stale dark → light; v1 users can re-toggle.
      migrate: (persistedState, version) => {
        const state = persistedState as Partial<ThemeState> | undefined;
        if (version < 2 && state?.theme === "dark") {
          return { ...state, theme: "light" };
        }
        return state;
      },
    }
  )
);
