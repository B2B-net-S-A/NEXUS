import type { CandidateFilters, RemoteMode } from "@/lib/url-filters";
import type { StageFilterValue } from "@/components/v2/filters/StageFilterPanel";
import type { SkillBucketsValue } from "@/lib/candidate-search-semantics";

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
    filters.status.length +
    filters.openTo.length +
    (filters.hideUnknown ? 1 : 0) +
    filters.qAny.slice(1).flat().length;
  return {
    rate: filters.rateMin !== null || filters.rateMax !== null ? 1 : 0,
    location: (filters.location.trim() ? 1 : 0) + filters.voivodeships.length,
    remote: filters.remote.length,
    history:
      filters.recruitmentIds.length +
      stageCount +
      (filters.sentToClientFrom || filters.sentToClientTo ? 1 : 0) +
      filters.workedAtClientIds.length +
      contactCount,
    skills: skills.required.length + skills.preferred.length + skills.excluded.length,
    availability: filters.availability.length + filters.employment.length,
    more: about + company + source + other,
  };
}

/** „120–160 zł/h", „od 120 zł/h", „do 160 zł/h"; `null` = nic nie ustawiono. */
export function rateSummary(filters: Pick<CandidateFilters, "rateMin" | "rateMax">): string | null {
  const { rateMin: lo, rateMax: hi } = filters;
  if (lo !== null && hi !== null) return `${lo}–${hi} zł/h`;
  if (lo !== null) return `od ${lo} zł/h`;
  if (hi !== null) return `do ${hi} zł/h`;
  return null;
}

function voivodeshipsLabel(count: number): string {
  if (count === 1) return "1 województwo";
  const mod10 = count % 10;
  const mod100 = count % 100;
  const few = mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14);
  return `${count} ${few ? "województwa" : "województw"}`;
}

/**
 * „Warszawa +25 km", „Warszawa, mazowieckie", „2 województwa" — na przycisku
 * mieści się jedna krótka fraza; pełne wartości są w okienku.
 */
export function locationSummary(
  filters: Pick<CandidateFilters, "location" | "locationRadiusKm" | "voivodeships">,
): string | null {
  const city = filters.location.trim();
  const woj = filters.voivodeships;
  const cityPart = city
    ? filters.locationRadiusKm !== null
      ? `${city} +${filters.locationRadiusKm} km`
      : city
    : "";
  const wojPart = woj.length === 0 ? "" : woj.length === 1 ? woj[0] : voivodeshipsLabel(woj.length);
  if (cityPart && wojPart) return `${cityPart}, ${wojPart}`;
  return cityPart || wojPart || null;
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
 * Chipy nad tabelą, których wartość widać już na pasku (słowa kluczowe
 * i pierwsza grupa „którekolwiek", stawka, lokalizacja, tryb pracy). Kolejne
 * grupy „którekolwiek" (`q_any:1:…`) zostają chipami — są w „Więcej filtrów".
 */
export function isChipShownOnFilterBar(key: string): boolean {
  return (
    key === "rate" ||
    key === "loc" ||
    key === "q_scope" ||
    key.startsWith("woj:") ||
    key.startsWith("remote:") ||
    key.startsWith("q_all:") ||
    key.startsWith("q_any:0:") ||
    key.startsWith("q_none:")
  );
}
