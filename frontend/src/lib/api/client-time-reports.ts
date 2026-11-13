// Raport klienta (Time for Teams) — plan Nordei N1 (`docs/rozliczenia-nordea-plan.md`).
//
// Lustro `backend/app/api/client_time_reports.py`
// (`/api/finance/settlements/time-reports…`, moduł Finanse). Godziny przychodzą
// jako tekst dziesiętny z kropką; kwoty faktury i stawka tylko przy dostępie
// do kwot klienta, inaczej `null`.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

const BASE = "/api/finance/settlements/time-reports";

export type TimeReportStatus = "ok" | "no_approval" | "waiting" | "differs" | "no_invoice" | "not_in_report" | "unmatched";
export type TimeReportCountKey = TimeReportStatus | "changed" | "all";
/** [zatwierdzone (2), złożone (1)] w przedziale T4T. */
export type WeekCell = [string, string];

export interface TimeReportVersion {
  id: number;
  version_no: number;
  received_on: string;
  file_name: string | null;
  sheet_name: string | null;
  rows_count: number;
  people_count: number;
  hours_approved: string;
  hours_submitted: string;
  counts?: Record<TimeReportStatus, number>;
}

export interface TimeReportPeriod {
  start: string;
  end: string;
}

export interface TimeReportRow {
  key: string;
  person_no: string | null;
  name: string;
  report_name: string | null;
  contract_id: number | null;
  contract_status: string | null;
  mapping: "confirmed" | "suggested" | null;
  projects: string[];
  status: TimeReportStatus;
  previous_status: TimeReportStatus | null;
  changed: boolean;
  approved: string;
  submitted: string;
  invoice_hours: string | null;
  difference: string | null;
  notes: string[];
  weeks: WeekCell[];
}

export interface TimeReportMonth {
  client_id: number;
  client_name: string;
  month: string;
  versions: TimeReportVersion[];
  version_id: number | null;
  previous_version_id: number | null;
  periods: TimeReportPeriod[];
  counts: Record<TimeReportCountKey, number>;
  rows: TimeReportRow[];
}

export interface TimeReportHistoryEntry extends TimeReportVersion {
  status: TimeReportStatus | null;
  approved: string | null;
  submitted: string | null;
  difference: string | null;
  notes: string[];
  weeks: WeekCell[];
  projects: {
    project_no: string | null;
    project_name: string | null;
    weeks: WeekCell[];
  }[];
}

export interface ExternalIdItem {
  id: number;
  kind: "client_person_no" | "project_no";
  value: string;
  source: "ksef_item" | "report_name" | "manual";
  state: "confirmed" | "suggested" | "rejected";
  valid_from: string | null;
  valid_to: string | null;
}

export interface TimeReportPerson {
  client_id: number;
  month: string;
  key: string;
  person_no: string | null;
  name: string;
  report_name: string | null;
  can_see_amounts: boolean;
  contract: {
    id: number;
    status: string;
    start_date: string | null;
    end_date: string | null;
  } | null;
  periods: TimeReportPeriod[];
  version_id: number | null;
  selected: TimeReportHistoryEntry | null;
  history: TimeReportHistoryEntry[];
  invoice: {
    hours: string | null;
    source: "net_by_rate";
    note: string | null;
    net: string | null;
    rate: string | null;
    invoices: {
      id: number;
      ksef_number: string;
      invoice_number: string | null;
      issue_date: string | null;
      nip_state: string;
      net_amount: string | null;
    }[];
  } | null;
  ids: ExternalIdItem[];
}

export interface IdsContract {
  contract_id: number;
  name: string;
  contract_status: string | null;
  start_date: string | null;
  end_date: string | null;
}

export interface TimeReportIds {
  client_id: number;
  month: string;
  version_id: number | null;
  counts: {
    confirmed: number;
    suggested: number;
    unmatched: number;
    ended: number;
    without_number: number;
  };
  suggestions: (IdsContract & {
    id: number;
    value: string;
    report_name: string | null;
  })[];
  unmatched: {
    person_no: string;
    report_name: string | null;
    hours: string;
    projects: string[];
  }[];
  ended: (IdsContract & { person_no: string; hours: string })[];
  without_number: IdsContract[];
  confirmed: (IdsContract & {
    person_no: string[];
    project_no: string[];
    sources: string[];
  })[];
}

export type UploadResult =
  | {
      needs_sheet: true;
      sheets: {
        name: string;
        rows: number;
        people: number;
        month: string | null;
      }[];
    }
  | {
      duplicate: boolean;
      version: TimeReportVersion;
      skipped_rows?: number;
      suggested?: number;
      needs_sheet?: undefined;
    };

export function useTimeReportClients(month: string) {
  return useQuery({
    queryKey: ["client-time-reports", "clients", month],
    queryFn: async () =>
      (
        await api.get<{ client_ids: number[] }>(`${BASE}/clients`, {
          params: { month },
        })
      ).data,
  });
}

export function useTimeReportMonth(clientId: number, month: string, versionId: number | null) {
  return useQuery({
    queryKey: ["client-time-reports", "month", clientId, month, versionId],
    queryFn: async () =>
      (
        await api.get<TimeReportMonth>(BASE, {
          params: {
            client_id: clientId,
            month,
            ...(versionId ? { version_id: versionId } : {}),
          },
        })
      ).data,
  });
}

export function useTimeReportPerson(clientId: number, month: string, key: string, versionId: number | null) {
  return useQuery({
    queryKey: ["client-time-reports", "person", clientId, month, key, versionId],
    queryFn: async () =>
      (
        await api.get<TimeReportPerson>(`${BASE}/person/${encodeURIComponent(key)}`, {
          params: {
            client_id: clientId,
            month,
            ...(versionId ? { version_id: versionId } : {}),
          },
        })
      ).data,
  });
}

export function useTimeReportIds(clientId: number, month: string) {
  return useQuery({
    queryKey: ["client-time-reports", "ids", clientId, month],
    queryFn: async () =>
      (
        await api.get<TimeReportIds>(`${BASE}/ids`, {
          params: { client_id: clientId, month },
        })
      ).data,
  });
}

function useInvalidate() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["client-time-reports"] });
}

export function useUploadTimeReport() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (input: { clientId: number; month: string; receivedOn: string; file: File; sheet?: string }) => {
      const form = new FormData();
      form.append("client_id", String(input.clientId));
      form.append("month", input.month);
      form.append("received_on", input.receivedOn);
      if (input.sheet) form.append("sheet", input.sheet);
      form.append("file", input.file);
      return (await api.post<UploadResult>(BASE, form)).data;
    },
    onSuccess: (result) => {
      if (!result.needs_sheet) void invalidate();
    },
  });
}

export function useFillIdsFromKsef() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (clientId: number) =>
      (
        await api.post<{
          invoices: number;
          added: number;
          updated: number;
          skipped: number;
        }>(`${BASE}/ids/fill`, null, {
          params: { client_id: clientId },
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useDecideId() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ id, approve }: { id: number; approve: boolean }) =>
      (await api.post<{ id: number; state: string }>(`${BASE}/ids/${id}/${approve ? "confirm" : "reject"}`)).data,
    onSuccess: invalidate,
  });
}

export function useAddId() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (input: { client_id: number; contract_id: number; kind: "client_person_no" | "project_no"; value: string }) =>
      (await api.post<{ id: number; state: string }>(`${BASE}/ids`, input)).data,
    onSuccess: invalidate,
  });
}
