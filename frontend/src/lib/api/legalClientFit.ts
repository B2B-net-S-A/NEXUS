/**
 * Zgodność umów z kontraktorami z umową ramową klienta (asystent prawny,
 * część G, 25.11.2026). Lustro `backend/app/api/legal_client_fit.py`
 * (prefiks `/api/legal/client-fit`). Bramka jak treść umów ramowych:
 * „Stawki i kwoty: podgląd” u klienta z zakresu — bez niej 403 i panel się
 * nie pokazuje.
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type ClientFitStatus =
  | "never"
  | "queued"
  | "running"
  | "done"
  | "unavailable"
  | "failed"
  | "no_contract";

export type ClientFitState = "gap" | "decide" | "ok";

export type ClientFitSourceKind = "framework_contract" | "amendment";

export interface ClientFitSource {
  kind: ClientFitSourceKind;
  id: number;
  name: string;
  readable: boolean;
  note: string | null;
}

export interface ClientFitClauseDraft {
  requested_at: string;
  requested_by_name: string | null;
}

export interface ClientFitFinding {
  id: number;
  topic: string;
  topic_label: string;
  state: ClientFitState;
  summary: string;
  client_quote: string;
  client_ref: string;
  client_source: { kind: ClientFitSourceKind; id: number; name: string };
  our_quote: string | null;
  our_ref: string | null;
  next_step: string | null;
  /** Gotowe zdanie do „Dodaj do treści aneksu” (luka). */
  annex_text: string | null;
  /** Powody progu do prawnika (kara umowna, spór, skutek natychmiastowy). */
  lawyer_review: string[];
  affected_contracts: number;
  clause_draft: ClientFitClauseDraft | null;
}

export interface ClientFitResponse {
  client_id: number;
  client_name: string;
  status: ClientFitStatus;
  status_message: string | null;
  checked_at: string | null;
  stale: boolean;
  sources: ClientFitSource[];
  template_label: string;
  active_b2b_contracts: number;
  counts: Record<ClientFitState, number>;
  findings: ClientFitFinding[];
  can_request_clause_draft: boolean;
  disclaimer: string;
}

export const LEGAL_CLIENT_FIT_KEY = "legal-client-fit";

export const legalClientFitKeys = {
  client: (clientId: number) => [LEGAL_CLIENT_FIT_KEY, "client", clientId] as const,
};

const BASE = "/api/legal/client-fit/clients";

export const legalClientFitApi = {
  get: async (clientId: number): Promise<ClientFitResponse> =>
    (await api.get<ClientFitResponse>(`${BASE}/${clientId}`)).data,
  check: async (clientId: number): Promise<{ status: ClientFitStatus }> =>
    (await api.post<{ status: ClientFitStatus }>(`${BASE}/${clientId}/check`)).data,
  requestClauseDraft: async (
    clientId: number,
    findingId: number,
  ): Promise<{ clause_draft: ClientFitClauseDraft }> =>
    (
      await api.post<{ clause_draft: ClientFitClauseDraft }>(
        `${BASE}/${clientId}/findings/${findingId}/clause-draft`,
      )
    ).data,
};

/** Sprawdzenie w toku odpytuje się co 5 s, aż bieg w tle się skończy. */
export const CLIENT_FIT_POLL_MS = 5_000;

export function isClientFitRunning(data: ClientFitResponse | undefined): boolean {
  return data?.status === "queued" || data?.status === "running";
}

export function useClientFit(
  clientId: number | null | undefined,
  { poll = true }: { poll?: boolean } = {},
) {
  return useQuery({
    queryKey: legalClientFitKeys.client(clientId ?? 0),
    queryFn: () => legalClientFitApi.get(clientId as number),
    enabled: typeof clientId === "number" && clientId > 0,
    staleTime: 30_000,
    // Bez własnego `retry`: globalnie react-query nie ponawia (QueryProvider),
    // a chwilowe 502/503/504 powtarza interceptor axios — 403 nie wraca.
    refetchInterval: (query) =>
      poll && isClientFitRunning(query.state.data) ? CLIENT_FIT_POLL_MS : false,
  });
}
