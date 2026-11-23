/**
 * „Zatrzymaj do podpisu przedwstępnej” (0762, decyzje Artura 23.11.2026).
 *
 * Dwa źródła blokady: ustawienie rekrutacji (`jobs.pre_contract_rule`,
 * ustawiane na `/jobs/new` i w nagłówku) i wybór przy prośbie o osobę
 * (`blocks_move`: null = jak rekrutacja, true = stop, false = wyjątek).
 * Blokadę liczy serwer (`services/pre_contract_stop.py`) i zatrzymuje ruch
 * 409 `PRE_CONTRACT_NOT_SIGNED`; front tylko ją pokazuje.
 * Reguła: `docs/claude/rekrutacja-tablica/stop-do-podpisu-przedwstepnej.md`.
 */

import type {
  CardPreContract,
  PreContractRuleStage,
  PreContractStop,
} from "@/lib/api/preContracts";
import { BOARD_COLUMN_ORDER, type BoardColumnKey } from "@/lib/board-stages";
import { getUserRoles, type UserRole } from "@/store/auth";

/** Kto ustawia i zdejmuje blokadę (lustro `pre_contract_stop.can_set_stop`;
 *  serwer dodatkowo zawęża DL-a do jego klientów). */
export const PRE_CONTRACT_STOP_ROLES: readonly UserRole[] = ["admin", "head_of_recruitment", "delivery_lead"];

export const RULE_STAGE_OPTIONS: ReadonlyArray<{ value: PreContractRuleStage; label: string; short: string }> = [
  { value: "cv_sent", label: "Przed wysłaniem CV", short: "przed CV" },
  { value: "client_interview", label: "Przed rozmową u klienta", short: "przed rozmową" },
  { value: "b2b_contract", label: "Przed umową B2B", short: "przed B2B" },
];

/** Napis na strzałce karty, gdy następny krok jest zablokowany. */
export const PRE_CONTRACT_STOP_GAP = "Stop: przedwstępna niepodpisana";

export function canSetPreContractStop(user: Parameters<typeof getUserRoles>[0]): boolean {
  if (!user) return false;
  return getUserRoles(user).some((r) => PRE_CONTRACT_STOP_ROLES.includes(r));
}

export function ruleStageLabel(stage: PreContractRuleStage): string {
  return RULE_STAGE_OPTIONS.find((o) => o.value === stage)?.label ?? "";
}

export function ruleStageShort(stage: PreContractRuleStage): string {
  return RULE_STAGE_OPTIONS.find((o) => o.value === stage)?.short ?? "";
}

export function nextColumn(from: BoardColumnKey | null | undefined): BoardColumnKey | null {
  if (!from) return null;
  return BOARD_COLUMN_ORDER[BOARD_COLUMN_ORDER.indexOf(from) + 1] ?? null;
}

/** Karta stoi przed ruchem na `to` (kolumna blokady z plakietki serwera). */
export function cardStopsBefore(meta: CardPreContract | null | undefined, to: BoardColumnKey | null): boolean {
  const stop = meta?.stop_column as BoardColumnKey | null | undefined;
  if (!stop || !to) return false;
  const at = BOARD_COLUMN_ORDER.indexOf(stop);
  return at >= 0 && BOARD_COLUMN_ORDER.indexOf(to) >= at;
}

function dayPl(iso?: string | null): string {
  if (!iso) return "";
  const [, m, d] = iso.slice(0, 10).split("-");
  return d && m ? `${d}.${m}` : "";
}

/** „ustawienie rekrutacji — Olaf M., 23.11” / „przy tej osobie — Igor T., 23.11”. */
export function stopOriginText(stop: Pick<PreContractStop, "origin" | "set_by_name" | "set_at">): string {
  const who = [stop.set_by_name, dayPl(stop.set_at)].filter(Boolean).join(", ");
  const source = stop.origin === "job" ? "ustawienie rekrutacji" : "przy tej osobie";
  return who ? `${source} — ${who}` : source;
}
