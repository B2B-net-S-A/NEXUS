// Porcja dnia od Nexusa (decyzje Artura z 07.11.2026) — typy są lustrem
// `backend/app/api/review_batch.py` i `services/review_batch.py`.

import { useQuery, type QueryClient } from "@tanstack/react-query"

import api from "@/lib/api"
import { hasSectionAccess } from "@/lib/section-access"
import { useAuthStore } from "@/store/auth"

export interface ReviewBatchJob {
  job_id: number
  title: string
  /** Osoby z porcji czekające u patrzącego w tej rekrutacji. */
  pending: number
  p0: boolean
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
  jobs: ReviewBatchJob[]
  team_jobs: ReviewBatchJob[]
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

export async function addMoreFromNexus(jobId: number): Promise<number> {
  const res = await api.post<{ added: number }>(`/api/review-batch/jobs/${jobId}/more`)
  return res.data.added
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
