"use client";

import {
  AVAILABILITY_OPTIONS,
  type AvailabilityValue,
  CANDIDATE_STATUS_OPTIONS,
  type CandidateStatusValue,
  EMPLOYMENT_OPTIONS,
  OPEN_TO_OPTIONS,
} from "@/lib/filter-options";
import type { CandidateFilters } from "@/lib/url-filters";

import { PillGroup, type PillTone, toggleInList } from "./FilterPillGroup";

export type StatusAvailabilityValue = Pick<
  CandidateFilters,
  "status" | "employment" | "availability" | "openTo"
>;

interface StatusAvailabilityFilterFieldsProps {
  value: StatusAvailabilityValue;
  /** Łatka filtrów; wołający sam zeruje stronę. */
  onPatch: (patch: Partial<CandidateFilters>) => void;
}

// Mapy tonów dla grup, gdzie kolor niesie znaczenie. Reszta pigułek = neutral.
const STATUS_PILL_TONES: Partial<Record<CandidateStatusValue, PillTone>> = {
  active: "emerald",
  passive: "amber",
  blacklisted: "rose",
};

const AVAILABILITY_PILL_TONES: Partial<Record<AvailabilityValue, PillTone>> = {
  actively_looking: "emerald",
  open_to_offers: "sky",
};

/** Liczba aktywnych wartości — licznik na pigułce „Status" w pasku narzędzi. */
export function countStatusAvailability(value: StatusAvailabilityValue): number {
  return (
    value.status.length +
    value.employment.length +
    value.availability.length +
    value.openTo.length
  );
}

/**
 * Status, zatrudnienie, dyspozycyjność i otwartość na dodatkowe — ten sam blok
 * w szufladzie „Filtry" i w pigułce „Status" nad listą kandydatów.
 */
export function StatusAvailabilityFilterFields({
  value,
  onPatch,
}: StatusAvailabilityFilterFieldsProps) {
  return (
    <>
      <PillGroup
        label="Status"
        options={CANDIDATE_STATUS_OPTIONS}
        value={value.status}
        tones={STATUS_PILL_TONES}
        onToggle={(v) => onPatch({ status: toggleInList(value.status, v) })}
      />
      <PillGroup
        label="Zatrudnienie"
        options={EMPLOYMENT_OPTIONS}
        value={value.employment}
        onToggle={(v) =>
          onPatch({ employment: toggleInList(value.employment, v) })
        }
      />
      <PillGroup
        label="Dyspozycyjność"
        options={AVAILABILITY_OPTIONS}
        value={value.availability}
        tones={AVAILABILITY_PILL_TONES}
        onToggle={(v) =>
          onPatch({ availability: toggleInList(value.availability, v) })
        }
      />
      <PillGroup
        label="Otwartość na dodatkowe"
        options={OPEN_TO_OPTIONS}
        value={value.openTo}
        onToggle={(v) => onPatch({ openTo: toggleInList(value.openTo, v) })}
      />
    </>
  );
}
