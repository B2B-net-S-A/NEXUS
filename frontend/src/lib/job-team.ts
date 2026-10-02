/**
 * Kto jest „Rekruterem” rekrutacji (decyzja Artura 02.10.2026) — lustro
 * `backend/app/services/job_team.py`.
 *
 * Rekrutacja ma trzy role: Delivery Lead, Rekruter (jedna albo kilka osób,
 * które faktycznie nad nią pracują) i Kategoria (informacyjnie). Rekruterem
 * jest prowadzący (`via: "owner"`), osoba z przypisaniem z pulpitu albo
 * automatu (`via: "assignment"`) i ręcznie dopisany współpracownik
 * (`via: "collaborator"`). Propozycja automatu (`proposed: true`) to jeszcze
 * nie praca — czeka na decyzję Head of Recruitment albo admina.
 *
 * Serwer oddaje te osoby w polu `recruiters` (wiersz listy i szczegóły
 * rekrutacji) oraz w `people` requestu na pulpicie „Requesty i obłożenie”.
 * Funkcje listy przyjmują oba kształty (`RecruiterLike`).
 */

import api from "@/lib/api";
import { manualCollaborators } from "@/lib/job-collaborators";
import { shortenPersonName } from "@/lib/job-header-subtitle";

export type RecruiterRole = "recruiter" | "sourcer";

/** Skąd osoba jest przy rekrutacji. */
export type RecruiterVia = "owner" | "assignment" | "collaborator";

export interface JobRecruiter {
  user_id: number;
  name: string;
  role: RecruiterRole;
  via: RecruiterVia;
  /** Propozycja automatu czekająca na decyzję — to jeszcze nie praca. */
  proposed: boolean;
  /** Kto przypisał (akceptacja propozycji, dodanie z pulpitu); `null` = nie wiadomo. */
  assigned_by_name: string | null;
}

/**
 * Osoba w kształcie, który przyjmują funkcje listy i `RecruiterChips`:
 * `JobRecruiter` albo osoba z pulpitu (`BoardPerson`), której `via`
 * i `assigned_by_name` starszy backend jeszcze nie oddaje.
 */
export type RecruiterLike = Omit<JobRecruiter, "via" | "assigned_by_name"> & {
  via?: RecruiterVia;
  assigned_by_name?: string | null;
};

/** Osoba z dotychczasowych pól rekrutacji (`primary_owner`, `collaborators[]`). */
interface LegacyTeamUser {
  id: number;
  name?: string | null;
  role?: string | null;
  roles?: readonly string[] | null;
  /** Tylko współpracownicy: `auto_cc` = cała kategoria, nie osoba przy rekrutacji. */
  source?: string | null;
  is_active?: boolean | null;
}

/** Pola rekrutacji (wiersz listy, szczegóły), z których czytamy Rekruterów. */
export interface JobTeamSource {
  /**
   * Od 02.10.2026: pracujący w kolejności z serwera, na końcu propozycje.
   * Listę wypełniają `GET /api/jobs` i `GET /api/jobs/{id}`; odpowiedź zapisu
   * (np. PATCH) niesie pustą niezależnie od obsady — po zapisie odśwież
   * rekrutację, zamiast czytać Rekruterów z odpowiedzi.
   */
  recruiters?: readonly JobRecruiter[] | null;
  /** Zapas dla starszego backendu i starych fixture'ów. */
  primary_owner?: LegacyTeamUser | null;
  collaborators?: readonly LegacyTeamUser[] | null;
}

/** Lustro `work_role_of`: sourcer tylko wtedy, gdy nie jest też rekruterem ani TAC. */
function workRoleOf(user: LegacyTeamUser): RecruiterRole {
  const roles = new Set<string>(user.roles ?? []);
  if (user.role) roles.add(user.role);
  return roles.has("sourcer") && !roles.has("recruiter") && !roles.has("tac")
    ? "sourcer"
    : "recruiter";
}

function legacyRecruiters(job: JobTeamSource): JobRecruiter[] {
  const people: JobRecruiter[] = [];
  const seen = new Set<number>();
  const add = (user: LegacyTeamUser, via: RecruiterVia) => {
    // Nieaktywne konto nie pracuje (ta sama reguła co filtr „Rekruter”).
    if (user.is_active === false || seen.has(user.id)) return;
    seen.add(user.id);
    people.push({
      user_id: user.id,
      name: user.name?.trim() || `#${user.id}`,
      role: workRoleOf(user),
      via,
      proposed: false,
      assigned_by_name: null,
    });
  };
  if (job.primary_owner) add(job.primary_owner, "owner");
  for (const collaborator of manualCollaborators(job.collaborators)) {
    add(collaborator, "collaborator");
  }
  return people;
}

/**
 * Osoby w roli „Rekruter”. Gdy serwer oddał `recruiters`, wygrywa ta lista
 * (także pusta — „nikt nie pracuje” to odpowiedź, nie brak danych). Bez pola
 * składamy ją z prowadzącego i ręcznie dopisanych współpracowników.
 */
export function recruitersOf(
  job: JobTeamSource | null | undefined,
): readonly JobRecruiter[] {
  if (!job) return [];
  if (Array.isArray(job.recruiters)) return job.recruiters;
  return legacyRecruiters(job);
}

/** Osoby, które pracują — bez propozycji czekających na decyzję. */
export function workingRecruiters<T extends RecruiterLike>(
  people: readonly T[],
): T[] {
  return people.filter((person) => !person.proposed);
}

/** Propozycje automatu czekające na decyzję. */
export function proposedRecruiters<T extends RecruiterLike>(
  people: readonly T[],
): T[] {
  return people.filter((person) => person.proposed);
}

/** Czy ktoś pracuje nad rekrutacją; sama propozycja automatu to za mało. */
export function hasRecruiter(people: readonly RecruiterLike[]): boolean {
  return people.some((person) => !person.proposed);
}

/** Czy rekrutacja ma pracującego prowadzącego (`jobs.recruiter_id`). */
export function hasWorkingOwner(people: readonly RecruiterLike[]): boolean {
  return people.some((person) => person.via === "owner" && !person.proposed);
}

export interface RecruitersSummary {
  /** Pierwsza pracująca osoba, skrócona („Marta K.”); `null` = nikt nie pracuje. */
  lead: string | null;
  /** Ilu pracujących poza pierwszą osobą („+N”). */
  more: number;
  /** Pełne imiona i nazwiska pracujących, w kolejności z serwera. */
  names: string[];
  /** Osoby proponowane przez automat — nie liczą się do „+N”. */
  proposedNames: string[];
  /** Podpowiedź z wszystkimi nazwiskami; pusty napis, gdy nie ma nikogo. */
  tooltip: string;
}

/** Zwarta komórka tabeli: pierwsza osoba, „+N” i podpowiedź z nazwiskami. */
export function recruitersSummary(
  people: readonly RecruiterLike[],
): RecruitersSummary {
  const names = workingRecruiters(people).map((person) => person.name);
  const proposedNames = proposedRecruiters(people).map((person) => person.name);
  const parts: string[] = [];
  if (names.length > 0) {
    parts.push(
      `${names.length === 1 ? "Rekruter" : "Rekruterzy"}: ${names.join(", ")}`,
    );
  }
  if (proposedNames.length > 0) {
    parts.push(
      `${proposedNames.length === 1 ? "Propozycja" : "Propozycje"} automatu: ${proposedNames.join(", ")}`,
    );
  }
  return {
    lead: names.length > 0 ? (shortenPersonName(names[0]) ?? names[0]) : null,
    more: Math.max(names.length - 1, 0),
    names,
    proposedNames,
    tooltip: parts.join(" · "),
  };
}

/** „przydzielił(a) Anna L.” — podpis pod osobą; `null`, gdy nie wiadomo, kto. */
export function assignedByCaption(person: RecruiterLike): string | null {
  const name = shortenPersonName(person.assigned_by_name);
  return name ? `przydzielił(a) ${name}` : null;
}

/** Co zalogowana osoba może zrobić z listą Rekruterów tej rekrutacji. */
export interface RecruiterAccess {
  /** Przydziela i zdejmuje ludzi: `can_staff` rekrutacji albo capability `job.recruiter.assign`. */
  canStaff: boolean;
  /** Rozstrzyga propozycje automatu: capability `request.proposal.decide`. */
  canDecide: boolean;
  /** Redaguje rekrutację (`can_edit`) — dopisuje i zdejmuje współpracowników. */
  canEdit: boolean;
}

/**
 * Czy pokazać „Zdejmij” przy osobie. Propozycję odrzuca tylko osoba, która
 * rozstrzyga propozycje; współpracownika zdejmuje każdy, kto redaguje
 * rekrutację; prowadzącego i osobę z przypisaniem — role przydzielające.
 */
export function canRemoveRecruiter(
  person: RecruiterLike,
  { canStaff, canDecide, canEdit }: RecruiterAccess,
): boolean {
  if (person.proposed) return canDecide;
  if (person.via === "collaborator") return canEdit || canStaff;
  return canStaff;
}

/**
 * Zdejmuje osobę z roli „Rekruter”. Role przydzielające wołają pulpit — ten
 * zdejmuje ze wszystkich trzech miejsc naraz (prowadzący, przypisanie,
 * współpracownik), a przy propozycji oznacza „odrzuć”. Pozostali mogą zdjąć
 * tylko współpracownika.
 */
export async function removeRecruiter(
  jobId: number,
  person: Pick<RecruiterLike, "user_id" | "via">,
  { canStaff }: Pick<RecruiterAccess, "canStaff">,
): Promise<void> {
  if (canStaff) {
    await api.delete(`/api/request-board/jobs/${jobId}/people/${person.user_id}`);
    return;
  }
  if (person.via === "collaborator") {
    await api.delete(`/api/jobs/${jobId}/collaborators/${person.user_id}`);
    return;
  }
  throw new Error(
    "Tę osobę może zdjąć admin, Delivery Lead albo Head of Recruitment.",
  );
}

/**
 * Dodaje osobę do roli „Rekruter”. Rola przydzielająca przy rekrutacji bez
 * pracującego prowadzącego ustawia prowadzącego; w każdym innym przypadku
 * osoba dochodzi jako współpracownik. Zwraca, jak została dodana.
 */
export async function addRecruiter(
  jobId: number,
  userId: number,
  options: { hasWorkingOwner: boolean; canStaff: boolean },
): Promise<"owner" | "collaborator"> {
  if (options.canStaff && !options.hasWorkingOwner) {
    await api.post(`/api/jobs/${jobId}/owner`, { user_id: userId });
    return "owner";
  }
  await api.post(`/api/jobs/${jobId}/collaborators`, { user_id: userId });
  return "collaborator";
}

/** „Przejmij rekrutację” — zalogowana osoba zostaje prowadzącym. */
export async function claimJob(jobId: number): Promise<void> {
  await api.post(`/api/jobs/${jobId}/claim`);
}

/** „Dołącz” — zalogowana osoba dopisuje siebie jako współpracownika. */
export async function joinJob(jobId: number, meId: number): Promise<void> {
  await api.post(`/api/jobs/${jobId}/collaborators`, { user_id: meId });
}
