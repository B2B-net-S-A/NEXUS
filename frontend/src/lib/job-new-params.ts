/**
 * `/jobs/new?client=&hm=&skills=&title=` — nowa rekrutacja z działu klienta
 * (22.10.2026): „Nowa rekrutacja z działu” w zakładce klienta „Ludzie
 * i technologie” i potwierdzony popyt z okna „Rozmowa z menedżerem”.
 *
 * Reguła jak przy odczycie requestu (D3, `jobs-new-jeden-ekran-i-odczyt-pustych-pol.md`):
 * parametry wypełniają WYŁĄCZNIE puste pola — tytuł, hiring managera (gdy nikt
 * go nie wybrał ani nie zaznaczył „Klient nie podał”) i wymagania (gdy żadne
 * nie jest wpisane). `?from=` (kopia rekrutacji) ma pierwszeństwo — wtedy
 * strona tych parametrów nie czyta.
 */

import type { HiringManagerOption } from "@/lib/hiring-manager";
import type { IntakeForm } from "@/lib/job-request-intake";
import { REQUIRED_ROWS_MAX, filledRows, newRowKey } from "@/lib/requirement-rows";

export interface JobPrefillParams {
  hmId: number | null;
  skillIds: number[];
  title: string | null;
}

function positiveInt(raw: string | null | undefined): number | null {
  if (!raw || !/^\d+$/.test(raw.trim())) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}

/** Parametry z adresu; śmieci („abc”, „0”, puste) to brak wartości. */
export function parseJobPrefill(params: {
  hm?: string | null;
  skills?: string | null;
  title?: string | null;
}): JobPrefillParams {
  const skillIds: number[] = [];
  for (const part of (params.skills ?? "").split(",")) {
    const id = positiveInt(part);
    if (id !== null && !skillIds.includes(id)) skillIds.push(id);
  }
  const title = (params.title ?? "").trim().slice(0, 200);
  return {
    hmId: positiveInt(params.hm),
    skillIds: skillIds.slice(0, REQUIRED_ROWS_MAX),
    title: title || null,
  };
}

export function hasJobPrefill(prefill: JobPrefillParams): boolean {
  return prefill.hmId !== null || prefill.skillIds.length > 0 || prefill.title !== null;
}

/** Nazwy umiejętności w kolejności z adresu; nieznane id odpadają. */
export function skillNamesFor(
  ids: readonly number[],
  known: readonly { skill_id: number; name: string }[],
): string[] {
  const byId = new Map(known.map((item) => [item.skill_id, item.name]));
  return ids.map((id) => byId.get(id)).filter((name): name is string => Boolean(name));
}

export interface JobPrefillValues {
  title: string | null;
  hiringManager: HiringManagerOption | null;
  skills: string[];
}

/**
 * Wkłada parametry do formularza — tylko w puste pola. Zwraca ten sam obiekt,
 * gdy nic się nie zmieniło (stan Reacta się nie przestawia).
 */
export function applyJobPrefill(form: IntakeForm, values: JobPrefillValues): IntakeForm {
  let next = form;
  if (values.title && !form.title.trim()) {
    next = { ...next, title: values.title };
  }
  if (values.hiringManager && form.hiringManager === null && !form.hiringManagerNotProvided) {
    next = {
      ...next,
      hiringManager: {
        kind: "contact",
        id: values.hiringManager.id,
        name: values.hiringManager.name,
      },
    };
  }
  if (values.skills.length && filledRows(form.rows).length === 0) {
    next = {
      ...next,
      rows: values.skills.slice(0, REQUIRED_ROWS_MAX).map((name) => ({
        key: newRowKey(),
        words: [name],
        level: "must" as const,
      })),
    };
  }
  return next;
}
