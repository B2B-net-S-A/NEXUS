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
 *
 * „Poprzedni rekruter” (14.10.2026, `previous_recruiters`): osoby uśpione
 * przy zejściu z P1 albo zamknięciu — nie pracują, wracają przy P1
 * (`backend/app/services/job_previous_recruiters.py`).
 */

import api from "@/lib/api";
import { manualCollaborators } from "@/lib/job-collaborators";
import { shortenPersonName } from "@/lib/job-header-subtitle";

/** Skąd osoba jest przy rekrutacji. */
export type RecruiterVia = "owner" | "assignment" | "collaborator";

export interface JobRecruiter {
  user_id: number;
  name: string;
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

/** „Poprzedni rekruter” — lustro `JobPreviousRecruiterOut`. */
export interface PreviousRecruiter {
  user_id: number;
  name: string;
  via: RecruiterVia;
  /** `closed` — zamknięcie rekrutacji, `priority` — zejście z P1. */
  reason: "closed" | "priority";
  /** ISO — kiedy osoba przeszła do poprzednich. */
  parked_at: string;
  parked_by_name: string | null;
  /** Wróci przy P1: konto aktywne i rola rekrutera. */
  will_return: boolean;
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
  /** „Poprzedni rekruter” (14.10.2026); brak pola = nikt. */
  previous_recruiters?: readonly PreviousRecruiter[] | null;
  /** Zapas dla starszego backendu i starych fixture'ów. */
  primary_owner?: LegacyTeamUser | null;
  collaborators?: readonly LegacyTeamUser[] | null;
}

function legacyRecruiters(job: JobTeamSource): JobRecruiter[] {
  const people: JobRecruiter[] = [];
  // Poprzedni rekruterzy nie pracują, choć zostają w polach zespołu.
  const seen = new Set<number>(
    previousRecruitersOf(job).map((person) => person.user_id),
  );
  const add = (user: LegacyTeamUser, via: RecruiterVia) => {
    // Nieaktywne konto nie pracuje (ta sama reguła co filtr „Rekruter”).
    if (user.is_active === false || seen.has(user.id)) return;
    seen.add(user.id);
    people.push({
      user_id: user.id,
      name: user.name?.trim() || `#${user.id}`,
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

/** „Poprzedni rekruter” rekrutacji, w kolejności przeniesienia. */
export function previousRecruitersOf(
  job: JobTeamSource | null | undefined,
): readonly PreviousRecruiter[] {
  return Array.isArray(job?.previous_recruiters) ? job.previous_recruiters : [];
}

/** Czy prowadzący rekrutacji jest wśród poprzednich (uśpiony = brak prowadzącego). */
export function ownerIsPrevious(job: JobTeamSource | null | undefined): boolean {
  return previousRecruitersOf(job).some((person) => person.via === "owner");
}

/** „Anna”, „Anna i Piotr”, „Anna, Piotr i Ewa” — imiona w zdaniu. */
export function joinNames(names: readonly string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} i ${names[names.length - 1]}`;
}

/** „Usuń z poprzednich” — osoba nie wróci przy powrocie na P1. */
export async function dismissPreviousRecruiter(
  jobId: number,
  userId: number,
): Promise<void> {
  await api.delete(`/api/jobs/${jobId}/previous-recruiters/${userId}`);
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

/**
 * Osoby z `pinnedIds` na początek listy pracujących (w kolejności `pinnedIds`),
 * reszta w kolejności z serwera, propozycje na końcu. Komórka tabeli pokazuje
 * pierwsze osoby z nazwiska — dzięki temu osoba, po której się filtruje,
 * i zalogowany rekruter stoją w wierszu także wtedy, gdy są trzeci na liście
 * (zgłoszenie 12.10.2026: „po filtrze widać tylko tę główną”).
 */
export function pinRecruiters<T extends RecruiterLike>(
  people: readonly T[],
  pinnedIds: readonly (number | null | undefined)[],
): T[] {
  const order = new Map<number, number>();
  for (const id of pinnedIds) {
    if (id != null && !order.has(id)) order.set(id, order.size);
  }
  const working = workingRecruiters(people);
  const pinned = working
    .filter((person) => order.has(person.user_id))
    .sort(
      (a, b) => (order.get(a.user_id) ?? 0) - (order.get(b.user_id) ?? 0),
    );
  if (pinned.length === 0) return [...people];
  return [
    ...pinned,
    ...working.filter((person) => !order.has(person.user_id)),
    ...proposedRecruiters(people),
  ];
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
