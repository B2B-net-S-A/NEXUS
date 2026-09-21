/** Wywołania REST Jarvisa przez wspólną instancję axios (interceptory, 401). */

import { api } from "@/lib/api";
import type {
  JarvisActionOutcome,
  JarvisConversationDetail,
  JarvisConversationSummary,
  JarvisPrefs,
  JarvisPrefsResponse,
  JarvisStatus,
} from "./types";

export const jarvisKeys = {
  status: ["jarvis", "status"] as const,
  prefs: ["jarvis", "prefs"] as const,
  conversations: ["jarvis", "conversations"] as const,
  conversation: (id: string) => ["jarvis", "conversation", id] as const,
};

export async function fetchJarvisStatus(): Promise<JarvisStatus> {
  return (await api.get<JarvisStatus>("/api/jarvis/status")).data;
}

export async function fetchJarvisPrefs(): Promise<JarvisPrefsResponse> {
  const { data } = await api.get<{ jarvis: JarvisPrefsResponse }>("/api/users/me/preferences");
  return data.jarvis;
}

export async function saveJarvisPrefs(update: Partial<JarvisPrefs>): Promise<JarvisPrefsResponse> {
  const { data } = await api.patch<{ jarvis: JarvisPrefsResponse }>("/api/users/me/preferences", {
    jarvis: update,
  });
  return data.jarvis;
}

export async function fetchConversations(): Promise<JarvisConversationSummary[]> {
  return (await api.get<JarvisConversationSummary[]>("/api/jarvis/conversations")).data;
}

export async function fetchConversation(id: string): Promise<JarvisConversationDetail> {
  return (await api.get<JarvisConversationDetail>(`/api/jarvis/conversations/${id}`)).data;
}

export async function deleteConversation(id: string): Promise<void> {
  await api.delete(`/api/jarvis/conversations/${id}`);
}

export async function confirmAction(id: string): Promise<JarvisActionOutcome> {
  return (await api.post<JarvisActionOutcome>(`/api/jarvis/actions/${id}/confirm`)).data;
}

export async function rejectAction(id: string): Promise<JarvisActionOutcome> {
  return (await api.post<JarvisActionOutcome>(`/api/jarvis/actions/${id}/reject`)).data;
}
