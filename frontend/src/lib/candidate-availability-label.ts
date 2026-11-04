/**
 * „Czy szuka pracy?” — jedno źródło etykiet pola `availability_status`
 * dla pigułki przy nazwisku (profil, lista kandydatów).
 *
 * Od 13.10.2026 (decyzja D4) pigułka zastępuje plakietkę statusu „Aktywny”,
 * którą miało 65 828 z 65 865 osób — nic nie mówiła. Sygnał „szuka” żyje
 * w polu dostępności (4 423 osoby „szuka aktywnie”), a na liście przegrywał
 * w kolumnie „Dostępność” z datą. Brak pigułki = status nieustalony.
 */

export type CandidateAvailabilityStatus =
  | "actively_looking"
  | "open_to_offers"
  | "not_looking"
  | "unknown";

export type AvailabilityTone = "success" | "info" | "neutral";

const LABELS: Record<Exclude<CandidateAvailabilityStatus, "unknown">, string> = {
  actively_looking: "Szuka aktywnie",
  open_to_offers: "Otwarty na oferty",
  not_looking: "Nie szuka",
};

const TONES: Record<Exclude<CandidateAvailabilityStatus, "unknown">, AvailabilityTone> = {
  actively_looking: "success",
  open_to_offers: "info",
  not_looking: "neutral",
};

/** Etykieta pigułki albo `null`, gdy statusu nie ustalono (wtedy pigułki nie ma). */
export function availabilityStatusLabel(status: string | null | undefined): string | null {
  if (!status || !(status in LABELS)) return null;
  return LABELS[status as keyof typeof LABELS];
}

export function availabilityStatusTone(status: string | null | undefined): AvailabilityTone {
  if (!status || !(status in TONES)) return "neutral";
  return TONES[status as keyof typeof TONES];
}
