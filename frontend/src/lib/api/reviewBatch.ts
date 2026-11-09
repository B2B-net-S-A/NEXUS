// Porcja dnia od Nexusa (decyzje Artura z 07.11.2026) — typy są lustrem
// `backend/app/api/review_batch.py` i `services/review_batch.py`.

import { useQuery, type QueryClient } from "@tanstack/react-query"

import api from "@/lib/api"
import { pluralPl } from "@/lib/plural-pl"
import { hasSectionAccess } from "@/lib/section-access"
import type { KnownFacts } from "@/lib/new-column-queue"
import { useAuthStore } from "@/store/auth"

export interface ReviewBatchJob {
  job_id: number
  title: string
  /** Osoby z porcji czekające u patrzącego w tej rekrutacji. */
  pending: number
  p0: boolean
}

export interface ReviewBatchOpenScreening {
  job_id: number
  job_title: string
  candidate_id: number
  name: string
}

export interface ReviewBatchStatus {
  enabled: boolean
  /** Porcja dotyczy patrzącego (konto z rolą rekrutera). */
  applies: boolean
  minimum: number
  done_today: number
  pending: number
  /** Ile decyzji trzeba dziś podjąć: minimum albo cała porcja, gdy mniejsza. */
  required: number
  remaining: number
  met: boolean
  /** Niezrobione minimum teraz blokuje wyszukiwanie (wyłącznik HoR, pilot, dzień roboczy od 7:00). */
  blocks?: boolean
  /** „Do screeningu” z ostatnich 2 dni roboczych, jeszcze bez wyniku. */
  open_screenings?: number
  /** Przy niezrobionym minimum: dzisiejsze niedomknięte „Do screeningu” z porcji. */
  open_today_screenings?: ReviewBatchOpenScreening[]
  jobs: ReviewBatchJob[]
  team_jobs: ReviewBatchJob[]
  /** Ile osób dokłada „Dodaj kolejnych”: 20 w porcji, 10 przy celu wg tempa. */
  more_cards?: number
}

export interface ReviewBatchCaution {
  key: string
  label: string
  title: string
}

export interface ReviewBatchItem {
  process_id: number
  stage_id: number | null
  job_id: number
  job_title: string
  candidate_id: number
  name: string
  city: string | null
  years: number | null
  position: string | null
  score: number
  matched_must: string[]
  missing_must: string[]
  rate_from_hourly: number | null
  rate_currency: string | null
  availability_status: string | null
  cautions: ReviewBatchCaution[]
  budget_hourly: number | null
  known?: KnownFacts | null
  order_active?: boolean
  order_in_budget?: boolean
}

export interface ReviewBatchTeamRow {
  user_id: number
  name: string
  absent: boolean
  done_today: number
  /** Minimum tej osoby na dziś: rośnie o 10 po każdym zrobionym, do 50. */
  minimum: number
  required: number
  pending: number
  /** Godzina zrobienia minimum, `null` = jeszcze nie. */
  minimum_at: string | null
  screened: number
  rejected: number
  open_screenings: number
  /** Wpisy `review_batch.blocked`, jeden na 10 minut. */
  blocked_today: number
}

export interface ReviewBatchStreamsWeek {
  start: string
  system: number
  manual: number
  all: number
  complete: boolean
  found_via: Record<string, number>
}

export interface ReviewBatchTeam {
  day: string
  enabled: boolean
  minimum: number
  rows: ReviewBatchTeamRow[]
  good_before_11: number
  measured: number
  streams: {
    weeks: ReviewBatchStreamsWeek[]
    baseline_week: { system: number; manual: number; all: number }
    stop_drop_percent: number
    stop_weeks: number
    stop: boolean
  }
}

export const REVIEW_BATCH_QUERY_KEY = ["review-batch"] as const
export const REVIEW_BATCH_STATUS_KEY = [...REVIEW_BATCH_QUERY_KEY, "me"] as const
export const REVIEW_BATCH_QUEUE_KEY = [...REVIEW_BATCH_QUERY_KEY, "queue"] as const

/** Kod odpowiedzi 423, gdy rekruter szuka ręcznie przed minimum. */
export const REVIEW_BATCH_BLOCK_CODE = "REVIEW_MINIMUM_PENDING"

export function useReviewBatchStatus(options: { enabled?: boolean } = {}) {
  const readsJobs = useAuthStore((s) => hasSectionAccess(s.user, "pipeline"))
  return useQuery<ReviewBatchStatus>({
    queryKey: REVIEW_BATCH_STATUS_KEY,
    queryFn: async () => (await api.get<ReviewBatchStatus>("/api/review-batch/me")).data,
    enabled: readsJobs && (options.enabled ?? true),
    staleTime: 30_000,
    refetchInterval: 120_000,
    retry: false,
  })
}

export function useReviewBatchQueue(options: { enabled?: boolean } = {}) {
  return useQuery<{ items: ReviewBatchItem[] }>({
    queryKey: REVIEW_BATCH_QUEUE_KEY,
    queryFn: async () =>
      (await api.get<{ items: ReviewBatchItem[] }>("/api/review-batch/me/queue", {
        params: { limit: 20 },
      })).data,
    enabled: options.enabled ?? true,
    staleTime: 0,
    retry: false,
  })
}

/** Porcja zespołu dziś (HoR i admin), liczona dopiero po rozwinięciu tabeli. */
export function useReviewBatchTeam(enabled: boolean) {
  return useQuery<ReviewBatchTeam>({
    queryKey: [...REVIEW_BATCH_QUERY_KEY, "team"],
    queryFn: async () => (await api.get<ReviewBatchTeam>("/api/review-batch/team")).data,
    enabled,
    staleTime: 30_000,
    retry: false,
  })
}

export async function addMoreFromNexus(jobId: number): Promise<number> {
  const res = await api.post<{ added: number }>(`/api/review-batch/jobs/${jobId}/more`)
  return res.data.added
}

export type NewColumnTempoState =
  | { enabled: false }
  | {
      enabled: true
      tier: "quiet" | "moderate" | "hot" | "new" | "p0"
      target: number
      /** Decyzje ludzi o kartach z „Nowych” w 21 dni. */
      decisions: number
      /** Czekające karty od systemu. */
      waiting: number
      more_cards: number
      can_add_more: boolean
    }

function newColumnTempoKey(jobId: number) {
  return [...REVIEW_BATCH_QUERY_KEY, "tempo", jobId] as const
}

/** Cel kart od systemu wg tempa rekrutacji (`GET …/jobs/{id}/tempo`). */
export function useNewColumnTempo(jobId: number) {
  const readsJobs = useAuthStore((s) => hasSectionAccess(s.user, "pipeline"))
  return useQuery<NewColumnTempoState>({
    queryKey: newColumnTempoKey(jobId),
    queryFn: async () =>
      (await api.get<NewColumnTempoState>(`/api/review-batch/jobs/${jobId}/tempo`)).data,
    enabled: readsJobs,
    staleTime: 60_000,
    retry: false,
  })
}

export function invalidateNewColumnTempo(queryClient: QueryClient, jobId: number): void {
  void queryClient.invalidateQueries({ queryKey: newColumnTempoKey(jobId) })
  void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] })
  void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] })
}

/** Dymek plakietki „cel N”: skąd ten cel i kiedy kolumna się dopełnia. */
export function newColumnTargetHint(tempo: Extract<NewColumnTempoState, { enabled: true }>): string {
  const refills = tempo.tier === "hot" || tempo.tier === "new" || tempo.tier === "p0"
  const why =
    tempo.tier === "p0"
      ? "P0"
      : tempo.tier === "new"
        ? "rekrutacja do 14 dni"
        : tempo.decisions === 0
          ? "bez decyzji w 21 dni"
          : `${tempo.decisions} ${pluralPl(tempo.decisions, "decyzja", "decyzje", "decyzji")} w 21 dni`
  return `Cel ${tempo.target}: ${why}. ${refills ? "Dopełnia się po ruchu karty." : "Reszta przyciskiem."}`
}

export function invalidateReviewBatch(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: REVIEW_BATCH_QUERY_KEY })
}

/** Odpowiedź serwera to blokada porcji (423 `REVIEW_MINIMUM_PENDING`). */
export function reviewBatchBlock(
  error: unknown,
): { message: string; remaining: number; required: number } | null {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })
    ?.response
  if (response?.status !== 423) return null
  const detail = response.data?.detail as
    | { code?: string; message?: string; remaining?: number; required?: number }
    | undefined
  if (!detail || detail.code !== REVIEW_BATCH_BLOCK_CODE) return null
  return {
    message: detail.message ?? "Najpierw porcja od Nexusa.",
    remaining: Number(detail.remaining ?? 0),
    required: Number(detail.required ?? 0),
  }
}
