// Spotkania pary przy zamknięciu karty (zgłoszenie 09.11.2026) — typy są lustrem
// `POST/GET /api/interview-cycle/pairs/{job}/{candidate}/meetings`.

import api from "@/lib/api"
import { apiErrorMessage } from "@/lib/api-error"
import { pluralPl } from "@/lib/plural-pl"

export interface PairMeeting {
  event_id: number
  kind: "prep" | "client_interview" | "outlook"
  title: string
  start: string
  host: string | null
  /** `false` = zaproszenie z Outlooka, NEXUS może tylko poprosić prowadzącego. */
  cancellable: boolean
}

export interface PairMeetingsChoice {
  cancel: number[]
  ask: number[]
}

interface PairMeetingsClosed {
  cancelled: number[]
  asked: number[]
  failed: { event_id: number; title: string; detail: string }[]
}

export function pairMeetingsKey(jobId: number, candidateId: number) {
  return ["pair-meetings", jobId, candidateId] as const
}

export async function fetchPairMeetings(jobId: number, candidateId: number): Promise<PairMeeting[]> {
  const { data } = await api.get<PairMeeting[]>(
    `/api/interview-cycle/pairs/${jobId}/${candidateId}/meetings`,
  )
  return data
}

/** „pon 09.11, 15:00” w kalendarzu firmy. */
export function meetingWhen(start: string): string {
  const parts = new Intl.DateTimeFormat("pl-PL", {
    weekday: "short",
    day: "numeric",
    month: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Warsaw",
  }).formatToParts(new Date(start))
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? ""
  return `${part("weekday").replace(".", "")} ${part("day")}.${part("month")}, ${part("hour")}:${part("minute")}`
}

export function meetingsResultMessages(result: PairMeetingsClosed): {
  success: string | null
  error: string | null
} {
  const done = result.cancelled.length
  return {
    success: done
      ? `Odwołano ${done} ${pluralPl(done, "spotkanie", "spotkania", "spotkań")}.`
      : null,
    error: result.failed.length
      ? `Karta jest zamknięta, ale nie udało się odwołać: ${result.failed
          .map((row) => row.title)
          .join(", ")}. Odwołaj w Kalendarzu (widok Tydzień) albo poproś prowadzącego.`
      : null,
  }
}

/** Po zamknięciu karty. Błąd tutaj nie cofa ruchu, więc tylko go pokazujemy. */
export async function closePairMeetings(
  jobId: number,
  candidateId: number,
  choice: PairMeetingsChoice | null | undefined,
  toast: { showSuccess: (message: string) => void; showError: (message: string) => void },
): Promise<void> {
  if (!choice || (choice.cancel.length === 0 && choice.ask.length === 0)) return
  try {
    const { data } = await api.post<PairMeetingsClosed>(
      `/api/interview-cycle/pairs/${jobId}/${candidateId}/meetings/close`,
      { cancel_event_ids: choice.cancel, ask_event_ids: choice.ask },
    )
    const { success, error } = meetingsResultMessages(data)
    if (success) toast.showSuccess(success)
    if (error) toast.showError(error)
  } catch (error) {
    toast.showError(
      apiErrorMessage(error, "Karta jest zamknięta, ale nie udało się odwołać spotkań. Odwołaj je w Kalendarzu (widok Tydzień) albo poproś prowadzącego."),
    )
  }
}
