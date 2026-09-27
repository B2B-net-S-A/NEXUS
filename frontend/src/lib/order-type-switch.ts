/**
 * Runda 10 (F02): zmiana typu nowego zamówienia (Okresowe ↔ MD/kosztowe)
 * przełącza między DWOMA formularzami. Do 27.09.2026 niosła tylko plik
 * i numer — kandydat, rekrutacja, daty, stawki i notatka znikały bez
 * ostrzeżenia, a powrót do „Okresowego” dawał pusty formularz.
 *
 * Pola wspólne obu formularzy (okres i notatka) jadą w obie strony;
 * pozostałe pola formularza okresowego (kandydat, rekrutacja, stawki)
 * czekają w roboczym stanie, dopóki użytkownik do niego nie wróci.
 * Zapis zawsze używa wybranego typu — pola niepasujące do typu nie są
 * przenoszone.
 */
export interface CarriedOrderFields {
  startDate: string;
  endDate: string;
  notes: string;
}

/** Roboczy stan formularza „Nowy kontraktor / zamówienie” (okresowe). */
export interface PeriodicOrderDraft {
  selectedCandidate: {
    id: number;
    name: string;
    lastname: string;
    email?: string | null;
    location?: string | null;
    competence_category?: string | null;
  } | null;
  jobId: string;
  contractStart: string;
  orderStart: string;
  orderEnd: string;
  rateClient: string;
  rateCandidate: string;
  rateUnit: "monthly" | "daily" | "hourly";
  billingHours: string;
  rateClientCurrency: string;
  rateCandidateCurrency: string;
  notes: string;
  executiveContractId: string;
}

/**
 * Formularz okresowy po powrocie z MD/kosztowego: jego roboczy stan
 * z polami wspólnymi nadpisanymi tym, co wpisano w drugim formularzu.
 */
export function periodicDraftForReturn(
  saved: PeriodicOrderDraft | null,
  common: CarriedOrderFields | null,
): Partial<PeriodicOrderDraft> | null {
  if (!saved && !common) return null;
  const base: Partial<PeriodicOrderDraft> = { ...(saved ?? {}) };
  if (common) {
    base.orderStart = common.startDate;
    base.orderEnd = common.endDate;
    base.notes = common.notes;
  }
  return base;
}

/** Pola wspólne z roboczego stanu formularza okresowego. */
export function commonFieldsOfPeriodic(
  draft: PeriodicOrderDraft,
): CarriedOrderFields {
  return {
    startDate: draft.orderStart,
    endDate: draft.orderEnd,
    notes: draft.notes,
  };
}
