// Edycja Akademii od strony recepcji (etap 5 propozycji sprzętu, makieta „I”).
//
// Lustro `backend/app/api/academy_edition.py` (`/api/academy/editions`,
// `/api/academy/programs/{id}/editions/{yyyy-mm}`) i
// `backend/app/services/academy_edition.py`. Edycja = program i miesiąc startu;
// wiersz uczestnika liczy serwer (umowa, hotel, bilet, zestaw, protokół).
// Tu też wydanie z kreatora, które odświeża i sprzęt, i edycje.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import {
  equipmentKeys,
  type EquipmentHolder,
  type EquipmentProtocol,
  type IssueInput,
} from "@/lib/api/equipment";

export type LogisticsStatus =
  | "nie_dotyczy"
  | "do_zrobienia"
  | "zrobione"
  | "do_anulowania"
  | "anulowane";

export type ContractState =
  | "brak"
  | "dokumenty"
  | "wyslana"
  | "podpisana"
  | "rezygnacja"
  | "wykluczenie";

export type KitState = "brak" | "wydany" | "do_zwrotu" | "zwrocony";

export interface ChecklistItem {
  id: number;
  item_key: string;
  label: string;
  done: boolean;
  done_at: string | null;
  done_by: string | null;
  note: string | null;
}

export interface ChecklistSection {
  key: string;
  label: string;
  done: number;
  total: number;
  items: ChecklistItem[];
}

export interface KitItem {
  assignment_id: number;
  item_id: number;
  category: string;
  name: string;
}

export interface EditionParticipant {
  application_id: number;
  candidate_id: number;
  full_name: string;
  email: string | null;
  city: string | null;
  status: string;
  status_label: string;
  left: boolean;
  cohort_month: string | null;
  contract: { state: ContractState; at: string | null };
  hotel: LogisticsStatus;
  ticket: LogisticsStatus;
  logistics_note: string | null;
  kit: { state: KitState; items: KitItem[] };
  protocol: { id: number; number: string; status: EquipmentProtocol["status"] } | null;
}

/** Edycja = program i miesiąc startu (`key` = „2026-11”). */
export interface EditionInfo {
  program_id: number;
  program_name: string;
  cohort_month: string;
  key: string;
  starts_on: string;
  ends_on: string;
}

export interface EditionRef {
  programId: number;
  month: string;
}

export interface EditionSummary {
  participants: number;
  left: number;
  contracts_signed: number;
  kits_issued: number;
  kits_to_return: number;
  protocols_confirmed: number;
  logistics_open: number;
}

export interface EditionView {
  edition: EditionInfo;
  checklist: ChecklistSection[];
  checklist_done: number;
  checklist_total: number;
  participants: EditionParticipant[];
  summary: EditionSummary;
  can_issue: boolean;
}

export interface EditionListItem extends EditionInfo {
  participants: number;
  people: number;
}

export interface KitLineInput {
  item_id: number;
  unit_value?: string | null;
  accessories?: string | null;
}

export interface BulkIssueInput {
  protocol_date?: string | null;
  send_link: boolean;
  participants: { application_id: number; lines: KitLineInput[] }[];
}

export type BulkIssueResult =
  | {
      application_id: number;
      ok: true;
      protocol: EquipmentProtocol;
      link_url: string | null;
    }
  | { application_id: number; ok: false; status: number; message: string };

export interface BulkIssueReport {
  issued: number;
  failed: number;
  results: BulkIssueResult[];
}

export const LOGISTICS_LABELS: Record<LogisticsStatus, string> = {
  nie_dotyczy: "Nie dotyczy",
  do_zrobienia: "Do zrobienia",
  zrobione: "Jest",
  do_anulowania: "Anuluj",
  anulowane: "Anulowane",
};

export const LOGISTICS_ORDER: LogisticsStatus[] = [
  "do_zrobienia",
  "zrobione",
  "nie_dotyczy",
  "do_anulowania",
  "anulowane",
];

export const CONTRACT_LABELS: Record<ContractState, string> = {
  brak: "Brak",
  dokumenty: "Dokumenty gotowe",
  wyslana: "Wysłana",
  podpisana: "Podpisana",
  rezygnacja: "Rezygnacja",
  wykluczenie: "Wykluczenie",
};

export const KIT_LABELS: Record<KitState, string> = {
  brak: "Brak",
  wydany: "Wydany",
  do_zwrotu: "Do zwrotu",
  zwrocony: "Zwrócony",
};

const BASE = "/api/academy";

export function editionUrl({ programId, month }: EditionRef): string {
  return `${BASE}/programs/${programId}/editions/${month}`;
}

export function editionRef(edition: Pick<EditionInfo, "program_id" | "key">): EditionRef {
  return { programId: edition.program_id, month: edition.key };
}

/** Wybór domyślny: najbliższa edycja, która jeszcze się nie zaczęła albo trwa w tym miesiącu. */
export function defaultEdition<T extends Pick<EditionInfo, "key">>(
  items: readonly T[],
  today: string,
): T | null {
  const month = today.slice(0, 7);
  const upcoming = items.filter((item) => item.key >= month);
  if (upcoming.length) {
    return upcoming.reduce((best, item) => (item.key < best.key ? item : best));
  }
  return items[0] ?? null;
}

export const editionKeys = {
  all: ["academy-edition"] as const,
  list: (programId: number | null) => ["academy-edition", "list", programId] as const,
  edition: (programId: number, month: string) =>
    ["academy-edition", "edition", programId, month] as const,
  holders: (q: string) => ["academy-edition", "holders", q] as const,
};

export function useAcademyEditions(programId: number | null, enabled = true) {
  return useQuery({
    queryKey: editionKeys.list(programId),
    queryFn: async () =>
      (
        await api.get<{ items: EditionListItem[] }>(`${BASE}/editions`, {
          params: programId == null ? {} : { program_id: programId },
        })
      ).data.items,
    enabled,
  });
}

export function useAcademyEdition(ref: EditionRef | null) {
  return useQuery({
    queryKey: editionKeys.edition(ref?.programId ?? 0, ref?.month ?? ""),
    queryFn: async () => {
      if (!ref) throw new Error("Nie wybrano edycji.");
      return (await api.get<EditionView>(editionUrl(ref))).data;
    },
    enabled: ref != null,
  });
}

function useInvalidateEdition() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: editionKeys.all });
  };
}

export function useSetChecklistItem(ref: EditionRef) {
  const invalidate = useInvalidateEdition();
  return useMutation({
    mutationFn: async ({
      itemId,
      ...patch
    }: {
      itemId: number;
      done?: boolean;
      note?: string | null;
    }) =>
      (
        await api.patch<ChecklistItem>(`${editionUrl(ref)}/checklist/${itemId}`, patch)
      ).data,
    onSuccess: invalidate,
  });
}

export function useSetParticipantLogistics(ref: EditionRef) {
  const invalidate = useInvalidateEdition();
  return useMutation({
    mutationFn: async ({
      applicationId,
      ...patch
    }: {
      applicationId: number;
      hotel?: LogisticsStatus;
      ticket?: LogisticsStatus;
      note?: string | null;
    }) =>
      (
        await api.patch<{
          application_id: number;
          hotel: LogisticsStatus;
          ticket: LogisticsStatus;
          logistics_note: string | null;
        }>(`${editionUrl(ref)}/participants/${applicationId}`, patch)
      ).data,
    onSuccess: invalidate,
  });
}

/** Wydanie zestawów i wydanie z kreatora odświeżają też rejestr sprzętu. */
function useInvalidateAfterIssue() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: editionKeys.all });
    void queryClient.invalidateQueries({ queryKey: equipmentKeys.all });
    // Zakładka „Sprzęt” kontraktu czyta własny klucz.
    void queryClient.invalidateQueries({ queryKey: ["contract-equipment"] });
  };
}

export function useIssueEditionKits(ref: EditionRef) {
  const invalidate = useInvalidateAfterIssue();
  return useMutation({
    mutationFn: async (payload: BulkIssueInput) =>
      (await api.post<BulkIssueReport>(`${editionUrl(ref)}/issue`, payload)).data,
    onSuccess: invalidate,
  });
}

/** Uczestnicy Akademii w kreatorze wydania (po zaliczonym zadaniu albo z rzeczami). */
export function useAcademyHolderSearch(q: string, enabled = true) {
  const term = q.trim();
  return useQuery({
    queryKey: editionKeys.holders(term),
    queryFn: async () =>
      (
        await api.get<{ items: EquipmentHolder[] }>("/api/equipment/holders", {
          params: { q: term, kind: "academy" },
        })
      ).data.items,
    enabled: enabled && term.length >= 2,
  });
}

/** Wydanie z kreatora dla każdego posiadacza, także uczestnika Akademii. */
export function useIssueToHolder() {
  const invalidate = useInvalidateAfterIssue();
  return useMutation({
    mutationFn: async (payload: IssueInput) =>
      (
        await api.post<{ protocol: EquipmentProtocol; link_url: string | null }>(
          "/api/equipment/issue",
          payload,
        )
      ).data,
    onSuccess: invalidate,
  });
}
