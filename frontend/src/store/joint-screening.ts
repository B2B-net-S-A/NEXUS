import { create } from "zustand";

/**
 * „Screening razem” z okienka „+N rekrutacja” na karcie Tablicy (14.10.2026):
 * karta zapisuje, z którymi rekrutacjami otworzyć formularz, a panel osoby
 * (`ScreeningWorkbench`) zabiera to raz przy otwarciu tej osoby. Bez persist.
 */
interface JointScreeningIntentState {
  intent: { candidateId: number; jobIds: number[] } | null;
  setIntent: (candidateId: number, jobIds: number[]) => void;
  /** Rekrutacje do zaznaczenia dla tej osoby — i czyści zamiar. */
  consume: (candidateId: number) => number[];
}

export const useJointScreeningIntent = create<JointScreeningIntentState>((set, get) => ({
  intent: null,
  setIntent: (candidateId, jobIds) => set({ intent: { candidateId, jobIds } }),
  consume: (candidateId) => {
    const intent = get().intent;
    if (!intent || intent.candidateId !== candidateId) return [];
    set({ intent: null });
    return intent.jobIds;
  },
}));
