// Strażnik widełek przy publikacji ogłoszenia na portalu (16.11.2026).
//
// Od 24.12.2025 (Dz.U. 2025 poz. 807) kandydat na umowę o pracę poznaje
// wynagrodzenie albo widełki przed rozmową. Publikacja bez widełek nie jest
// zablokowana, ale wymaga potwierdzenia z powodem — powód idzie w ustawieniach
// ogłoszenia (`no_salary_reason`) i zostaje przy publikacji. Dla B2B tekst
// mówi „zalecane” i nie przesądza zakresu prawa (Artur pytał prawnika).
// Lustro: `backend/app/services/job_portals/salary_guard.py`.
// Reguła: `docs/claude/rekrutacja-tworzenie/widelki-w-ogloszeniu-albo-powod.md`.

import type { ReasonRequest } from "@/components/v2/modals/ConfirmV2";
import type { PortalListingOptions } from "@/lib/api/jobPortals";

export type AdContractForm = "b2b" | "uop";

/**
 * Forma umowy w ogłoszeniach NEXUSA. Dziś każda rekrutacja to B2B
 * (`job_public_profile.public_params`, portal dostaje `employmentTypes: b2b`).
 */
export const NEXUS_AD_CONTRACT_FORM: AdContractForm = "b2b";

export const NO_SALARY_REASON_MIN = 3;
export const NO_SALARY_REASON_MAX = 300;

export function noSalaryDescription(form: AdContractForm): string {
  const law =
    form === "uop"
      ? "Przy umowie o pracę prawo wymaga (od 24.12.2025, Dz.U. 2025 poz. 807), żeby kandydat poznał wynagrodzenie albo jego widełki przed rozmową."
      : "Przy B2B podanie widełek jest zalecane. Czy przepisy o jawności wynagrodzeń obejmują ogłoszenia B2B, sprawdzamy z prawnikiem.";
  return `${law} Wróć i wpisz widełki albo podaj powód publikacji bez nich — zapiszemy go przy ogłoszeniu.`;
}

export function noSalaryReasonRequest(
  form: AdContractForm,
  { editing = false }: { editing?: boolean } = {},
): ReasonRequest {
  return {
    title: "Ogłoszenie bez widełek",
    description: noSalaryDescription(form),
    confirmLabel: editing ? "Zapisz bez widełek" : "Opublikuj bez widełek",
    cancelLabel: "Wróć i wpisz widełki",
    field: {
      label: "Powód publikacji bez widełek",
      placeholder: "np. stawkę ustalamy z klientem po rozmowie technicznej",
      minLength: NO_SALARY_REASON_MIN,
      maxLength: NO_SALARY_REASON_MAX,
    },
  };
}

/**
 * Ustawienia do wysyłki: z widełkami bez pytania (powód pusty), bez widełek
 * dopiero po potwierdzeniu z powodem. `null` = człowiek wrócił do formularza.
 */
export async function confirmSalaryOrReason(
  options: PortalListingOptions,
  askReason: (request: ReasonRequest) => Promise<string | null>,
  { form = NEXUS_AD_CONTRACT_FORM, editing = false }: { form?: AdContractForm; editing?: boolean } = {},
): Promise<PortalListingOptions | null> {
  if (options.salary) return { ...options, no_salary_reason: null };
  const reason = await askReason(noSalaryReasonRequest(form, { editing }));
  if (!reason || reason.length < NO_SALARY_REASON_MIN) return null;
  return { ...options, no_salary_reason: reason };
}
