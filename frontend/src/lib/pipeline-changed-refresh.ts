/**
 * Które kolejki „CV” odświeżyć po `pipeline_changed` (27.10.2026).
 *
 * Do tej daty każdy ruch karty unieważniał cały prefiks `["board-tasks"]` —
 * u każdego członka zespołu rekrutacji i każdego admina — a ikona „CV”
 * (`/api/board-tasks/cv`, ~1 900 żądań na godzinę na prod) odpytywała serwer,
 * choć ruch zwykle jej nie dotyczył. Teraz:
 *
 * - `dl-send` i „CV” u Delivery Leada TEJ rekrutacji (`delivery_lead_id`
 *   z ramki; ramka sprzed tego pola = każdy Delivery Lead, jak dawniej),
 * - „CV” i `dl-send` u każdego, kto ma już w nich wiersz tej rekrutacji
 *   (rekruter: CV u Delivery Leada przeszło do „wysłane”; DL z portfelem
 *   klienta, choć rekrutację prowadzi kolega).
 *
 * Nowy wiersz u rekrutera przychodzi ramką tematu `cv` (gotowe auto-CV, QC
 * do poprawy), a jego własny ruch odświeża ikonę w `usePipelineMove`.
 */

import type { CvTopicResponse, DlSendQueueResponse } from "@/lib/api/boardTasks";
import { hasRole, type User } from "@/store/auth";

export interface PipelineCvRefresh {
  cv: boolean;
  dlSend: boolean;
}

function cvTopicHasJob(topic: CvTopicResponse | undefined, jobId: number): boolean {
  if (!topic) return false;
  const rows: { job_id: number }[] = [
    ...(topic.recruiter?.to_check ?? []),
    ...(topic.recruiter?.to_fix ?? []),
    ...(topic.recruiter?.with_dl ?? []),
    ...(topic.recruiter?.sent ?? []),
    ...(topic.dl?.to_send ?? []),
    ...(topic.dl?.sent_today ?? []),
  ];
  return rows.some((row) => row.job_id === jobId);
}

/**
 * `deliveryLeadIds` — wartości `delivery_lead_id` ze wszystkich ramek
 * sklejonych w jedno odświeżenie; `undefined` w zbiorze = ramka bez pola.
 */
export function pipelineCvRefresh(
  jobId: number,
  deliveryLeadIds: ReadonlySet<number | null | undefined>,
  user: Pick<User, "id" | "role" | "roles"> | null | undefined,
  cvTopic: CvTopicResponse | undefined,
  dlSend: DlSendQueueResponse | undefined,
): PipelineCvRefresh {
  // Bez konta w pamięci nie wiemy nic — odświeżamy jak dawniej.
  if (!user) return { cv: true, dlSend: true };
  const leadsThisJob =
    hasRole(user, "delivery_lead") &&
    (deliveryLeadIds.has(undefined) || deliveryLeadIds.has(user.id));
  const inCv = cvTopicHasJob(cvTopic, jobId);
  const inDlSend = (dlSend?.ready ?? []).some((row) => row.job_id === jobId);
  return {
    cv: leadsThisJob || inCv,
    dlSend: leadsThisJob || inDlSend,
  };
}
