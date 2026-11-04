import { create } from "zustand";
import type { NotificationTopic } from "@/lib/notification-topics";

/**
 * Stan jedynego gniazda powiadomień (`NotificationsRealtime`) i otwartego
 * okienka paska. Okienka czytają `connected`, żeby przy zerwanym gnieździe
 * odpytywać częściej; dymek tematu nie wyskakuje, gdy jego okienko jest
 * otwarte (`openTopic`).
 */
interface RealtimeStatus {
  connected: boolean;
  setConnected: (connected: boolean) => void;
  openTopic: NotificationTopic | null;
  setOpenTopic: (topic: NotificationTopic | null) => void;
}

export const useRealtimeStatus = create<RealtimeStatus>((set) => ({
  connected: false,
  setConnected: (connected) => set({ connected }),
  openTopic: null,
  setOpenTopic: (openTopic) => set({ openTopic }),
}));
