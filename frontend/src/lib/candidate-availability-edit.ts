/**
 * Edycja dostępności z karty „Podsumowanie” profilu kandydata.
 *
 * Do 04.10.2026 dostępność dało się zmienić tylko w „Edytuj dane”, choć
 * pokazywał ją pasek faktów. Zapis idzie tym samym PATCH-em
 * `/api/candidates/{id}` i tą samą regułą co „Edytuj dane”: wysyłamy WYŁĄCZNIE
 * pola zmienione względem stanu z chwili otwarcia okna (runda 9, R9-N8-7) —
 * inaczej zapis cofałby zmianę zrobioną w międzyczasie przez kogoś innego.
 */

export const AVAILABILITY_STATUS_OPTIONS = [
  { value: "unknown", label: "Nie wiemy" },
  { value: "actively_looking", label: "Aktywnie szuka pracy" },
  { value: "open_to_offers", label: "Otwarty na oferty" },
  { value: "not_looking", label: "Nie szuka" },
] as const;

export const NOTICE_PERIOD_UNITS = [
  { value: "days", label: "dni" },
  { value: "weeks", label: "tygodnie" },
  { value: "months", label: "miesiące" },
] as const;

export interface AvailabilitySource {
  availability_status?: string | null;
  availability_date?: string | null;
  notice_period?: number | null;
  notice_period_unit?: string | null;
}

export interface AvailabilityDraft {
  status: string;
  /** `YYYY-MM-DD` albo pusty napis. */
  date: string;
  /** Liczba wpisana w pole albo pusty napis. */
  noticePeriod: string;
  noticeUnit: string;
}

export interface AvailabilityPatch {
  availability_status?: string;
  availability_date?: string | null;
  notice_period?: number | null;
  notice_period_unit?: string | null;
}

export function availabilityDraft(source: AvailabilitySource): AvailabilityDraft {
  return {
    status: source.availability_status || "unknown",
    date: source.availability_date ? source.availability_date.slice(0, 10) : "",
    noticePeriod:
      source.notice_period != null ? String(source.notice_period) : "",
    noticeUnit: source.notice_period_unit || "days",
  };
}

/** Błąd do pokazania przy polu albo `null`, gdy szkic da się zapisać. */
export function availabilityDraftError(draft: AvailabilityDraft): string | null {
  const raw = draft.noticePeriod.trim();
  if (!raw) return null;
  if (!/^\d+$/.test(raw)) {
    return "Okres wypowiedzenia to liczba całkowita, np. 30.";
  }
  if (Number(raw) > 365) {
    return "Okres wypowiedzenia może mieć najwyżej 365 jednostek.";
  }
  return null;
}

function normalized(draft: AvailabilityDraft): Required<AvailabilityPatch> {
  const notice = draft.noticePeriod.trim();
  return {
    availability_status: draft.status || "unknown",
    availability_date: draft.date || null,
    notice_period: notice ? Number(notice) : null,
    notice_period_unit: notice ? draft.noticeUnit || "days" : null,
  };
}

/** Pola zmienione względem stanu z chwili otwarcia — pusty obiekt = nic do zapisu. */
export function availabilityPatch(
  initial: AvailabilityDraft,
  next: AvailabilityDraft,
): AvailabilityPatch {
  const before = normalized(initial);
  const after = normalized(next);
  const patch: AvailabilityPatch = {};
  if (before.availability_status !== after.availability_status) {
    patch.availability_status = after.availability_status;
  }
  if (before.availability_date !== after.availability_date) {
    patch.availability_date = after.availability_date;
  }
  if (
    before.notice_period !== after.notice_period ||
    before.notice_period_unit !== after.notice_period_unit
  ) {
    patch.notice_period = after.notice_period;
    patch.notice_period_unit = after.notice_period_unit;
  }
  return patch;
}
