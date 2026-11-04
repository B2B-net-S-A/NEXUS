import type { CandidateFilters, RemoteMode } from "@/lib/url-filters";
import type { StageFilterValue } from "@/components/v2/filters/StageFilterPanel";
import type { SkillBucketsValue } from "@/lib/candidate-search-semantics";
import { describeLocationPlaces, shownLocationPlaces } from "@/lib/location-places";

/**
 * Pasek filtrów listy kandydatów (wariant A, decyzja Artura 23.09.2026):
 * ile ustawień siedzi w każdym przycisku i co przycisk mówi o swojej
 * wartości. Czyste funkcje — przycisk z ukrytym, ale ustawionym filtrem
 * musi to pokazać licznikiem albo podsumowaniem.
 */

export interface FilterGroupCounts {
  rate: number;
  location: number;
  remote: number;
  history: number;
  skills: number;
  availability: number;
  /** „Więcej filtrów": profil, firma, źródło i „Inne". */
  more: number;
}

export function filterGroupCounts(
  filters: CandidateFilters,
  stage: StageFilterValue,
  skills: SkillBucketsValue,
): FilterGroupCounts {
  const stageCount =
    stage.columns.length +
    stage.stages.length +
    (stage.currentOnly ? 1 : 0) +
    stage.clientIds.length +
    stage.movedByIds.length +
    (stage.movedAfter || stage.movedBefore ? 1 : 0);
  const contactCount = filters.contacted ? 1 + filters.contactedByIds.length : 0;
  const about =
    (filters.experienceMin !== null || filters.experienceMax !== null ? 1 : 0) +
    filters.languages.length +
    filters.competenceCategoryIds.length;
  const company =
    filters.currentCompany.length +
    filters.pastCompany.length +
    filters.currentTitle.length +
    (filters.recentlyChangedJobs ? 1 : 0);
  const source = filters.poolIds.length + filters.addedByIds.length;
  const other =
    filters.tags.length +
    filters.status.length +
    filters.openTo.length +
    (filters.hideUnknown ? 1 : 0);
  return {
    rate: filters.rateMin !== null || filters.rateMax !== null ? 1 : 0,
    location: shownLocationPlaces(filters).length + filters.voivodeships.length,
    remote: filters.remote.length,
    history:
      filters.recruitmentIds.length +
      filters.recruitmentClientIds.length +
      (filters.recruitmentPresence ? 1 : 0) +
      stageCount +
      (filters.sentToClientFrom || filters.sentToClientTo ? 1 : 0) +
      filters.workedAtClientIds.length +
      contactCount,
    skills: skills.required.length + skills.preferred.length + skills.excluded.length,
    availability: filters.availability.length + filters.employment.length,
    more: about + company + source + other,
  };
}

/** Dopisek wyboru D5 przy podsumowaniu stawki albo lokalizacji. */
export const HIDDEN_RATE_NOTE = "bez stawki: ukryte";
export const HIDDEN_LOCATION_NOTE = "bez miasta: ukryte";

/**
 * „120–160 zł/h", „od 120 zł/h", „do 160 zł/h"; z „· bez stawki: ukryte”,
 * gdy osoby bez stawki są ukryte (D5). `null` = nic nie ustawiono.
 */
export function rateSummary(
  filters: Pick<CandidateFilters, "rateMin" | "rateMax"> &
    Partial<Pick<CandidateFilters, "hideUnknownRate">>,
): string | null {
  const { rateMin: lo, rateMax: hi } = filters;
  const range =
    lo !== null && hi !== null
      ? `${lo}–${hi} zł/h`
      : lo !== null
        ? `od ${lo} zł/h`
        : hi !== null
          ? `do ${hi} zł/h`
          : null;
  if (range === null) return null;
  return filters.hideUnknownRate ? `${range} · ${HIDDEN_RATE_NOTE}` : range;
}

function voivodeshipsLabel(count: number): string {
  if (count === 1) return "1 województwo";
  const mod10 = count % 10;
  const mod100 = count % 100;
  const few = mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14);
  return `${count} ${few ? "województwa" : "województw"}`;
}

/**
 * „Warszawa +25 km", „Warszawa, mazowieckie", „2 województwa",
 * „Warszawa +30 km, Łódź, Kraków +50 km” (D6); z „· bez miasta: ukryte”,
 * gdy osoby bez miasta są ukryte (D5).
 */
export function locationSummary(
  filters: Pick<CandidateFilters, "location" | "locationRadiusKm" | "voivodeships"> &
    Partial<Pick<CandidateFilters, "locationPlaces" | "hideUnknownLocation">>,
): string | null {
  const cityPart = describeLocationPlaces(
    shownLocationPlaces({ ...filters, locationPlaces: filters.locationPlaces ?? [] }),
  );
  const woj = filters.voivodeships;
  const wojPart = woj.length === 0 ? "" : woj.length === 1 ? woj[0] : voivodeshipsLabel(woj.length);
  const summary = cityPart && wojPart ? `${cityPart}, ${wojPart}` : cityPart || wojPart || null;
  if (summary === null) return null;
  return filters.hideUnknownLocation ? `${summary} · ${HIDDEN_LOCATION_NOTE}` : summary;
}

const REMOTE_LABELS: Record<RemoteMode, string> = {
  remote: "Zdalnie",
  hybrid: "Hybryda",
  onsite: "Biuro",
};

export function remoteSummary(filters: Pick<CandidateFilters, "remote">): string | null {
  if (filters.remote.length === 0) return null;
  return filters.remote.map((m) => REMOTE_LABELS[m] ?? m).join(", ");
}

/**
 * Chipy nad tabelą, których wartość widać już na pasku (wszystkie wiersze
 * słów kluczowych i „Wyklucz”, stawka, lokalizacja, tryb pracy).
 */
export function isChipShownOnFilterBar(key: string): boolean {
  return (
    key === "rate" ||
    key === "loc" ||
    key === "q_scope" ||
    key.startsWith("woj:") ||
    key.startsWith("remote:") ||
    key.startsWith("q_all:") ||
    key.startsWith("q_any:") ||
    key.startsWith("q_none:")
  );
}
