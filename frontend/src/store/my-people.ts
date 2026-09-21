import { create } from "zustand";

/**
 * Stan otwarcia panelu „Moi ludzie". Wspólny dla przycisku w topbarze,
 * awatara, skrótu `m` i linku z dzwonka (`?people=1`) — bez persist:
 * po przeładowaniu panel startuje zamknięty.
 */
interface MyPeoplePanelState {
  open: boolean;
  openPanel: () => void;
  close: () => void;
  toggle: () => void;
}

export const useMyPeoplePanel = create<MyPeoplePanelState>((set) => ({
  open: false,
  openPanel: () => set({ open: true }),
  close: () => set({ open: false }),
  toggle: () => set((s) => ({ open: !s.open })),
}));
