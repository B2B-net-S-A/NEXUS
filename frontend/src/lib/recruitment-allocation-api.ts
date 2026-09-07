import { api } from "@/lib/api"

export type AllocationMode = "off" | "shadow" | "auto"
export interface Substitution {
  owner_id: number
  performer_id: number
  start_date: string
  end_date: string
  owner_name?: string
  performer_name?: string
}
export interface Workload {
  active_searches: number
  with_favorite: number
  overdue_tasks: number
  tasks_today: number
  candidate_followups: number
  inherited_recruitments: number
  inherited_tasks: number
}
export interface AllocationTeam {
  enabled: boolean
  mode: AllocationMode
  availability_fresh: boolean
  last_sync_at: string | null
  last_run_at: string | null
  sync_error: string | null
  worker_error: string | null
  people: (Workload & { user_id: number; name: string; available: boolean })[]
  delegations: Substitution[]
  issues: {
    reason?: string
    code?: string
    user_id?: number
    owner_id?: number
    performer_id?: number
    job_id?: number
  }[]
  requests: {
    id: number
    job_id: number
    title: string
    status: string
    reason: string | null
    person_name: string | null
    created_at: string
    decision: { workload_before?: Workload; competence_priority?: number } | null
  }[]
}
export interface JobAllocation {
  owner_name: string | null
  effective_name: string | null
  substitution: Substitution | null
  favorite_sourcing_paused: boolean
  reason: string | null
  decision: { workload_before?: Workload; competence_priority?: number } | null
}
export interface OnboardingTask {
  id: number
  label: string
  due_date: string | null
  owner_user_id: number
  effective_user_id: number
  substitution: Substitution | null
}
export const allocationApi = {
  team: () =>
    api.get<AllocationTeam>("/api/recruitment-allocation/team").then((r) => r.data),
  mode: (mode: AllocationMode) => api.put("/api/recruitment-allocation/mode", { mode }),
  job: (id: number) =>
    api.get<JobAllocation>(`/api/recruitment-allocation/jobs/${id}`).then((r) => r.data),
  onboarding: (after = 0) =>
    api
      .get<{
        items: OnboardingTask[]
        next_cursor: number | null
      }>("/api/recruitment-allocation/onboarding", { params: { after } })
      .then((r) => r.data),
  complete: (id: number) =>
    api.patch(`/api/recruitment-allocation/onboarding/${id}`, { status: "done" }),
}
export const allocationReason: Record<string, string> = {
  brief_not_ready: "Profil rekrutacji wymaga uzupełnienia",
  availability_stale: "Brak aktualnych danych COMPASS — automat czeka",
  availability_invalid: "Nieprawidłowe dane dostępności COMPASS — automat czeka",
  sourcing_paused: "Poszukiwania wstrzymane",
  allocation_off: "Automat zatrzymany",
  competence_missing: "Brak kompetencji na rekrutacji",
  no_eligible_person: "Brak dostępnej osoby z pasującymi kompetencjami i kanałem pracy",
  least_workload: "Najmniejsze obłożenie",
  already_owned_or_closed: "Ma prowadzącego lub została zamknięta",
  identity_missing: "Nie znaleziono konta w COMPASS",
  identity_ambiguous: "Niejednoznaczne powiązanie kont",
  substitute_missing: "Nie wskazano zastępcy",
  substitute_unmapped: "Nie można powiązać konta zastępcy",
  substitute_absent: "Zastępca także jest nieobecny",
  substitute_unavailable: "Zastępca jest niedostępny",
  substitution_conflict: "Sprzeczne zastępstwa",
  substitution_cycle: "Zastępstwo wskazuje tę samą osobę",
  substitute_role_invalid: "Zastępca nie ma wymaganych uprawnień",
  substitute_overloaded: "Zastępca ma większe obłożenie niż inna pasująca osoba",
}
