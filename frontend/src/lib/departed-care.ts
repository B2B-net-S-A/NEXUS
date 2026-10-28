/**
 * Odejście rekrutera: jego kandydatów domyka Delivery Lead rekrutacji
 * (decyzje Artura 28.10.2026, backend `services/departure_care.py`).
 *
 * „Prowadzi” zostaje przy osobie, która odeszła — DL domyka w ramach
 * obowiązków, bez Ligi, KPI i premii. Tu: typy odpowiedzi, zapytania
 * i teksty wspólne dla okna „Wyłącz konto”, kafla na pulpicie, karty
 * na Tablicy i listy „Po osobach, które odeszły”.
 */

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";

/** Kolumny Tablicy żywej pary, od najbliższej klienta. */
export const CARE_COLUMNS = [
  "contract",
  "client_interview",
  "cv_sent",
  "cv_qc",
  "verified",
  "screening",
  "new",
] as const;
export type CareColumn = (typeof CARE_COLUMNS)[number];

export const CARE_COLUMN_LABELS: Record<CareColumn, string> = {
  contract: "umowa",
  client_interview: "rozmowa u klienta",
  cv_sent: "CV wysłane",
  cv_qc: "QC CV",
  verified: "zweryfikowani",
  screening: "screening",
  new: "nowi",
};

export const CARE_LINK = "/departed-care";

export interface DeparturePreviewCaretaker {
  user_id: number;
  name: string;
  via: Array<"job_dl" | "client_dl" | "hor">;
  pairs: number;
  jobs: number;
  clients: string[];
  columns: Partial<Record<CareColumn, number>>;
}

export interface DeparturePreview {
  user_id: number;
  pairs: number;
  jobs: number;
  unassigned: number;
  caretakers: DeparturePreviewCaretaker[];
}

export interface DepartedCareRow {
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  client_name: string | null;
  column: CareColumn;
  moved_at: string | null;
  caretaker_user_id: number;
  caretaker_name: string;
}

export interface DepartedCareGroup {
  departed_user_id: number;
  departed_name: string;
  since: string;
  pairs: number;
  jobs: number;
  clients: string[];
  columns: Partial<Record<CareColumn, number>>;
  rows: DepartedCareRow[];
}

export interface DepartedCareOverdue {
  user_id: number;
  name: string;
  pairs: number;
  departed: string[];
  since: string;
}

export interface DepartedCareResponse {
  groups: DepartedCareGroup[];
  total: number;
  overdue: DepartedCareOverdue[];
  escalate_after_days: number;
}

export const DEPARTED_CARE_QUERY_KEY = ["board-tasks", "departed-care"] as const;

export function useDepartedCare(enabled = true) {
  return useQuery<DepartedCareResponse>({
    queryKey: DEPARTED_CARE_QUERY_KEY,
    queryFn: () =>
      api.get<DepartedCareResponse>("/api/board-tasks/departed-care").then((r) => r.data),
    enabled,
    staleTime: 60_000,
  });
}

export function useDeparturePreview(userId: number | null) {
  return useQuery<DeparturePreview>({
    queryKey: ["admin-users", "departure-preview", userId],
    queryFn: () =>
      api
        .get<DeparturePreview>(`/api/admin/users/${userId}/departure-preview`)
        .then((r) => r.data),
    enabled: userId != null,
    staleTime: 0,
  });
}

/** „Monika Czapla” → „Monika C.”. */
export function shortName(name: string | null | undefined): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "ktoś z zespołu";
  if (parts.length === 1) return parts[0];
  return `${parts[0]} ${parts[parts.length - 1][0]}.`;
}

/** „1 osoba”, „3 osoby”, „12 osób”. */
export function peoplePhrase(count: number): string {
  if (count === 1) return "1 osoba";
  const tens = count % 100;
  if (count % 10 >= 2 && count % 10 <= 4 && (tens < 12 || tens > 14)) {
    return `${count} osoby`;
  }
  return `${count} osób`;
}

/** „1 rekrutacja”, „3 rekrutacje”, „7 rekrutacji”. */
export function jobsPhrase(count: number): string {
  if (count === 1) return "1 rekrutacja";
  const tens = count % 100;
  if (count % 10 >= 2 && count % 10 <= 4 && (tens < 12 || tens > 14)) {
    return `${count} rekrutacje`;
  }
  return `${count} rekrutacji`;
}

/** Miejscownik po „w”: „1 rekrutacji”, „7 rekrutacjach”. */
export function jobsLocative(count: number): string {
  return count === 1 ? "1 rekrutacji" : `${count} rekrutacjach`;
}

/** Liczniki kolumn od najbliższej klienta: [etykieta, liczba]. */
export function columnCounts(
  columns: Partial<Record<CareColumn, number>>,
): Array<[CareColumn, number]> {
  return CARE_COLUMNS.filter((c) => (columns[c] ?? 0) > 0).map((c) => [c, columns[c] ?? 0]);
}

export function columnsText(columns: Partial<Record<CareColumn, number>>): string {
  return columnCounts(columns)
    .map(([c, n]) => `${n} ${CARE_COLUMN_LABELS[c]}`)
    .join(" · ");
}

/** Podpis karty na Tablicy: kto odszedł i kto domyka („domykasz Ty”). */
export function cardCareLabel(
  departedName: string,
  caretakerId: number,
  caretakerName: string | null | undefined,
  viewerId: number | null | undefined,
): { departed: string; caretaker: string } {
  return {
    departed: `${shortName(departedName)} · konto wyłączone`,
    caretaker: caretakerId === viewerId ? "domykasz Ty" : `domyka ${shortName(caretakerName)}`,
  };
}
