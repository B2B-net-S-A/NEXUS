// Okno „Rozmowa” (decyzja 4 z 22.10.2026) — stan formularza i budowa ciała
// `POST /api/care/contracts/{id}/conversations` bez Reacta, z testami.
//
// Zasady:
// - „Co u klienta” idzie do serwera TYLKO, gdy opiekun coś w tej sekcji
//   ruszył („bez zmian” albo „zmień”) — inaczej `client_state: null` i karta
//   technologiczna się nie zapisuje;
// - pola sekcji „zmień” wchodzą do `changes`, „bez zmian” tylko potwierdza;
// - odpowiedzi na pytania z mapy i sprawy bez treści są pomijane;
// - bez danych o zdrowiu i bez stawek — okno o nie nie pyta.

import type { CaseArea } from "@/lib/api/admin-cases";
import type {
  CadenceLevel,
  CareChannel,
  ClientQuestion,
  ClientStateChanges,
  ClientStatePayload,
  ConversationCasePayload,
  ConversationPayload,
  GapAnswerPayload,
  HiringSource,
} from "@/lib/api/care";
import { countPl } from "@/lib/plural-pl";

/** Najwięcej spraw z jednej rozmowy (limit serwera). */
export const MAX_CONVERSATION_CASES = 5;

export interface PickedName {
  /** `null` = nazwa wpisana tekstem (spoza słownika). */
  id: number | null;
  name: string;
}

export interface TalkForm {
  occurredOn: string;
  channel: CareChannel;
  /** „Jak mu się pracuje” 1–5; `null` = bez oceny. */
  satisfaction: number | null;
  note: string;
  attritionRisk: boolean;
  wantsChange: boolean;
  projectEnd: boolean;
  projectEndOn: string;
  clientHiring: boolean;
  hiringNote: string;
  hiringSource: HiringSource | null;
  followUp: string;
}

export type StateRow = "area" | "manager" | "team" | "technologies" | "vendors" | "project_end";
export type StateMode = "same" | "change";

export const STATE_ROWS: StateRow[] = [
  "area",
  "manager",
  "team",
  "technologies",
  "vendors",
  "project_end",
];

export const STATE_ROW_LABELS: Record<StateRow, string> = {
  area: "Dział",
  manager: "Menedżer",
  team: "Zespół",
  technologies: "Technologie",
  vendors: "Inni dostawcy",
  project_end: "Koniec projektu",
};

export interface ClientStateForm {
  modes: Partial<Record<StateRow, StateMode>>;
  /** `"new"` = nowy dział z `newAreaName`. */
  areaId: number | "new" | null;
  newAreaName: string;
  managerContactId: number | null;
  teamSize: string;
  teamExternals: string;
  skills: PickedName[];
  vendors: PickedName[];
  /** `YYYY-MM`; pusty = „nie wiadomo” (czyści koniec projektu). */
  projectEndMonth: string;
}

export interface GapAnswerForm {
  reportsToContactId: number | null;
  skills: PickedName[];
  note: string;
}

export interface CaseDraft {
  title: string;
  area: CaseArea;
  assigneeUserId: number | null;
  dueOn: string;
}

export function emptyTalk(today: string): TalkForm {
  return {
    occurredOn: today,
    channel: "phone",
    satisfaction: null,
    note: "",
    attritionRisk: false,
    wantsChange: false,
    projectEnd: false,
    projectEndOn: "",
    clientHiring: false,
    hiringNote: "",
    hiringSource: null,
    followUp: "",
  };
}

export function emptyClientState(): ClientStateForm {
  return {
    modes: {},
    areaId: null,
    newAreaName: "",
    managerContactId: null,
    teamSize: "",
    teamExternals: "",
    skills: [],
    vendors: [],
    projectEndMonth: "",
  };
}

export function emptyGapAnswer(): GapAnswerForm {
  return { reportsToContactId: null, skills: [], note: "" };
}

export function emptyCase(): CaseDraft {
  return { title: "", area: "administration", assigneeUserId: null, dueOn: "" };
}

/** Odstęp rytmu w dniach — do podpowiedzi „Następny kontakt”. Kamienie i wstrzymany: brak. */
export const CADENCE_INTERVAL_DAYS: Partial<Record<CadenceLevel, number>> = {
  biweekly: 14,
  monthly: 30,
  quarterly: 91,
};

function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** Podpowiedź „Następny kontakt” z rytmu: data rozmowy + odstęp rytmu. */
export function suggestFollowUp(
  level: CadenceLevel | null | undefined,
  occurredOn: string,
): string | null {
  if (!level || !/^\d{4}-\d{2}-\d{2}$/.test(occurredOn)) return null;
  const days = CADENCE_INTERVAL_DAYS[level];
  return days ? addDays(occurredOn, days) : null;
}

function hasText(value: string): boolean {
  return value.trim().length > 0;
}

/** Wiersze „Co u klienta” ruszone przez opiekuna; pusty = sekcja nie idzie do serwera. */
export function touchedRows(form: ClientStateForm): StateRow[] {
  return STATE_ROWS.filter((row) => form.modes[row] !== undefined);
}

/** Zmiany wiersza „zmień” — pusty wynik znaczy, że opiekun nic nie wpisał. */
function rowChanges(row: StateRow, form: ClientStateForm): ClientStateChanges {
  switch (row) {
    case "area":
      if (form.areaId === "new") {
        return hasText(form.newAreaName) ? { new_area_name: form.newAreaName.trim() } : {};
      }
      return form.areaId != null ? { area_id: form.areaId } : {};
    case "manager":
      return form.managerContactId != null ? { manager_contact_id: form.managerContactId } : {};
    case "team": {
      const out: ClientStateChanges = {};
      if (hasText(form.teamSize)) out.team_size = form.teamSize.trim();
      const externals = Number(form.teamExternals);
      if (hasText(form.teamExternals) && Number.isInteger(externals) && externals >= 0) {
        out.team_externals = externals;
      }
      return out;
    }
    case "technologies":
      return {
        skill_ids: form.skills.filter((s) => s.id != null).map((s) => s.id as number),
        new_skill_names: form.skills.filter((s) => s.id == null).map((s) => s.name),
      };
    case "vendors":
      return { vendors: form.vendors.map((vendor) => vendor.name) };
    case "project_end":
      return {
        project_end_month: /^\d{4}-\d{2}$/.test(form.projectEndMonth) ? form.projectEndMonth : null,
      };
  }
}

/** Liczba wierszy „zmień” (stopka: „stan u klienta: 2 zmiany”). */
export function changedRows(form: ClientStateForm): StateRow[] {
  return STATE_ROWS.filter((row) => form.modes[row] === "change");
}

/**
 * `client_state` do zapisu: `null`, gdy sekcji nikt nie ruszył. Przy sygnale
 * „klient zatrudnia” role i źródło idą też do karty, jeśli karta się zapisuje.
 */
/**
 * Technologie stanu po zapisie: lista z „zmień” albo ta, którą już znamy.
 * Karta technologiczna bez ani jednej technologii się nie zapisuje (serwer 422).
 */
export function effectiveTechnologies(form: ClientStateForm, knownTechnologies: number): number {
  return form.modes.technologies === "change" ? form.skills.length : knownTechnologies;
}

export function buildClientState(
  form: ClientStateForm,
  talk: Pick<TalkForm, "clientHiring" | "hiringNote" | "hiringSource">,
  knownTechnologies = 0,
): ClientStatePayload | null {
  if (!touchedRows(form).length) return null;
  if (effectiveTechnologies(form, knownTechnologies) === 0) return null;
  const changes: ClientStateChanges = {};
  for (const row of changedRows(form)) Object.assign(changes, rowChanges(row, form));
  if (talk.clientHiring) {
    const roles = splitRoles(talk.hiringNote);
    if (roles.length) changes.hiring_roles = roles;
    if (talk.hiringSource) changes.hiring_source = talk.hiringSource;
  }
  return { confirmed: true, changes };
}

/** „Java, 2× QA; tester” → ["Java", "2× QA", "tester"]. */
export function splitRoles(raw: string): string[] {
  return raw
    .split(/[,;\n]+/)
    .map((part) => part.trim())
    .filter(Boolean);
}

/** Odpowiedzi na pytania z mapy klienta — tylko te, w których coś wpisano. */
export function buildGapAnswers(
  questions: ClientQuestion[],
  answers: Record<string, GapAnswerForm>,
): GapAnswerPayload[] {
  const out: GapAnswerPayload[] = [];
  for (const question of questions) {
    const answer = answers[question.key];
    if (!answer) continue;
    const payload: GapAnswerPayload = { key: question.key };
    if (question.kind === "reports_to" && answer.reportsToContactId != null) {
      payload.reports_to_contact_id = answer.reportsToContactId;
    }
    if (question.kind !== "reports_to" && answer.skills.length) {
      payload.skill_ids = answer.skills.filter((s) => s.id != null).map((s) => s.id as number);
      payload.new_skill_names = answer.skills.filter((s) => s.id == null).map((s) => s.name);
    }
    if (hasText(answer.note)) payload.note = answer.note.trim();
    if (Object.keys(payload).length > 1) out.push(payload);
  }
  return out;
}

/** Sprawy z tytułem (puste wiersze się nie liczą), najwyżej 5. */
export function buildCases(drafts: CaseDraft[]): ConversationCasePayload[] {
  return drafts
    .filter((draft) => hasText(draft.title))
    .slice(0, MAX_CONVERSATION_CASES)
    .map((draft) => {
      const payload: ConversationCasePayload = { title: draft.title.trim(), area: draft.area };
      if (draft.assigneeUserId != null) payload.assignee_user_id = draft.assigneeUserId;
      if (draft.dueOn) payload.due_on = draft.dueOn;
      return payload;
    });
}

export interface PayloadInput {
  talk: TalkForm;
  clientState: ClientStateForm;
  questions: ClientQuestion[];
  answers: Record<string, GapAnswerForm>;
  cases: CaseDraft[];
  planItemId: number | null;
  /** Ile technologii zna ostatni stan „Co u klienta” (bez nich karta się nie zapisuje). */
  knownTechnologies?: number;
}

export function buildConversationPayload(input: PayloadInput): ConversationPayload {
  const { talk } = input;
  return {
    occurred_on: talk.occurredOn,
    channel: talk.channel,
    satisfaction: talk.satisfaction,
    note: talk.note.trim() || null,
    attrition_risk: talk.attritionRisk,
    wants_change: talk.wantsChange,
    project_end_on: talk.projectEnd && talk.projectEndOn ? talk.projectEndOn : null,
    client_hiring: talk.clientHiring,
    client_hiring_note: talk.clientHiring ? talk.hiringNote.trim() || null : null,
    follow_up_on: talk.followUp || null,
    plan_item_id: input.planItemId,
    client_state: buildClientState(input.clientState, talk, input.knownTechnologies ?? 0),
    gap_answers: buildGapAnswers(input.questions, input.answers),
    cases: buildCases(input.cases),
  };
}

/** Błąd formularza do pokazania nad stopką albo `null`. */
export function validateConversation(input: PayloadInput, today: string): string | null {
  const { talk } = input;
  if (!talk.occurredOn || talk.occurredOn > today) {
    return "Podaj datę rozmowy (najpóźniej dzisiejszą).";
  }
  if (talk.followUp && talk.followUp < talk.occurredOn) {
    return "Następny kontakt musi być po dacie rozmowy.";
  }
  if (talk.projectEnd && !talk.projectEndOn) {
    return "Podaj datę końca projektu albo wyłącz ten sygnał.";
  }
  const titled = input.cases.filter((draft) => hasText(draft.title));
  if (titled.length > MAX_CONVERSATION_CASES) {
    return `Z jednej rozmowy założysz najwyżej ${MAX_CONVERSATION_CASES} spraw.`;
  }
  const untitled = input.cases.find((draft) => !hasText(draft.title) && (draft.dueOn || draft.assigneeUserId != null));
  if (untitled) return "Sprawa potrzebuje tytułu — albo usuń pusty wiersz.";
  return null;
}

/** Wiersz „Co u klienta”, do którego należy pole zmian (role popytu to sygnał, nie wiersz). */
const CHANGE_GROUP: Record<keyof ClientStateChanges, StateRow | null> = {
  area_id: "area",
  new_area_name: "area",
  manager_contact_id: "manager",
  team_size: "team",
  team_externals: "team",
  skill_ids: "technologies",
  new_skill_names: "technologies",
  vendors: "vendors",
  project_end_month: "project_end",
  hiring_roles: null,
  hiring_source: null,
};

/**
 * Stopka okna: co się zapisze („Zapiszemy: rozmowę · stan u klienta (2 zmiany)
 * · 1 odpowiedź do mapy klienta · 2 sprawy · sygnał popytu do Delivery Leada”).
 */
export function saveSummary(payload: ConversationPayload): string {
  const parts = ["rozmowę"];
  if (payload.client_state) {
    const changes = new Set(
      Object.keys(payload.client_state.changes)
        .map((key) => CHANGE_GROUP[key as keyof ClientStateChanges])
        .filter(Boolean),
    ).size;
    parts.push(
      changes
        ? `stan u klienta (${countPl(changes, "zmiana", "zmiany", "zmian")})`
        : "stan u klienta bez zmian",
    );
  }
  const answers = payload.gap_answers?.length ?? 0;
  if (answers) {
    parts.push(`${countPl(answers, "odpowiedź", "odpowiedzi", "odpowiedzi")} do mapy klienta`);
  }
  const cases = payload.cases?.length ?? 0;
  if (cases) parts.push(countPl(cases, "sprawę", "sprawy", "spraw"));
  if (payload.client_hiring) parts.push("sygnał popytu do Delivery Leada");
  if (payload.attrition_risk || payload.wants_change) parts.push("wpis „Do przepięcia”");
  return `Zapiszemy: ${parts.join(" · ")}.`;
}

/** Pytanie z mapy klienta słowami opiekuna. */
export function questionText(question: ClientQuestion): string {
  switch (question.kind) {
    case "reports_to":
      return `Komu podlega ${question.subject}?`;
    case "area_without_source":
      return `Na czym pracuje dział ${question.subject}?`;
    case "single_source":
      return `Czy ${question.subject} jest naprawdę używany?`;
  }
}
