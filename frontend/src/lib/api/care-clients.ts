// Opieka · klient „Ludzie i technologie”, popyt → Delivery Lead (22.10.2026).
//
// Lustro rozszerzeń tras `backend/app/api/contract_care.py` (prefiks
// `/api/care`), z których korzysta zakładka klienta i okno „Rozmowa
// z menedżerem”:
// - `POST /clients/{id}/feedback` przyjmuje opcjonalnie `demand` (rozstrzygnięcie
//   karty „Popyt do sprawdzenia”); oceny mogą być wtedy puste, a odpowiedź dla
//   `confirmed` niesie `jobs_new_url`;
// - `GET /clients/{id}/org` może nieść `health` przy konsultancie (krąg D11).
// Bez stawek i danych o zdrowiu w treści — zdrowie relacji to poziom i zdania
// „dlaczego” policzone przez serwer.

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

import { careBoardKeys, type CareHealth } from "./care-board";
import { careKeys } from "./care";
import {
  clientPeopleKeys,
  type FeedbackPayload,
  type OrgConsultant,
} from "./client-people";

// ── Popyt → Delivery Lead ───────────────────────────────────────────────────

export type DemandOutcome = "confirmed" | "not_now" | "stale";

/**
 * Karta „Popyt do sprawdzenia” otwierająca okno „Rozmowa z menedżerem”.
 * Tablica (F1/F2) podaje klucz karty (`demand:<client>:<rozmowa>`),
 * role z rozmowy opiekuna i dział, jeśli go znamy.
 */
export interface DemandContext {
  key: string;
  roles: string[];
  area: { id: number; name: string } | null;
  /** Skąd opiekun wie („widział”, „słyszał”, „plotka”) — tylko do wyświetlenia. */
  source?: string | null;
}

export interface DemandPayload {
  key: string;
  outcome: DemandOutcome;
  role?: string | null;
  headcount?: number | null;
  /** „RRRR-MM”. */
  start_month?: string | null;
  skill_ids?: number[];
}

/**
 * `contact_id` może zniknąć wyłącznie razem z `demand` (serwer: bez obu 422).
 * Rozstrzyga popyt DL klienta albo admin — inni dostają 403 z komunikatem.
 * Bez menedżera serwer nie zakłada sesji opinii, więc oceny, przedłużenie
 * i notatka idą tylko z `contact_id`.
 */
export interface FeedbackWithDemandPayload
  extends Omit<FeedbackPayload, "contact_id" | "extension_outlook" | "note" | "scores"> {
  contact_id?: number | null;
  extension_outlook?: FeedbackPayload["extension_outlook"];
  note?: FeedbackPayload["note"];
  scores?: FeedbackPayload["scores"];
  demand?: DemandPayload | null;
}

export interface FeedbackSaveResult {
  /** Sesja opinii; `null`, gdy zapis był samym rozstrzygnięciem popytu (bez menedżera). */
  id: number | null;
  contract_ids: number[];
  /** Tylko dla `confirmed`: `/jobs/new?client=…&hm=…&skills=…&title=…`. */
  jobs_new_url?: string | null;
  /** Klucze kart popytu zamkniętych tym zapisem. */
  demand_keys?: string[];
}

export const DEMAND_OUTCOME_LABELS: Record<DemandOutcome, string> = {
  confirmed: "Potrzeba potwierdzona",
  not_now: "Nie teraz",
  stale: "Nieaktualne",
};

/** Co mówi okno po zapisie — jedno zdanie na rozstrzygnięcie. */
export const DEMAND_OUTCOME_TOASTS: Record<DemandOutcome, string> = {
  confirmed: "Potrzeba potwierdzona — otwieram nową rekrutację",
  not_now: "Zapisano „Nie teraz” — karta wróci za 30 dni",
  stale: "Zapisano — potrzeba nieaktualna",
};

/**
 * Adres nowej rekrutacji z działu klienta: `/jobs/new` czyta tylko puste pola
 * (`lib/job-new-params.ts`), a `?from=` ma pierwszeństwo.
 */
export function jobsNewHref({
  clientId,
  hmId,
  skillIds,
  title,
}: {
  clientId: number;
  hmId?: number | null;
  skillIds?: readonly number[];
  title?: string | null;
}): string {
  const params = new URLSearchParams({ client: String(clientId) });
  if (hmId != null && hmId > 0) params.set("hm", String(hmId));
  const skills = (skillIds ?? []).filter((id) => Number.isInteger(id) && id > 0);
  if (skills.length) params.set("skills", skills.join(","));
  if (title?.trim()) params.set("title", title.trim());
  // `URLSearchParams` koduje przecinek — w adresie zostaje czytelna lista id.
  return `/jobs/new?${params.toString().replace(/%2C/g, ",")}`;
}

/**
 * Zapis rozmowy z menedżerem z opcjonalnym rozstrzygnięciem popytu. Ta sama
 * trasa co „Zapisz opinię” (`useSaveClientFeedback`); po zapisie odświeża
 * drzewo, prośby o opinię i tablicę opieki (karta popytu znika).
 */
export function useSaveClientFeedbackWithDemand(clientId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: FeedbackWithDemandPayload) =>
      (
        await api.post<FeedbackSaveResult>(
          `/api/care/clients/${clientId}/feedback`,
          payload,
        )
      ).data,
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: clientPeopleKeys.org(clientId) });
      void queryClient.invalidateQueries({ queryKey: ["care", "feedback-requests"] });
      void queryClient.invalidateQueries({ queryKey: careBoardKeys.all });
      // Karta konsultanta (`["care","contract",id,"card"]`) i sprawy na tablicy.
      void queryClient.invalidateQueries({ queryKey: ["care", "contract"] });
      void queryClient.invalidateQueries({ queryKey: ["admin-cases"] });
      void queryClient.invalidateQueries({ queryKey: careKeys.clientMap(clientId) });
      for (const contractId of saved.contract_ids) {
        void queryClient.invalidateQueries({
          queryKey: clientPeopleKeys.contractFeedback(contractId),
        });
      }
    },
  });
}

// ── Zdrowie przy konsultancie w drzewie ─────────────────────────────────────

// TODO(orkiestrator): przenieść do `lib/api/client-people.ts`, gdy `GET
// /clients/{id}/org` dostanie `health` przy konsultancie (B1).
export type OrgConsultantWithHealth = OrgConsultant & { health?: CareHealth | null };

/** Zdrowie relacji konsultanta, jeśli serwer je podał (krąg D11). */
export function consultantHealth(consultant: OrgConsultant): CareHealth | null {
  return (consultant as OrgConsultantWithHealth).health ?? null;
}
