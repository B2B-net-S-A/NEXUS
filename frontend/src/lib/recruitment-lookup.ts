import { keepPreviousData, useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import { countPl } from "@/lib/plural-pl";

/**
 * Lista rekrutacji do wyboru w filtrze kandydatów (`GET /api/jobs-lookup/search`).
 *
 * Jedno miejsce dla listy wyboru i chipów nad tabelą: szukanie i etykiety
 * wybranych pozycji mają osobne klucze zapytań — dwa różne pobrania pod jednym
 * kluczem podmieniałyby sobie dane.
 */
export type RecruitmentLookupStatus = "open" | "closed" | "all";

export interface RecruitmentLookupItem {
  id: number;
  title: string;
  client_id: number | null;
  client_name: string | null;
  status: "open" | "closed";
}

export interface RecruitmentLookupClient {
  id: number;
  name: string;
  jobs_count: number;
}

export interface RecruitmentLookupResponse {
  items: RecruitmentLookupItem[];
  clients: RecruitmentLookupClient[];
  total: number;
}

export const RECRUITMENT_LOOKUP_ENDPOINT = "/api/jobs-lookup/search";
export const RECRUITMENT_LOOKUP_LIMIT = 50;

export function fetchRecruitmentLookup(
  params: Record<string, unknown>,
): Promise<RecruitmentLookupResponse> {
  return api
    .get<RecruitmentLookupResponse>(RECRUITMENT_LOOKUP_ENDPOINT, {
      params,
      // Tablice jako `ids=1&ids=2` — domyślne `ids[]=` serwer pomija po cichu.
      paramsSerializer: { indexes: null },
    })
    .then((response) => response.data);
}

export function useRecruitmentSearch(
  query: string,
  status: RecruitmentLookupStatus,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["jobs-lookup-search", status, query],
    queryFn: () =>
      fetchRecruitmentLookup({
        q: query || undefined,
        status,
        limit: RECRUITMENT_LOOKUP_LIMIT,
      }),
    enabled,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

/** Nazwy wybranych rekrutacji i klientów — także spoza bieżącej strony listy. */
export function useRecruitmentLabels(recruitmentIds: number[], clientIds: number[]) {
  const ids = [...recruitmentIds].sort((a, b) => a - b);
  const clients = [...clientIds].sort((a, b) => a - b);
  return useQuery({
    queryKey: ["jobs-lookup-labels", ids, clients],
    queryFn: () => fetchRecruitmentLookup({ ids, client_ids: clients }),
    enabled: ids.length > 0 || clients.length > 0,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

/** „Bank Alfa · #2143” — dwa „Java Developer” rozróżnia klient i numer. */
export function recruitmentItemContext(item: RecruitmentLookupItem): string {
  return item.client_name ? `${item.client_name} · #${item.id}` : `#${item.id}`;
}

export function recruitmentClientLabel(name: string): string {
  return `Wszystkie rekrutacje klienta ${name}`;
}

export function recruitmentClientContext(client: RecruitmentLookupClient): string {
  return `${countPl(client.jobs_count, "rekrutacja", "rekrutacje", "rekrutacji")} · otwarte i zamknięte`;
}
