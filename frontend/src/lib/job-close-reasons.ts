/**
 * Grupy powodów zamknięcia rekrutacji w hit ratio (decyzja Artura 21.10.2026).
 *
 * Przegraną jest tylko rekrutacja, którą wzięła inna firma. Powody z grupy
 * „Nie liczy się” nie wchodzą do hit ratio (Liga DL, cel DL, Insights) i
 * wymagają uzasadnienia. Lustro `backend/app/services/metric_definitions.py`
 * (`HIT_RATIO_*_CLOSE_REASONS`) — serwer i tak sprawdza wybór.
 */

import { JOB_CLOSE_REASONS, type JobCloseReason } from "@/types/client-profile";

export type CloseReasonGroup = "won" | "lost" | "neutral";

export interface CloseReasonOption {
  value: JobCloseReason;
  label: string;
  hint: string;
}

export interface CloseReasonGroupDef {
  key: CloseReasonGroup;
  label: string;
  hint: string;
  effect: string;
  reasons: CloseReasonOption[];
}

const label = (value: JobCloseReason): string =>
  JOB_CLOSE_REASONS.find((r) => r.value === value)?.label ?? value;

export const CLOSE_REASON_GROUPS: CloseReasonGroupDef[] = [
  {
    key: "won",
    label: "Wygraliśmy",
    hint: "liczy się jako wygrana",
    effect: "Liczy się do hit ratio jako wygrana — w Lidze DL, celu DL i Insights.",
    reasons: [
      {
        value: "filled_by_us",
        label: label("filled_by_us"),
        hint: "Ktoś od nas jest zatrudniony w tej rekrutacji",
      },
    ],
  },
  {
    key: "lost",
    label: "Przegraliśmy",
    hint: "wzięła inna firma",
    effect: "Liczy się do hit ratio jako przegrana — w Lidze DL, celu DL i Insights.",
    reasons: [
      {
        value: "competitor",
        label: label("competitor"),
        hint: "Inna agencja albo dostawca obsadził to stanowisko",
      },
    ],
  },
  {
    key: "neutral",
    label: "Nie liczy się",
    hint: "poza hit ratio",
    effect:
      "Nie wchodzi do hit ratio, Ligi DL ani celu DL. Zostaje w historii klienta i na liście „Zamknięte poza hit ratio” w Insights.",
    reasons: [
      {
        value: "duplicate",
        label: label("duplicate"),
        hint: "Ten sam request jest w innej rekrutacji albo założono ją błędnie",
      },
      {
        value: "internal_hire",
        label: label("internal_hire"),
        hint: "Własny pracownik albo kandydat z ogłoszenia klienta",
      },
      {
        value: "budget",
        label: label("budget"),
        hint: "Stanowisko przestało istnieć",
      },
      {
        value: "paused",
        label: label("paused"),
        hint: "Może wrócić — wtedy „Otwórz ponownie”",
      },
      {
        value: "client_ghosted",
        label: label("client_ghosted"),
        hint: "Brak decyzji i kontaktu po stronie klienta",
      },
      {
        value: "no_match",
        label: label("no_match"),
        hint: "Nikogo nie wysłaliśmy albo nikt od nas nie przeszedł",
      },
    ],
  },
];

/**
 * Powody, które nadaje tylko NEXUS — nie ma ich w oknie zamykania, ale mają
 * grupę w hit ratio (28.10.2026: `no_activity` = przegrana, lustro
 * `HIT_RATIO_LOST_CLOSE_REASONS`).
 */
export const SYSTEM_CLOSE_REASON_GROUPS: Partial<Record<JobCloseReason, CloseReasonGroup>> = {
  no_activity: "lost",
};

/** Grupa powodu; `null` = „Inny” albo brak powodu (czeka na przegląd). */
export function closeReasonGroup(
  reason: JobCloseReason | null | undefined,
): CloseReasonGroup | null {
  if (!reason) return null;
  const system = SYSTEM_CLOSE_REASON_GROUPS[reason];
  if (system) return system;
  return (
    CLOSE_REASON_GROUPS.find((g) => g.reasons.some((r) => r.value === reason))?.key ??
    null
  );
}

export function closeReasonLabel(reason: JobCloseReason | null | undefined): string {
  return reason ? label(reason) : "Bez powodu (do przejrzenia)";
}

/** Powód, który da się wybrać w oknie (bez „Inny”). */
export function isSelectableCloseReason(
  reason: JobCloseReason | null | undefined,
): reason is JobCloseReason {
  if (reason && SYSTEM_CLOSE_REASON_GROUPS[reason]) return false;
  return closeReasonGroup(reason) !== null;
}
