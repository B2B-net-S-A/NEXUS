// „Mój zespół” — teksty komórek (czyste funkcje, testowalne bez zapytań).
// Pasek „Dziś”, mini-tydzień, pasek godzin i karty decyzji: `team-week.ts`.
//
// `null` z serwera = moduł wyłączony albo brak prawa → „—”, nigdy „0”.

import { daysLabel } from "@/components/hr/leave/leave-format";
import type { EmploymentType } from "@/lib/api/hr";
import type { TeamBonuses, TeamLeave } from "@/lib/api/hr-team";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";

export interface Cell {
  text: string;
  sub?: string;
  tone?: "warning" | "muted";
}

const DASH: Cell = { text: "—", tone: "muted" };

/**
 * Nieobecności: pula tylko u osób z płatną pulą (UoP albo B2B z umowną pulą
 * > 0 — sam wiersz z zerem to nie pula), u reszty zaplanowane dni (decyzja
 * Artura 17.10.2026).
 */
export function leaveCell(leave: TeamLeave | null, form?: EmploymentType): Cell {
  if (!leave) return DASH;
  const planned = Number(leave.planned_days);
  const pending = Number(leave.pending_days);
  const parts: string[] = [];
  if (planned > 0) parts.push(`zaplanowane ${daysLabel(planned)}`);
  if (pending > 0) parts.push(`czeka ${daysLabel(pending)}`);
  if (leave.has_paid_pool && leave.remaining_days !== null) {
    return {
      // Pula B2B jest umowna — „urlop” tylko przy umowie o pracę (D4).
      text: `zostało ${daysLabel(leave.remaining_days)} ${form && form !== "uop" ? "z puli" : "urlopu"}`,
      sub: parts.join(" · ") || undefined,
    };
  }
  if (parts.length === 0) return { text: "nic zaplanowanego", tone: "muted" };
  return { text: parts[0], sub: parts.slice(1).join(" · ") || undefined };
}

/** Premie w drodze: liczba i suma (bez stawek, D2); propozycje do wiadomości. */
export function bonusCell(bonuses: TeamBonuses | null): Cell {
  if (!bonuses || bonuses.count === 0) return DASH;
  const total = bonuses.totals.map((item) => formatMoney(item.amount, item.currency)).join(" + ");
  return {
    text: `${bonuses.count} · ${total}`,
    sub: bonuses.proposals
      ? `${countPl(bonuses.proposals, "propozycja", "propozycje", "propozycji")} — decydują Płace`
      : undefined,
  };
}
