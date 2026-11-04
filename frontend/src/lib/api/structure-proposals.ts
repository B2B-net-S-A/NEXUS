// Propozycje struktury u klienta — „Propozycja automatu + akcept DL” (18.10.2026).
//
// Lustro tras `backend/app/api/care_structure.py` (prefiks `/api/care`):
// `GET /structure-proposals` (klienci z zakresu z licznikami),
// `GET /clients/{id}/structure-proposals`, zatwierdzenie menedżera
// (`POST …/managers`) i „Podlega pod” (`POST …/reports-to`), „Pomiń”
// (`PUT …/{id}/skip`) i „Przywróć” (`DELETE …/{id}/skip`). Pewność i źródła
// liczy serwer (`services/care/structure_rules.py`); kto zatwierdza — też
// (`can_apply_managers`, `can_apply_org`). Odczyt niczego nie zapisuje.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

import { careKeys } from "./care";
import { clientPeopleKeys } from "./client-people";

export type ProposalConfidence = "certain" | "uncertain" | "none";

export type ProposalSource =
  | "pm_email"
  | "line_manager"
  | "client_pm_name"
  | "order_contact"
  | "job_hiring_manager"
  | "same_team"
  | "same_job"
  | "order_sender"
  | "area_manager"
  | "title_same_department"
  | "title_company"
  | "hm_of_team";

export interface ProposalPerson {
  id: number;
  name: string;
  position: string | null;
  area: string | null;
}

export interface ProposalCandidate {
  contact: ProposalPerson | null;
  score: number;
  sources: { source: ProposalSource; detail: string | null }[];
}

export interface ProposalSkip {
  skipped_at: string;
  by: string | null;
}

interface ProposalBase {
  confidence: ProposalConfidence;
  proposal: ProposalCandidate | null;
  alternatives: ProposalCandidate[];
  skipped: ProposalSkip | null;
}

/** „Dodaj X jako menedżera” — osoba z pola kontraktu, której nie ma w kontaktach klienta. */
export interface NewPersonHint {
  name: string;
  source: "line_manager" | "client_pm_name";
}

export interface ManagerProposal extends ProposalBase {
  contract_id: number;
  candidate_id: number | null;
  candidate_name: string | null;
  role: string | null;
  end_date: string | null;
  manager_outside_client: boolean;
  new_person: NewPersonHint | null;
}

export interface ReportsToProposal extends ProposalBase {
  contact: ProposalPerson;
  department_text: string | null;
}

export interface StructureCounts {
  consultants: number;
  without_manager: number;
  certain: number;
  uncertain: number;
  none: number;
  skipped: number;
  open: number;
  reports_to_certain: number;
  reports_to_uncertain: number;
  new_person: number;
}

export interface ClientStructureProposals {
  client_id: number;
  client_name: string;
  counts: StructureCounts;
  managers: ManagerProposal[];
  reports_to: ReportsToProposal[];
  people: ProposalPerson[];
  can_apply_managers: boolean;
  can_apply_org: boolean;
}

export interface StructureSummaryRow extends StructureCounts {
  client_id: number;
  client_name: string;
}

export interface StructureSummary {
  items: StructureSummaryRow[];
  totals: Pick<
    StructureCounts,
    "consultants" | "without_manager" | "certain" | "uncertain" | "none" | "open" | "new_person"
  >;
}

export interface ManagerChoice {
  contract_id: number;
  contact_id?: number;
  new_person_name?: string;
  new_person_position?: string | null;
}

export interface ApplyResult {
  applied: number[];
  conflicts: { contract_id?: number; contact_id?: number; reason: string }[];
  rejected?: { contact_id: number; detail: string }[];
  client: ClientStructureProposals;
}

export const SOURCE_LABELS: Record<ProposalSource, string> = {
  pm_email: "e-mail PM na kontrakcie",
  line_manager: "„Line Manager” na kontrakcie",
  client_pm_name: "„PM po stronie klienta” na kontrakcie",
  order_contact: "osoba kontaktowa z zamówienia",
  job_hiring_manager: "hiring manager rekrutacji",
  same_team: "menedżer kolegów z zespołu",
  same_job: "menedżer kolegów z tej samej rekrutacji",
  order_sender: "nadawca maila z zamówieniem",
  area_manager: "kierownik działu z karty technologicznej",
  title_same_department: "wyższe stanowisko w tym samym dziale",
  title_company: "najwyższy szczebel u klienta",
  hm_of_team: "hiring manager rekrutacji jej konsultantów",
};

export const CONFIDENCE_LABELS: Record<ProposalConfidence, string> = {
  certain: "pewna",
  uncertain: "do sprawdzenia",
  none: "bez propozycji",
};

export const structureKeys = {
  summary: ["care", "structure-proposals"] as const,
  client: (clientId: number) => ["care", "client", clientId, "structure-proposals"] as const,
};

export function useStructureSummary(enabled = true) {
  return useQuery({
    queryKey: structureKeys.summary,
    queryFn: async () =>
      (await api.get<StructureSummary>("/api/care/structure-proposals")).data,
    enabled,
  });
}

export function useClientStructureProposals(clientId: number | null, enabled = true) {
  return useQuery({
    queryKey: structureKeys.client(clientId ?? 0),
    queryFn: async () =>
      (
        await api.get<ClientStructureProposals>(
          `/api/care/clients/${clientId}/structure-proposals`,
        )
      ).data,
    enabled: enabled && clientId !== null && Number.isFinite(clientId) && clientId > 0,
  });
}

/** Po zapisie: propozycje z odpowiedzi, drzewo i liczniki od nowa. */
function useAfterWrite(clientId: number) {
  const queryClient = useQueryClient();
  return (client: ClientStructureProposals) => {
    queryClient.setQueryData(structureKeys.client(clientId), client);
    void queryClient.invalidateQueries({ queryKey: structureKeys.summary });
    void queryClient.invalidateQueries({ queryKey: clientPeopleKeys.org(clientId) });
    void queryClient.invalidateQueries({ queryKey: careKeys.clientMap(clientId) });
  };
}

export function useApplyManagers(clientId: number) {
  const after = useAfterWrite(clientId);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (items: ManagerChoice[]) =>
      (
        await api.post<ApplyResult>(
          `/api/care/clients/${clientId}/structure-proposals/managers`,
          { items },
        )
      ).data,
    onSuccess: (result) => {
      after(result.client);
      // Menedżer kontraktu widać też w Konsultantach, na tablicy (popyt) i w Klientach
      // (audyt 22.10, F8).
      void queryClient.invalidateQueries({ queryKey: careKeys.consultants });
      void queryClient.invalidateQueries({ queryKey: ["care", "board"] });
      void queryClient.invalidateQueries({ queryKey: ["care", "clients"] });
    },
  });
}

export function useApplyReportsTo(clientId: number) {
  const after = useAfterWrite(clientId);
  return useMutation({
    mutationFn: async (items: { contact_id: number; reports_to_contact_id: number }[]) =>
      (
        await api.post<ApplyResult>(
          `/api/care/clients/${clientId}/structure-proposals/reports-to`,
          { items },
        )
      ).data,
    onSuccess: (result) => after(result.client),
  });
}

export type SkipKind = "managers" | "reports-to";

export function useSkipProposal(clientId: number) {
  const after = useAfterWrite(clientId);
  return useMutation({
    mutationFn: async ({
      kind,
      subjectId,
      proposedContactId,
      restore = false,
    }: {
      kind: SkipKind;
      subjectId: number;
      proposedContactId?: number | null;
      restore?: boolean;
    }) => {
      const url = `/api/care/clients/${clientId}/structure-proposals/${kind}/${subjectId}/skip`;
      return restore
        ? (await api.delete<ClientStructureProposals>(url)).data
        : (
            await api.put<ClientStructureProposals>(url, {
              proposed_contact_id: proposedContactId ?? null,
            })
          ).data;
    },
    onSuccess: (client) => after(client),
  });
}

/** Pozycje do „Zatwierdź pewne”: pewne, niepominięte, z osobą. */
export function certainManagerChoices(data: ClientStructureProposals): ManagerChoice[] {
  return data.managers
    .filter((row) => row.confidence === "certain" && !row.skipped && row.proposal?.contact)
    .map((row) => ({ contract_id: row.contract_id, contact_id: row.proposal!.contact!.id }));
}

/** Pozycje do „Dodaj z „Line Manager””: niepominięte z podpowiedzią nowej osoby. */
export function newPersonChoices(data: ClientStructureProposals): ManagerChoice[] {
  return data.managers
    .filter((row) => !row.skipped && row.new_person)
    .map((row) => ({ contract_id: row.contract_id, new_person_name: row.new_person!.name }));
}

export const NEW_PERSON_SOURCE_LABELS: Record<NewPersonHint["source"], string> = {
  line_manager: "„Line Manager”",
  client_pm_name: "„PM po stronie klienta”",
};

export function certainReportsToChoices(
  data: ClientStructureProposals,
): { contact_id: number; reports_to_contact_id: number }[] {
  return data.reports_to
    .filter((row) => row.confidence === "certain" && !row.skipped && row.proposal?.contact)
    .map((row) => ({
      contact_id: row.contact.id,
      reports_to_contact_id: row.proposal!.contact!.id,
    }));
}
