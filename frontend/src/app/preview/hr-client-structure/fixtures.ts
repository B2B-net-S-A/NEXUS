/**
 * Dane harnessu „Struktura u klientów” (`/preview/hr-client-structure`) —
 * wyłącznie fikcyjne. Propozycje automatu „Propozycja automatu + akcept DL”
 * (18.10.2026): Telekom Wzorcowy ma wszystkie stany (dwie pewne, jedna do
 * sprawdzenia z alternatywą, jedna bez propozycji, jedna pominięta) i dwie
 * propozycje „Podlega pod”; Bank Przykładowy — jedną pewną z pola „Line
 * Manager” (ten sam układ co harness „Struktura u klienta”), Klinika — każdy
 * ma menedżera. Te same dane zasiewają harnessy Opieki, żeby zakładka nie
 * pytała serwera.
 */

import type { QueryClient } from "@tanstack/react-query";

import {
  structureKeys,
  type ClientStructureProposals,
  type ManagerProposal,
  type ProposalCandidate,
  type ProposalPerson,
  type ReportsToProposal,
  type StructureCounts,
  type StructureSummary,
} from "@/lib/api/structure-proposals";

import { HR_CLIENTS, HR_CONSULTANTS, shiftDay } from "../hr-fixtures";

function person(id: number, name: string, position: string | null, area: string | null = null): ProposalPerson {
  return { id, name, position, area };
}

function candidate(
  contact: ProposalPerson,
  sources: ProposalCandidate["sources"],
): ProposalCandidate {
  return { contact, score: sources.length * 2 + 1, sources };
}

function manager(
  contractId: number,
  name: string,
  role: string,
  endDate: string | null,
  rest: Pick<ManagerProposal, "confidence" | "proposal"> &
    Partial<Pick<ManagerProposal, "alternatives" | "skipped" | "new_person">>,
): ManagerProposal {
  return {
    contract_id: contractId,
    candidate_id: contractId + 1000,
    candidate_name: name,
    role,
    end_date: endDate,
    manager_outside_client: false,
    new_person: null,
    alternatives: [],
    skipped: null,
    ...rest,
  };
}

function counts(managers: ManagerProposal[], org: ReportsToProposal[], consultants: number): StructureCounts {
  const live = managers.filter((m) => !m.skipped);
  const orgLive = org.filter((o) => !o.skipped);
  return {
    consultants,
    without_manager: managers.length,
    certain: live.filter((m) => m.confidence === "certain").length,
    uncertain: live.filter((m) => m.confidence === "uncertain").length,
    none: live.filter((m) => m.confidence === "none").length,
    skipped: managers.length - live.length,
    open: live.length,
    reports_to_certain: orgLive.filter((o) => o.confidence === "certain").length,
    reports_to_uncertain: orgLive.filter((o) => o.confidence === "uncertain").length,
    new_person: live.filter((m) => m.new_person && m.confidence !== "certain").length,
  };
}

// ── Telekom Wzorcowy — wszystkie stany ─────────────────────────────────────

const ROBERT = person(8301, "Robert Sieciowy", "Dyrektor Departamentu IT", "Billing");
const IWONA = person(8302, "Iwona Zespołowa", "Kierowniczka zespołu Billing", "Billing");
const TOMASZ = person(8303, "Tomasz Projektowy", "Team Lead", "Billing");
const MARTA = person(8304, "Marta Zakupowa", "Specjalistka ds. zakupów", null);

export function telecomStructure(today: string): ClientStructureProposals {
  const managers = [
    manager(9501, "Konrad Przykładowy", "Java Developer", shiftDay(today, 120), {
      confidence: "certain",
      proposal: candidate(IWONA, [
        { source: "line_manager", detail: "Iwona Zespołowa" },
        { source: "job_hiring_manager", detail: "Java Developer (Billing)" },
      ]),
    }),
    manager(9502, "Natalia Wzorcowa", "Analityczka biznesowa", shiftDay(today, 45), {
      confidence: "certain",
      proposal: candidate(IWONA, [
        { source: "same_team", detail: "Billing" },
        { source: "order_contact", detail: "Iwona Zespołowa" },
      ]),
    }),
    manager(9503, "Igor Testowy", "Tester automatyzujący", shiftDay(today, 200), {
      confidence: "uncertain",
      proposal: candidate(TOMASZ, [{ source: "job_hiring_manager", detail: "Tester automatyzujący" }]),
      alternatives: [candidate(ROBERT, [{ source: "order_sender", detail: null }])],
    }),
    manager(9504, "Lena Makietowa", "DevOps", null, {
      confidence: "none",
      proposal: null,
      new_person: { name: "Wiktor Liniowy", source: "line_manager" },
    }),
    manager(9506, "Julia Przykładowa", "Analityczka danych", shiftDay(today, 90), {
      confidence: "none",
      proposal: null,
      new_person: { name: "Wiktor Liniowy", source: "line_manager" },
    }),
    manager(9507, "Ernest Testowy", "Programista .NET", null, { confidence: "none", proposal: null }),
    manager(9505, "Oskar Fikcyjny", "Administrator baz danych", shiftDay(today, 15), {
      confidence: "uncertain",
      proposal: candidate(MARTA, [{ source: "order_sender", detail: null }]),
      skipped: { skipped_at: `${shiftDay(today, -2)}T09:15:00+02:00`, by: "Kamil Testowy" },
    }),
  ];
  const reportsTo: ReportsToProposal[] = [
    {
      contact: IWONA,
      department_text: "Billing",
      confidence: "certain",
      proposal: candidate(ROBERT, [
        { source: "title_same_department", detail: "Dyrektor Departamentu IT" },
      ]),
      alternatives: [],
      skipped: null,
    },
    {
      contact: TOMASZ,
      department_text: "Billing",
      confidence: "uncertain",
      proposal: candidate(IWONA, [{ source: "title_same_department", detail: "Kierowniczka zespołu Billing" }]),
      alternatives: [candidate(ROBERT, [{ source: "hm_of_team", detail: "Tester automatyzujący" }])],
      skipped: null,
    },
  ];
  return {
    client_id: HR_CLIENTS.telecom.id,
    client_name: HR_CLIENTS.telecom.name,
    counts: counts(managers, reportsTo, 9),
    managers,
    reports_to: reportsTo,
    people: [IWONA, MARTA, ROBERT, TOMASZ],
    can_apply_managers: true,
    can_apply_org: true,
  };
}

// ── Bank Przykładowy — ten sam układ co „Struktura u klienta” ──────────────

const LINE_MANAGER = person(8204, "Michał Liniowy", "Line Manager", null);
const ZENON = person(8201, "Zenon Dyrektorski", "CTO", "Data");
const KATARZYNA = person(8203, "Katarzyna Płatnicza", "Kierowniczka zespołu płatności", "Płatności");
const PIOTR = person(8202, "Piotr Menedżerski", "Head of Data", "Data");

export function bankStructure(): ClientStructureProposals {
  const managers = [
    manager(9405, HR_CONSULTANTS.pawel.name, "QA", null, {
      confidence: "certain",
      proposal: candidate(LINE_MANAGER, [{ source: "line_manager", detail: "Michał Liniowy" }]),
    }),
  ];
  const reportsTo: ReportsToProposal[] = [
    {
      contact: KATARZYNA,
      department_text: null,
      confidence: "uncertain",
      proposal: candidate(ZENON, [{ source: "hm_of_team", detail: "Tester automatyzujący" }]),
      alternatives: [],
      skipped: null,
    },
  ];
  return {
    client_id: HR_CLIENTS.bank.id,
    client_name: HR_CLIENTS.bank.name,
    counts: counts(managers, reportsTo, 5),
    managers,
    reports_to: reportsTo,
    people: [KATARZYNA, LINE_MANAGER, PIOTR, ZENON],
    can_apply_managers: true,
    can_apply_org: true,
  };
}

export function clinicStructure(): ClientStructureProposals {
  return {
    client_id: HR_CLIENTS.clinic.id,
    client_name: HR_CLIENTS.clinic.name,
    counts: counts([], [], 3),
    managers: [],
    reports_to: [],
    people: [person(8401, "Hanna Medyczna", "Kierowniczka IT")],
    can_apply_managers: true,
    can_apply_org: true,
  };
}

export function structureClients(today: string): ClientStructureProposals[] {
  return [telecomStructure(today), bankStructure(), clinicStructure()];
}

export function structureSummary(today: string): StructureSummary {
  const items = structureClients(today).map((client) => ({
    client_id: client.client_id,
    client_name: client.client_name,
    ...client.counts,
  }));
  const sum = (key: keyof StructureCounts) => items.reduce((total, row) => total + row[key], 0);
  return {
    items,
    totals: {
      consultants: sum("consultants"),
      without_manager: sum("without_manager"),
      certain: sum("certain"),
      uncertain: sum("uncertain"),
      none: sum("none"),
      open: sum("open"),
      new_person: sum("new_person"),
    },
  };
}

/** Zasiew propozycji dla harnessów, które montują Opiekę albo zakładkę klienta. */
export function seedStructure(client: QueryClient, today: string): void {
  client.setQueryData(structureKeys.summary, structureSummary(today));
  for (const data of structureClients(today)) {
    client.setQueryData(structureKeys.client(data.client_id), data);
  }
}
