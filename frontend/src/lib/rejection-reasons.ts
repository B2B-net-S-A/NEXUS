/**
 * Słownik powodów odrzucenia dla jednej rekrutacji.
 *
 * `RejectionV2` przyjmuje `{ id, label, applies_to }`, a backend zwraca
 * `{ id, name, category }` z szablonu procesu. Mapowanie i awaryjny fallback na
 * szablon domyślny żyły dotąd wyłącznie w efekcie wewnątrz `KanbanBoardV2`.
 * Dok „Decyzja" kroku 07 otwiera TEN SAM modal, więc potrzebuje tej samej
 * listy — a druga kopia mapowania rozjechałaby się przy pierwszej zmianie
 * kształtu (np. gdyby `applies_to` przestało być jednoelementowe).
 *
 * Fallback jest istotny: joby zaimportowane z Traffita nie mają
 * `pipeline_template_id`, więc bez niego lista powodów byłaby pusta, a przycisk
 * „Potwierdź" w modalu trwale zablokowany.
 */

import api, { pipelineTemplatesApi, type RejectionReasonDef } from "@/lib/api";

/** Klucz powodu „Nie akceptuje trybu pracy” (0442) — lustro
 *  `rejection_reason_labels.WORK_MODE_MISMATCH`. Okno odrzucenia pyta przy nim,
 *  ile dni w biurze kandydat akceptuje, a serwer zapisuje to na profilu. */
export const WORK_MODE_MISMATCH_REASON = "work_mode_mismatch";

/** Klucz powodu „Już po rozmowie u tego hiring managera” (0484) — lustro
 *  `rejection_reason_labels.HM_ALREADY_INTERVIEWED`. */
export const HM_ALREADY_INTERVIEWED_REASON = "hm_already_interviewed";

/** Klucz powodu „Zatrudniony gdzie indziej” (04.11.2026) — lustro
 *  `rejection_reason_labels.EMPLOYED_ELSEWHERE`. Serwer zapisuje przy nim
 *  w profilu „Nie szuka” na 3 miesiące, a okno o tym uprzedza. */
export const EMPLOYED_ELSEWHERE_REASON = "Zatrudniony gdzie indziej";

/** Sześć powodów, które zespół wpisywał ręcznie pod „Inne” (04.11.2026, 0646) —
 *  lustro `rejection_reason_labels`. */
export const NOT_LOOKING_FOR_WORK_REASON = "not_looking_for_work";
export const CLIENT_CONFLICT_REASON = "client_conflict";
export const CONTRACT_FORM_REASON = "contract_form";
export const NO_CONTACT_REASON = "no_contact";
export const CLIENT_NO_REASON_REASON = "client_no_reason";
export const CLIENT_CHOSE_OTHER_REASON = "client_chose_other";

/** Końce procesu bez decyzji klienta o osobie (08.11.2026, 0663): zapisuje je
 *  zamknięcie rekrutacji albo brak odpowiedzi klienta, nikt ich nie wybiera. */
const SYSTEM_ONLY_REASONS: ReadonlySet<string> = new Set([
  "request_closed",
  "client_no_response",
]);

/** Tylko przy „Odrzuca klient”: my ani DL nie mówimy w imieniu klienta. */
const CLIENT_ONLY_REASONS: ReadonlySet<string> = new Set([
  CLIENT_NO_REASON_REASON,
  CLIENT_CHOSE_OTHER_REASON,
]);
/** Nie przy „Odrzuca klient”: na 104 opisach klienta od 12.10 żaden tak nie
 *  mówi, bo to sprawa osoby, nie decyzja klienta. */
const NOT_CLIENT_REASONS: ReadonlySet<string> = new Set([
  NOT_LOOKING_FOR_WORK_REASON,
  NO_CONTACT_REASON,
]);

/**
 * Czy powód pasuje do tego, kto kończy proces. Pozostałe powody (także dopisane
 * przez admina w szablonie) pasują zawsze.
 */
export function reasonFitsEndedBy(
  reason: Pick<RejectionReasonOption, "name">,
  endedBy: "candidate" | "recruiter" | "delivery_lead" | "client",
): boolean {
  const name = reason.name?.trim() ?? "";
  if (SYSTEM_ONLY_REASONS.has(name)) return false;
  if (CLIENT_ONLY_REASONS.has(name)) return endedBy === "client";
  if (NOT_CLIENT_REASONS.has(name)) return endedBy !== "client";
  return true;
}

/** Grupy okna odrzucenia (04.11.2026): przy 1280 × 720 płaska lista 12 powodów
 *  chowała nowe pod zgięciem. Klucze szablonu domyślnego; powód spoza grup
 *  (także „Inne” i dopisane przez admina) stoi pod nimi w kolejności listy. */
const REJECTED_REASON_GROUPS: { title: string; names: readonly string[] }[] = [
  {
    title: "Klient",
    names: [CLIENT_NO_REASON_REASON, CLIENT_CHOSE_OTHER_REASON],
  },
  {
    title: "Wymagania",
    names: ["Brak doświadczenia", "Nie spełnia wymagań technicznych", "Nie pasuje kulturowo"],
  },
  {
    title: "Warunki",
    names: ["Za wysokie oczekiwania finansowe", WORK_MODE_MISMATCH_REASON, CONTRACT_FORM_REASON],
  },
  {
    title: "Sprawa osoby",
    names: [
      NOT_LOOKING_FOR_WORK_REASON,
      "Zatrudniony gdzie indziej",
      CLIENT_CONFLICT_REASON,
      NO_CONTACT_REASON,
      HM_ALREADY_INTERVIEWED_REASON,
    ],
  },
];

export interface RejectionReasonGroup<T> {
  /** `null` — żaden powód nie trafił do grupy (np. szablon z własną listą). */
  title: string | null;
  reasons: T[];
}

export function groupRejectedReasons<T extends { name?: string }>(
  reasons: readonly T[],
): RejectionReasonGroup<T>[] {
  const byName = new Map(reasons.map((r) => [r.name?.trim() ?? "", r]));
  const grouped = new Set<T>();
  const groups: RejectionReasonGroup<T>[] = [];
  for (const { title, names } of REJECTED_REASON_GROUPS) {
    const members = names.flatMap((name) => {
      const reason = byName.get(name);
      return reason ? [reason] : [];
    });
    if (members.length === 0) continue;
    members.forEach((r) => grouped.add(r));
    groups.push({ title, reasons: members });
  }
  const rest = reasons.filter((r) => !grouped.has(r));
  if (rest.length === 0) return groups;
  return [...groups, { title: groups.length > 0 ? "Pozostałe" : null, reasons: rest }];
}

/**
 * Czy powód bez opisu nic nie mówi (20.10.2026) — lustro
 * `rejection_reason_labels.needs_description`. Przy „Inne” i „Już po rozmowie
 * u tego hiring managera” serwer odrzuca ruch bez opisu (422).
 */
export function reasonNeedsDescription(
  reason: Pick<RejectionReasonOption, "name" | "label"> | null | undefined,
): boolean {
  if (!reason) return false;
  return (
    reason.name?.trim() === HM_ALREADY_INTERVIEWED_REASON ||
    reason.label.trim() === "Inne"
  );
}

/** Powody „za drogo” (26.10.2026): odrzucenie ze słownika szablonu
 *  domyślnego i rezygnacja `salary_mismatch` (0068). Okno pyta przy nich,
 *  ile osoba teraz chce. */
const RATE_TOO_HIGH_REASONS = new Set([
  "Za wysokie oczekiwania finansowe",
  "salary_mismatch",
]);

export function isRateTooHighReason(
  reason: Pick<RejectionReasonOption, "name"> | null | undefined,
): boolean {
  return RATE_TOO_HIGH_REASONS.has(reason?.name?.trim() ?? "");
}

export interface RejectionReasonOption {
  id: string;
  label: string;
  /** Klucz danych powodu (`rejection_reasons.name`). */
  name?: string;
  applies_to: ("rejected" | "withdrawn")[];
  /**
   * Czy ten powód jest werdyktem o OSOBIE — tylko takie blokują ponowne
   * zgłoszenie kandydata do hiring managera, który go odrzucił. Karta rozmowy
   * pokazuje to obok wyboru, żeby „blokuje ponowne propozycje" było
   * odczytem stanu, a nie osobnym przełącznikiem bez pokrycia w backendzie.
   */
  disqualifies_person: boolean;
}

/**
 * Tekst powodu dla człowieka. `name` jest kluczem danych i bywa kodem
 * (`counter_offer`, `Inne (withdrawn)`) — etykietę po polsku liczy backend
 * (`app/services/rejection_reason_labels.py`, jedno źródło). `name` zostaje
 * wyłącznie zapasem dla odpowiedzi bez pola `label`.
 */
export function rejectionReasonLabel(
  reason: Pick<RejectionReasonDef, "name" | "label">,
): string {
  return reason.label?.trim() || reason.name;
}

export function mapRejectionReasons(
  rows: readonly RejectionReasonDef[] | null | undefined,
): RejectionReasonOption[] {
  return (rows ?? [])
    .filter((r) => r.category === "rejected" || r.category === "withdrawn")
    .map((r) => ({
      id: String(r.id),
      label: rejectionReasonLabel(r),
      name: r.name,
      applies_to: [r.category as "rejected" | "withdrawn"],
      disqualifies_person: Boolean(r.disqualifies_person),
    }));
}

/** Powody dla tej rekrutacji — z jej szablonu, awaryjnie z domyślnego. */
export async function loadJobRejectionReasons(
  jobId: number,
): Promise<RejectionReasonOption[]> {
  const job = await api.get(`/api/jobs/${jobId}`);
  const templateId: number | null | undefined = job.data?.pipeline_template_id;

  if (templateId) {
    const detail = await pipelineTemplatesApi.get(templateId);
    const mapped = mapRejectionReasons(detail.data.rejection_reasons);
    if (mapped.length > 0) return mapped;
  }

  const templates = await pipelineTemplatesApi.list();
  const fallback = templates.data.find((t) => t.is_default);
  if (!fallback) return [];
  const detail = await pipelineTemplatesApi.get(fallback.id);
  return mapRejectionReasons(detail.data.rejection_reasons);
}
