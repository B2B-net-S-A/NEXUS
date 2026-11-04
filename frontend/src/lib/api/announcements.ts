// „Ogłoszenia” na pulpicie (28.10.2026) — typy są lustrem
// `backend/app/api/announcements.py`.

import { useQuery, type QueryClient } from "@tanstack/react-query"

import api from "@/lib/api"
import type { AnnouncementForm } from "@/lib/announcements"
import { ANNOUNCEMENTS_POLL_MS } from "@/lib/polling"

export interface Announcement {
  id: number
  title: string
  body: string
  /** `YYYY-MM-DD`, ostatni dzień widoczności (włącznie). */
  visible_until: string
  /** Pusta lista = wszyscy. */
  audience_roles: string[]
  pinned: boolean
  important: boolean
  author_name: string | null
  created_at: string
  updated_at: string
  /** Czy ogłoszenie jest do patrzącego (publikujący widzą wszystkie). */
  for_me: boolean
  read: boolean
  /** Tylko dla publikujących: „przeczytało N z M”. */
  read_count: number | null
  recipient_count: number | null
}

export interface AnnouncementList {
  /** Nieprzeczytane nad przeczytanymi; w grupie przypięte, potem najnowsze. */
  items: Announcement[]
  /** Head of Recruitment i administrator. */
  can_publish: boolean
  audience_roles: string[]
}

export interface AnnouncementSaved {
  id: number
  notified: number
}

export const ANNOUNCEMENTS_QUERY_KEY = ["announcements"] as const

/** Panel na pulpicie i przycisk „Nowe ogłoszenie” — jedno zapytanie w cache'u. */
export function useAnnouncements() {
  return useQuery<AnnouncementList>({
    queryKey: ANNOUNCEMENTS_QUERY_KEY,
    queryFn: async () => (await api.get<AnnouncementList>("/api/announcements")).data,
    refetchInterval: ANNOUNCEMENTS_POLL_MS,
    staleTime: 30_000,
  })
}

function payload(form: AnnouncementForm) {
  return {
    title: form.title,
    body: form.body,
    visible_until: form.visibleUntil,
    audience_roles: form.audience === "all" ? [] : form.roles,
    pinned: form.pinned,
    important: form.important,
  }
}

export async function publishAnnouncement(form: AnnouncementForm): Promise<AnnouncementSaved> {
  return (await api.post<AnnouncementSaved>("/api/announcements", payload(form))).data
}

export async function editAnnouncement(id: number, form: AnnouncementForm): Promise<AnnouncementSaved> {
  return (await api.patch<AnnouncementSaved>(`/api/announcements/${id}`, payload(form))).data
}

export async function withdrawAnnouncement(id: number): Promise<AnnouncementSaved> {
  return (await api.delete<AnnouncementSaved>(`/api/announcements/${id}`)).data
}

export async function markAnnouncementRead(id: number): Promise<void> {
  await api.post(`/api/announcements/${id}/read`)
}

export function invalidateAnnouncements(qc: QueryClient): void {
  void qc.invalidateQueries({ queryKey: ANNOUNCEMENTS_QUERY_KEY })
}
