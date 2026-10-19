import type { CandidateFilters } from "@/lib/url-filters";

/**
 * Blok „Rekrutacje” w filtrze „Rekrutacje i historia” (12.10.2026; do 16.10 „Historia z nami”).
 *
 * Ekran pokazuje JEDEN wybór („Dowolnie · Brał udział · Nie brał udziału · Bez
 * procesu w toku”), a filtry trzymają go w czterech polach: zakresie
 * (`recruitmentIds` + `recruitmentClientIds`), jego kierunku
 * (`recruitmentMatch`) i pytaniu bez zakresu (`recruitmentPresence`). Tryb
 * jest tu wyliczany, a każda zmiana zapisuje wszystkie pola naraz — żyją
 * w dwóch pojemnikach stanu listy, więc łatka częściowa zostawiłaby resztę
 * po poprzednim trybie.
 */
export type RecruitmentMode = "any" | "took_part" | "did_not" | "idle";

type RecruitmentFields = Pick<
  CandidateFilters,
  "recruitmentIds" | "recruitmentClientIds" | "recruitmentMatch" | "recruitmentPresence"
>;

/**
 * Etap i „Wysłany do klienta” dotyczą osób, które były w rekrutacji. Przy
 * „nie brał udziału w żadnej” dałyby zawsze zero wyników, więc ten tryb je
 * czyści, a ekran wyłącza (`recruitmentLocksStageFields`).
 */
const NO_STAGE_FILTERS = {
  pipelineStage: [],
  stageColumns: [],
  stageCurrentOnly: false,
  stageClientIds: [],
  stageMovedByIds: [],
  stageMovedAfter: "",
  stageMovedBefore: "",
  sentToClientFrom: "",
  sentToClientTo: "",
} satisfies Partial<CandidateFilters>;

const NO_SCOPE = {
  recruitmentIds: [],
  recruitmentClientIds: [],
  recruitmentMatch: "assigned",
} satisfies Partial<CandidateFilters>;

export function hasRecruitmentScope(
  filters: Pick<RecruitmentFields, "recruitmentIds" | "recruitmentClientIds">,
): boolean {
  return filters.recruitmentIds.length > 0 || filters.recruitmentClientIds.length > 0;
}

/**
 * Tryb widoczny na ekranie. `locked` = okno „Szukaj ręcznie”: zakres („nie w
 * tej rekrutacji”) dokłada tam samo zapytanie, więc ekran czyta tylko pytanie
 * bez zakresu.
 */
export function recruitmentMode(filters: RecruitmentFields, locked = false): RecruitmentMode {
  if (!locked && hasRecruitmentScope(filters)) {
    return filters.recruitmentMatch === "not_assigned" ? "did_not" : "took_part";
  }
  if (filters.recruitmentPresence === "ever") return "took_part";
  if (filters.recruitmentPresence === "never") return "did_not";
  if (filters.recruitmentPresence === "not_in_process") return "idle";
  return "any";
}

/** Łatka po wyborze opcji. */
export function patchForRecruitmentMode(
  mode: RecruitmentMode,
  filters: RecruitmentFields,
  locked = false,
): Partial<CandidateFilters> {
  if (locked) {
    if (mode === "did_not") return { recruitmentPresence: "never", ...NO_STAGE_FILTERS };
    if (mode === "took_part") return { recruitmentPresence: "ever" };
    return { recruitmentPresence: mode === "idle" ? "not_in_process" : "" };
  }
  if (mode === "any") return { ...NO_SCOPE, recruitmentPresence: "" };
  if (mode === "idle") return { ...NO_SCOPE, recruitmentPresence: "not_in_process" };
  if (hasRecruitmentScope(filters)) {
    // „Brał / nie brał” przy wybranych rekrutacjach odwraca kierunek, a wybór zostaje.
    return {
      recruitmentIds: filters.recruitmentIds,
      recruitmentClientIds: filters.recruitmentClientIds,
      recruitmentMatch: mode === "did_not" ? "not_assigned" : "assigned",
      recruitmentPresence: "",
    };
  }
  if (mode === "did_not") return { ...NO_SCOPE, recruitmentPresence: "never", ...NO_STAGE_FILTERS };
  return { ...NO_SCOPE, recruitmentPresence: "ever" };
}

/**
 * Łatka po zmianie na liście rekrutacji. Pusty wybór to „Wszystkie rekrutacje”
 * bieżącej opcji (w jakiejkolwiek / w żadnej), nie powrót do „Dowolnie”.
 */
export function patchForRecruitmentScope(
  recruitmentIds: number[],
  clientIds: number[],
  filters: RecruitmentFields,
): Partial<CandidateFilters> {
  const negative = recruitmentMode(filters) === "did_not";
  if (recruitmentIds.length > 0 || clientIds.length > 0) {
    return {
      recruitmentIds,
      recruitmentClientIds: clientIds,
      recruitmentMatch: negative ? "not_assigned" : "assigned",
      recruitmentPresence: "",
    };
  }
  return negative
    ? { ...NO_SCOPE, recruitmentPresence: "never", ...NO_STAGE_FILTERS }
    : { ...NO_SCOPE, recruitmentPresence: "ever" };
}

/**
 * Łatki po zdjęciu chipa nad tabelą. Ostatnia pozycja zakresu zdejmuje cały
 * filtr — ✕ nie może zamienić „poza rekrutacją X” w „w żadnej rekrutacji”.
 */
export function patchForRemovedRecruitment(
  filters: RecruitmentFields,
  recruitmentId: number,
): Partial<CandidateFilters> {
  const recruitmentIds = filters.recruitmentIds.filter((id) => id !== recruitmentId);
  return recruitmentIds.length > 0 || filters.recruitmentClientIds.length > 0
    ? { recruitmentIds }
    : { recruitmentIds, recruitmentMatch: "assigned" };
}

export function patchForRemovedRecruitmentClient(
  filters: RecruitmentFields,
  clientId: number,
): Partial<CandidateFilters> {
  const recruitmentClientIds = filters.recruitmentClientIds.filter((id) => id !== clientId);
  return recruitmentClientIds.length > 0 || filters.recruitmentIds.length > 0
    ? { recruitmentClientIds }
    : { recruitmentClientIds, recruitmentMatch: "assigned" };
}

/** „Nie brał udziału w żadnej rekrutacji” wyłącza etap i datę wysłania. */
export function recruitmentLocksStageFields(
  filters: Pick<RecruitmentFields, "recruitmentPresence">,
): boolean {
  return filters.recruitmentPresence === "never";
}
