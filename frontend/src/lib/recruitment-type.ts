/**
 * Etykiety PL dla `RecruitmentType` (`backend/app/models/job.py`) — lustro
 * `RECRUITMENT_TYPE_CONFIG` w `/jobs/[id]/page.tsx` (stąd nieeksportowane,
 * niosło tam też wariant koloru pilla), potrzebne w dwóch nowych miejscach
 * listy rekrutacji: wierszu tabeli i `JobReadinessDock`.
 *
 * Świadomie OSOBNE od `JobType`/`FILTER_TABS` w `JobsListV2` — te opisują
 * WARTOŚCI ZAPYTANIA filtra „Typ” (`recruitment_type` + `"all"` jako brak
 * filtra), a ten słownik opisuje WARTOŚĆ POLA konkretnej rekrutacji.
 */
export const RECRUITMENT_TYPE_LABEL: Record<string, string> = {
  body_leasing: "Body leasing",
  sales_project: "Sprzedaż",
  tender: "Przetarg",
};
