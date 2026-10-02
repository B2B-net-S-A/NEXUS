/**
 * „Rekruter” przy przekazaniu do searchu: automat albo konkretna osoba
 * (decyzja Artura 02.10.2026). To samo pole stoi na `/jobs/new` i w oknie
 * „Przekaż do searchu” — jedna reguła i jedne zdania, żeby oba miejsca mówiły
 * to samo.
 */

import type { AllocationMode } from "@/lib/recruitment-allocation-api";

/** Tryb automatu przydziału (`recruitment_allocation_state.mode`). */
export type { AllocationMode };

/** Kto dostanie rekrutację: automat albo osoba wskazana ręcznie. */
export type RecruiterAssignment = "automatic" | "person";

/**
 * Nazwy opcji, gdy tryb automatu nie jest znany albo automat tylko proponuje
 * („shadow”). Nazwę opcji automatu dla konkretnego trybu daje
 * `automaticAssignmentLabel`.
 */
export const RECRUITER_ASSIGNMENT_LABEL: Record<RecruiterAssignment, string> = {
  automatic: "Zaproponuje automat",
  person: "Wybieram sam",
};

/**
 * Nazwa opcji automatu mówi, co się stanie: w trybie „auto” automat od razu
 * przydziela rekrutera prowadzącego, w „shadow” tylko proponuje osobę do
 * akceptacji. Brak trybu (starszy serwer) traktujemy ostrożnie, jak propozycję.
 */
export function automaticAssignmentLabel(
  mode: AllocationMode | null | undefined,
): string {
  return mode === "auto"
    ? "Przydzieli automat"
    : RECRUITER_ASSIGNMENT_LABEL.automatic;
}

export const AUTOMATIC_DISABLED_TEXT =
  "Automatyczny przydział jest wyłączony — włącza go administrator.";

/**
 * Rekrutacja ma już pierwszego rekrutera (`jobs.recruiter_id`): automat takim
 * requestom nikogo nie proponuje, a serwer odmawia przekazania „automatowi”
 * (409). Opcja jest wtedy nieaktywna — to zdanie mówi dlaczego.
 */
export function automaticTakenText(name: string | null | undefined): string {
  const person = name?.trim();
  return `Do tej rekrutacji jest już przypisana osoba${
    person ? ` (${person})` : ""
  }, więc automat nikogo nie zaproponuje. Wybierz rekrutera z listy.`;
}

/**
 * Automat da się wybrać przy włączonej fladze i trybie innym niż „off”
 * (w „off” nikogo nie zaproponuje ani nie przydzieli, a serwer odmawia 409).
 * Brak trybu przy włączonej fladze = starszy serwer, który trybu nie oddaje.
 */
export function automaticAssignmentAvailable(
  enabled: boolean | null | undefined,
  mode: AllocationMode | null | undefined,
): boolean {
  return enabled === true && mode !== "off";
}

/**
 * Wybór jest trójstanowy: `null` znaczy „nikt jeszcze nie wybrał” i wtedy
 * działa automat, o ile jest dostępny — request, przy którym Delivery Lead
 * niczego nie zaznaczy, i tak dostanie rekrutera (albo jego propozycję).
 * Przy niedostępnym automacie zostaje wybór osoby.
 */
export function resolveRecruiterAssignment(
  choice: RecruiterAssignment | null,
  automaticAvailable: boolean,
): RecruiterAssignment {
  if (!automaticAvailable) return "person";
  return choice ?? "automatic";
}

/** Co zrobi automat po przekazaniu — zależy od trybu z panelu przydziału. */
export function automaticAssignmentHint(
  mode: AllocationMode | null | undefined,
): string {
  return mode === "auto"
    ? "Automat przydzieli jedną osobę z kategorii — tę z najmniejszą liczbą requestów. Head rekrutacji zobaczy to na pulpicie i może zmienić."
    : "Automat zaproponuje osobę według kategorii i obłożenia. Propozycję zatwierdza Head of Recruitment — do tego czasu nikt nie jest przypisany.";
}

/**
 * Priorytet „Przyjmujemy kandydatów” znaczy „nie szukamy aktywnie” — automat
 * takim requestom nikogo nie proponuje (`job_priority.is_passive`). Obietnica
 * propozycji byłaby wtedy nieprawdą, więc pole mówi to wprost.
 */
export const AUTOMATIC_PASSIVE_NOTE =
  "Przy priorytecie „Przyjmujemy kandydatów” automat nikogo nie proponuje — rekrutacja zostanie bez rekrutera, dopóki ktoś jej nie weźmie albo nie wskażesz osoby.";

/** Co stanie się z obsadą po przekazaniu z automatem — jedno pełne zdanie. */
export function automaticHandoffOutcome(
  mode: AllocationMode | null | undefined,
  passive = false,
): string {
  if (passive) {
    return "Rekrutacja zostaje bez rekrutera — przy priorytecie „Przyjmujemy kandydatów” automat nikogo nie proponuje.";
  }
  return mode === "auto"
    ? "Rekrutera prowadzącego przydzieli automat — zwykle w ciągu minuty."
    : "Rekrutera zaproponuje automat, a zatwierdzi Head of Recruitment.";
}
