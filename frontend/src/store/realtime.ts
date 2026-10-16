import { create } from "zustand";

/**
 * Stan jedynego gniazda powiadomień (`NotificationsRealtime`). Okienka paska
 * czytają go, żeby przy zerwanym gnieździe odpytywać częściej.
 */
interface RealtimeStatus {
  connected: boolean;
  setConnected: (connected: boolean) => void;
}

export const useRealtimeStatus = create<RealtimeStatus>((set) => ({
  connected: false,
  setConnected: (connected) => set({ connected }),
}));
