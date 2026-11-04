/**
 * Zakładka klienta „Ludzie i technologie” (22.10.2026) — czyste funkcje bez
 * Reacta: widok z adresu, liczby kompletności nagłówka, karty działów
 * złożone z mapy technologii (`GET …/tech-map`) i drzewa osób
 * (`GET …/org`, krąg D11) oraz pierwsza propozycja automatu do paska
 * „Do zatwierdzenia”. Drzewo bywa niedostępne (Finanse, awaria) — wtedy
 * karty biorą menedżerów z mapy.
 */

import type {
  ClientTechMap,
  DepartmentTechnology,
  MapDepartment,
} from "@/lib/api/care";
import type {
  ClientOrg,
  FeedbackRequestBrief,
  LastFeedback,
  OrgConsultant,
  OrgPerson,
} from "@/lib/api/client-people";
import { shortPersonName } from "@/lib/candidate-followup";
import {
  SOURCE_LABELS,
  type ClientStructureProposals,
  type ManagerProposal,
  type ProposalCandidate,
  type ProposalConfidence,
  type ReportsToProposal,
} from "@/lib/api/structure-proposals";

import { gapQuestion } from "../tech-gaps";

// ── Widok ───────────────────────────────────────────────────────────────────

export type PeopleView = "dzialy" | "drzewo" | "mapa";

export const PEOPLE_VIEWS: readonly PeopleView[] = ["dzialy", "drzewo", "mapa"];

export const PEOPLE_VIEW_LABELS: Record<PeopleView, string> = {
  dzialy: "Działy",
  drzewo: "Drzewo osób",
  mapa: "Mapa (tabela)",
};

/** Dawne zakładki klienta → widok nowej zakładki (linki z powiadomień i kodu). */
export const LEGACY_TAB_VIEWS: Readonly<Record<string, PeopleView>> = {
  struktura: "drzewo",
  technologie: "mapa",
};

/**
 * Widok z adresu: `?view=` wygrywa, potem dawna zakładka (`?tab=struktura`
 * → drzewo, `?tab=technologie` → mapa), na końcu „Działy”.
 */
export function peopleViewFrom(view: string | null | undefined, tab?: string | null): PeopleView {
  const picked = PEOPLE_VIEWS.find((value) => value === view);
  if (picked) return picked;
  return (tab && LEGACY_TAB_VIEWS[tab]) || "dzialy";
}

// ── Siła technologii ────────────────────────────────────────────────────────

/** „●●○” — liczba RODZAJÓW źródeł (karty, rekrutacje, konsultanci, notatki), najwyżej 3. */
export function strengthDots(sourceCount: number): string {
  const filled = Math.max(0, Math.min(3, Math.round(sourceCount)));
  return "●".repeat(filled) + "○".repeat(3 - filled);
}

export function strengthLabel(sourceCount: number): string {
  if (sourceCount >= 3) return "trzy i więcej rodzajów źródeł";
  if (sourceCount === 2) return "dwa rodzaje źródeł";
  if (sourceCount === 1) return "jedno źródło";
  return "bez źródła";
}

// ── Karty działów ───────────────────────────────────────────────────────────

export interface DepartmentManager {
  id: number;
  name: string;
  position: string | null;
  reportsTo: string | null;
  /** Stanowisko przełożonego („CTO”) — z drzewa, gdy osoba jest u klienta. */
  reportsToPosition: string | null;
  consultants: OrgConsultant[];
  /** Liczba z mapy, gdy drzewa nie ma (konsultantów nie znamy z nazwiska). */
  consultantsCount: number;
  lastFeedback: LastFeedback | null;
  feedbackRequest: FeedbackRequestBrief | null;
}

export interface DepartmentCard {
  area: { id: number; name: string };
  managers: DepartmentManager[];
  consultants: OrgConsultant[];
  consultantsCount: number;
  technologies: DepartmentTechnology[];
  technologiesTotal: number;
  openJobs: { id: number; title: string }[];
  /** „Szukają: …” — role z otwartych rekrutacji i sygnałów „klient zatrudnia”. */
  seeking: string[];
  /** Sygnały „klient zatrudnia” działu (role i dzień rozmowy), najnowszy pierwszy. */
  hiringSignals: { roles: string[]; on: string }[];
  /** „W bazie N pasujących” — osoby z najmocniejszymi technologiami działu. */
  base: MapDepartment["base"];
  /** Luka działu do dopytania (zdania) albo `null`. */
  gap: string | null;
  lastSeen: string | null;
  /** Dział ma cokolwiek do pokazania (technologia, nasi, rekrutacja, osoby). */
  hasSignal: boolean;
}

function uniq(values: Iterable<string>): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of values) {
    const value = raw.trim();
    const key = value.toLocaleLowerCase("pl");
    if (!value || seen.has(key)) continue;
    seen.add(key);
    out.push(value);
  }
  return out;
}

function sameName(a: string | null | undefined, b: string): boolean {
  return (a ?? "").trim().toLocaleLowerCase("pl") === b.trim().toLocaleLowerCase("pl");
}

function orgPeopleByArea(org: ClientOrg | null): Map<number, OrgPerson[]> {
  const out = new Map<number, OrgPerson[]>();
  for (const department of org?.departments ?? []) {
    if (!department.area) continue;
    out.set(department.area.id, [...(out.get(department.area.id) ?? []), ...department.people]);
  }
  return out;
}

function managersFor(
  department: MapDepartment,
  people: OrgPerson[] | undefined,
  org: ClientOrg | null,
): DepartmentManager[] {
  if (org !== null) {
    const positions = new Map(
      org.departments.flatMap((d) => d.people).map((person) => [person.id, person.position]),
    );
    return (people ?? [])
      .filter((person) => person.is_manager || person.consultants.length > 0)
      .map((person) => ({
        id: person.id,
        name: person.name,
        position: person.position,
        reportsTo: person.reports_to?.name ?? null,
        reportsToPosition: person.reports_to ? (positions.get(person.reports_to.id) ?? null) : null,
        consultants: person.consultants,
        consultantsCount: person.consultants.length,
        lastFeedback: person.last_feedback,
        feedbackRequest: person.feedback_request,
      }));
  }
  return department.managers.map((manager) => ({
    id: manager.id,
    name: manager.name,
    position: manager.position,
    reportsTo: null,
    reportsToPosition: null,
    consultants: [],
    consultantsCount: manager.consultants,
    lastFeedback: null,
    feedbackRequest: null,
  }));
}

/**
 * Luka działu jako zdania — po źródle, z naszym konsultantem z działu, przy
 * którego najbliższej rozmowie trzeba dopytać (to samo pytanie stoi w oknie
 * „Rozmowa” tej osoby): „Azure Data Factory znane tylko z rozmowy
 * z konsultantem — dopytać przy rozmowie (Karolina P.).”
 */
function gapFor(map: ClientTechMap, department: MapDepartment, consultants: OrgConsultant[]): string | null {
  const who = consultants
    .map((c) => shortPersonName(c.candidate_name))
    .filter(Boolean)
    .slice(0, 2)
    .join(", ");
  const ask = who ? ` — dopytać przy najbliższej rozmowie (${who})` : "";
  const lines: string[] = [];
  for (const gap of map.gaps) {
    if (gap.kind === "area_no_source" && gap.area.id === department.area.id) {
      lines.push(`Brak źródła technologii od 18 miesięcy${ask || " — dopytać, na czym pracują"}.`);
    } else if (gap.kind === "manager_unplaced" && gap.area?.id === department.area.id) {
      lines.push(`Komu podlega ${gap.contact.name}?${ask ? `${ask}.` : ""}`);
    } else if (gap.kind === "single_source" && gap.areas.some((area) => sameName(area, department.area.name))) {
      lines.push(`${gap.name} ${gapQuestion(gap).detail}${ask}.`);
    }
  }
  return lines.length ? lines.join(" ") : null;
}

/**
 * Karty działów w kolejności mapy (serwer: po nazwie działu). Drzewo osób
 * (gdy jest) daje menedżerów naszych z „Podlega pod” i nazwiska konsultantów;
 * bez drzewa menedżerowie i liczby idą z mapy.
 */
export function departmentCards(map: ClientTechMap, org: ClientOrg | null): DepartmentCard[] {
  const byArea = orgPeopleByArea(org);
  return map.departments.map((department) => {
    const people = byArea.get(department.area.id);
    const managers = managersFor(department, people, org);
    const consultants = managers.flatMap((manager) => manager.consultants);
    const openJobs = map.open_jobs
      .filter((job) => sameName(job.area, department.area.name))
      .map((job) => ({ id: job.id, title: job.title }));
    const signals = map.signals
      .filter((signal) => sameName(signal.area, department.area.name))
      .sort((a, b) => b.on.localeCompare(a.on));
    const seeking = uniq([
      ...openJobs.map((job) => job.title),
      ...signals.flatMap((signal) => signal.roles),
    ]);
    const consultantsCount = org !== null ? consultants.length : department.consultants;
    return {
      area: department.area,
      managers,
      consultants,
      consultantsCount,
      technologies: department.technologies,
      technologiesTotal: department.technologies_total,
      openJobs,
      seeking,
      hiringSignals: signals
        .filter((signal) => signal.roles.length > 0)
        .map((signal) => ({ roles: signal.roles, on: signal.on })),
      base: department.base,
      gap: gapFor(map, department, consultants),
      lastSeen: department.last_seen,
      hasSignal:
        department.technologies.length > 0 ||
        consultantsCount > 0 ||
        openJobs.length > 0 ||
        seeking.length > 0 ||
        (people?.length ?? 0) > 0,
    };
  });
}

/** Ludzie klienta bez działu (sekcja „Bez działu” drzewa). */
export function peopleOutsideDepartments(org: ClientOrg | null): OrgPerson[] {
  return (org?.departments ?? []).filter((d) => d.area === null).flatMap((d) => d.people);
}

/** Najmocniejsze technologie działu do „Nowej rekrutacji z działu” (najwyżej 3). */
export function topSkillIds(card: Pick<DepartmentCard, "technologies">, limit = 3): number[] {
  return [...card.technologies]
    .sort((a, b) => b.source_count - a.source_count || a.name.localeCompare(b.name, "pl"))
    .slice(0, limit)
    .map((tech) => tech.skill_id);
}

// ── Kompletność wiedzy ──────────────────────────────────────────────────────

export interface Completeness {
  consultants: number;
  departmentsWithOurs: number;
  departmentsTotal: number;
  /** `null` — bez drzewa (Finanse albo awaria) nie wiemy, kto ma menedżera. */
  withManager: number | null;
  /** Najświeższe źródło mapy (ISO) albo `null`. */
  mapOn: string | null;
  requests: number | null;
}

export function completeness(map: ClientTechMap, org: ClientOrg | null): Completeness {
  const consultants = org?.consultants_count ?? map.consultants_count;
  const dates = [
    ...map.technologies.map((tech) => tech.last_seen),
    ...map.departments.map((department) => department.last_seen),
  ].filter((value): value is string => Boolean(value));
  return {
    consultants,
    departmentsWithOurs: map.departments.filter((d) => d.consultants > 0).length,
    departmentsTotal: map.departments.length,
    withManager: org ? Math.max(0, org.consultants_count - org.without_manager.length) : null,
    mapOn: dates.length ? [...dates].sort()[dates.length - 1] : null,
    requests: org ? org.requests.length : null,
  };
}

// ── „Do zatwierdzenia” ──────────────────────────────────────────────────────

export type FirstProposal =
  | { kind: "manager"; row: ManagerProposal }
  | { kind: "reports_to"; row: ReportsToProposal };

const CONFIDENCE_RANK = { certain: 0, uncertain: 1, none: 2 } as const;

/**
 * Jedna propozycja automatu na pasek: najpierw menedżer konsultanta (pewne
 * przed „do sprawdzenia”), potem „Podlega pod”. Pominięte i bez osoby nie
 * wchodzą — pasek ma dać się zatwierdzić jednym kliknięciem.
 */
export function firstProposal(data: ClientStructureProposals): FirstProposal | null {
  const managers = data.managers
    .filter((row) => !row.skipped && row.proposal?.contact)
    .sort((a, b) => CONFIDENCE_RANK[a.confidence] - CONFIDENCE_RANK[b.confidence]);
  if (managers.length) return { kind: "manager", row: managers[0] };
  const org = data.reports_to
    .filter((row) => !row.skipped && row.proposal?.contact)
    .sort((a, b) => CONFIDENCE_RANK[a.confidence] - CONFIDENCE_RANK[b.confidence]);
  if (org.length) return { kind: "reports_to", row: org[0] };
  return null;
}

const CONFIDENCE_WORDS: Record<ProposalConfidence, string> = {
  certain: "pewne",
  uncertain: "do sprawdzenia",
  none: "bez pewności",
};

/** Uzasadnienie na pasku: „pewne: wyższe stanowisko w tym samym dziale”. */
export function proposalReason(confidence: ProposalConfidence, proposal: ProposalCandidate): string {
  const sources = proposal.sources.map((s) => SOURCE_LABELS[s.source]);
  const unique = [...new Set(sources)];
  return unique.length ? `${CONFIDENCE_WORDS[confidence]}: ${unique.join(", ")}` : CONFIDENCE_WORDS[confidence];
}

/** Ile pozycji czeka w pełnym panelu propozycji (bez pominiętych). */
export function openProposalCount(data: ClientStructureProposals): number {
  return (
    data.managers.filter((row) => !row.skipped).length +
    data.reports_to.filter((row) => !row.skipped).length
  );
}
