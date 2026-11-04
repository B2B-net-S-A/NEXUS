// Okno „Ustaw nową osobę” (0612, decyzje Artura 28.10.2026) — lustro
// `backend/app/api/people_setup.py`. Lista osób przychodzi w `/api/board-tasks`
// (`new_people`).

import { useQuery } from "@tanstack/react-query"

import api from "@/lib/api"

export interface PeopleSetupManager {
  id: number
  name: string
}

export interface PeopleSetupOptions {
  /** Przełożony żyje w „Ludziach w NEXUSIE” — bez programu kroku nie ma. */
  manager_enabled: boolean
  managers: PeopleSetupManager[]
}

export type PeopleSetupDecision = "recruiter" | "employee"

export interface PeopleSetupPayload {
  decision: PeopleSetupDecision
  first_category_id?: number | null
  second_category_ids?: number[]
  manager_user_id?: number | null
}

export const PEOPLE_SETUP_OPTIONS_QUERY_KEY = ["people-setup", "options"] as const

export function usePeopleSetupOptions(enabled: boolean) {
  return useQuery<PeopleSetupOptions>({
    queryKey: PEOPLE_SETUP_OPTIONS_QUERY_KEY,
    queryFn: async () => (await api.get<PeopleSetupOptions>("/api/people-setup/options")).data,
    enabled,
    staleTime: 60_000,
  })
}

export async function applyPeopleSetup(userId: number, payload: PeopleSetupPayload): Promise<void> {
  await api.post(`/api/people-setup/${userId}`, payload)
}
