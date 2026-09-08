/**
 * „Następna akcja" na karcie pipeline'u i druga linia nagłówka kolumny
 * (krok 04 Pipeline, program „flow w języku C2", fala 3 „parytet z makietami").
 *
 * Do 09.2026 karta niosła nazwisko, rekrutera i wynik — czyli KTO stoi na
 * etapie, nigdy CO z nim zrobić. Dok mówił o tym wprost („świadomie BEZ
 * następnej akcji — backend nie niesie takiego pola") i to zdanie zostaje
 * prawdziwe: backend nadal nie ma pola „next action". Ten moduł niczego nie
 * zmyśla o KANDYDACIE — czyta wyłącznie fakty, które karta już niesie (etap,
 * wiek na etapie, stan weryfikacji, weto hiring managera) i przekłada je na
 * zdanie o PROCESIE: „na tym etapie następnym krokiem jest X". To sam opis
 * pipeline'u, nie wiedza o człowieku.
 *
 * Czysty moduł bez renderu i bez sieci — tablica z 26+ kartami woła go raz na
 * kartę przy renderze, więc nie wolno tu wejść żadnemu zapytaniu.
 */

import { terminalOf } from "@/lib/kanban-terminal";
import {
  CV_SENT_STAGE,
  groupKeyForColumn,
  type PipelineGroupKey,
} from "@/lib/pipeline-flow";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";

/** Ton wiersza: zwykły, zaległy (po terminie) albo zablokowany bramką. */
export type NextActionTone = "normal" | "due" | "gate";

/** Rodzaj akcji — steruje IKONĄ, nie treścią. */
export type NextActionKind =
  | "analysis"
  | "screening"
  | "verification"
  | "cv"
  | "client"
  | "offer"
  | "contract"
  | "none";

export interface NextAction {
  label: string;
  tone: NextActionTone;
  kind: NextActionKind;
}

/**
 * Etykieta „nie ma co robić dalej" — filtr „Bez następnej akcji" w lewej
 * kolumnie wiąże się z TĄ stałą, nie z własną kopią stringa.
 */
export const NO_NEXT_ACTION_LABEL = "Brak następnej akcji";

/** Powyżej tylu dni na etapie karta jest „zaległa" (próg z `CandidateKanbanCard`). */
export const STUCK_DAYS = 7;

/** Do tylu dni świeża karta wejściowa jest jeszcze „do analizy dziś". */
const FRESH_INTAKE_DAYS = 1;

export interface NextActionContext {
  /** SLA klienta w dniach roboczych (karta klienta). `null` = nie ustawiono. */
  slaDays?: number | null;
  /**
   * Grupa etapu policzona nad CAŁĄ tablicą ({@link groupKanbanColumns}).
   *
   * Bez niej moduł klasyfikuje kolumnę sam, ale bez pozycji w szablonie nie
   * odróżni własnego etapu wewnętrznego PO screeningu („Przepuszczony przez
   * DZ") od etapu wejściowego — taka karta dostałaby „Umów screening" zamiast
   * „Wyślij CV do klienta". Tablica zna całą listę, więc podaje grupę wprost.
   */
  group?: PipelineGroupKey;
}

const KIND_FOR_GROUP: Record<PipelineGroupKey, NextActionKind> = {
  intake: "analysis",
  screening: "screening",
  verification: "cv",
  client: "client",
  contract: "contract",
  closed: "none",
};

/**
 * Co dalej z tą kartą — z danych, które karta niesie.
 *
 * Kolejność gałęzi jest wiążąca:
 *  1. etap terminalny (odrzucony/wycofany) NIE ma następnej akcji — i to musi
 *     wygrać z bramkami, inaczej odrzucony kandydat z wetem HM dostawałby
 *     „Bramka: weto HM" na karcie, z której nikt go już nie rusza,
 *  2. `pending` — czekamy na cudzą decyzję, nie na własną akcję,
 *  3. weto hiring managera — każdy ruch nie-terminalny jest zablokowany,
 *  4. dopiero potem etap.
 */
export function nextActionFor(
  item: KanbanItem,
  column: KanbanColumn,
  ctx: NextActionContext = {},
): NextAction {
  const group = ctx.group ?? groupKeyForColumn(column);

  if (group === "closed") {
    return { label: "", tone: "normal", kind: "none" };
  }

  // „Zatrudniony" jest terminalem, ale należy do grupy „Umowa → zatrudnieni",
  // więc guard wyżej go nie łapie. Bramki niżej też nie mogą: karta osoby już
  // zatrudnionej z zaległym `pending` albo wetem HM (schemat tego nie
  // wyklucza) mówiłaby „czeka na akceptację stawki" o kimś, kogo nikt
  // nie rusza. Jedyna prawdziwa następna akcja to przekazanie do Delivery.
  if (terminalOf(column) === "hired") {
    return { label: "Przekaż do Delivery", tone: "normal", kind: "contract" };
  }

  if (item.verification_status === "pending") {
    return {
      label: "Czeka na akceptację stawki",
      tone: "gate",
      kind: "verification",
    };
  }

  if (item.hm_veto) {
    return { label: "Bramka: weto HM", tone: "gate", kind: KIND_FOR_GROUP[group] };
  }

  const days = item.days_in_stage ?? 0;

  switch (group) {
    case "intake":
      if (days <= FRESH_INTAKE_DAYS) {
        return { label: "Analiza CV · dziś", tone: "normal", kind: "analysis" };
      }
      if (days < STUCK_DAYS) {
        return { label: "Umów screening", tone: "normal", kind: "screening" };
      }
      // Tydzień bez ruchu na etapie wejściowym znaczy, że NIKT nie umówił
      // screeningu — karta mówi o tym wprost zamiast powtarzać w kółko
      // podpowiedź, której nikt nie wykonał.
      return { label: NO_NEXT_ACTION_LABEL, tone: "due", kind: "analysis" };

    case "screening": {
      const sla = ctx.slaDays;
      const overdue = days >= STUCK_DAYS || (sla != null && days >= sla);
      return {
        label: "Uzupełnij arkusz screeningu",
        tone: overdue ? "due" : "normal",
        kind: "screening",
      };
    }

    case "verification":
      return { label: "Wyślij CV do klienta", tone: "normal", kind: "cv" };

    case "client":
      if (column.stage === CV_SENT_STAGE) {
        return {
          label: "Umów interview / feedback klienta",
          tone: "normal",
          kind: "client",
        };
      }
      if (column.stage === "client_interview") {
        return { label: "Zbierz feedback HM", tone: "normal", kind: "client" };
      }
      if (column.stage === "acceptance" || column.stage === "negotiation") {
        return {
          label: "Reakcja kandydata na ofertę",
          tone: "normal",
          kind: "offer",
        };
      }
      // Własny etap zewnętrzny bez legacy enuma („Preparation Meeting").
      // Wiemy tyle, że kandydat jest u klienta — i tylko tyle mówimy.
      return { label: "Feedback klienta", tone: "normal", kind: "client" };

    case "contract":
      if (terminalOf(column) === "hired" || column.stage === "onboarding") {
        return { label: "Przekaż do Delivery", tone: "normal", kind: "contract" };
      }
      return { label: "Podpis umowy", tone: "normal", kind: "contract" };

    default:
      return { label: "", tone: "normal", kind: "none" };
  }
}

/** Karta bez następnej akcji — filtr lewej kolumny. */
export function hasNoNextAction(action: NextAction): boolean {
  return action.label === NO_NEXT_ACTION_LABEL;
}

// ── Druga linia nagłówka kolumny ──────────────────────────────────────

export type ColumnHintTone = "normal" | "warn" | "bad";

export interface ColumnSlaHint {
  /** Lewa strona — czym ta kolumna jest wobec SLA. Zawsze coś mówi. */
  left: string;
  /** Prawa strona — `null`, gdy nie ma czego mierzyć (kolumna pusta). */
  right: string | null;
  rightTone: ColumnHintTone;
}

export interface ColumnSlaContext {
  slaDays?: number | null;
  /** Najstarsza karta w kolumnie (dni na etapie). `null` = kolumna pusta. */
  oldestDays?: number | null;
  group?: PipelineGroupKey;
}

/**
 * Druga linia nagłówka kolumny: SLA klienta po lewej, najstarsza karta po
 * prawej.
 *
 * SLA biegnie od wejścia w Screening (karta klienta — `sla_business_days`),
 * więc TYLKO kolumna screeningu przelicza je na „ile zostało". Pozostałe
 * kolumny mówią „SLA: —" zamiast milczeć: pusta linia czytałaby się jak
 * „zdążamy", a prawda jest taka, że tam nikt nic nie mierzy.
 */
export function columnSlaHint(
  column: KanbanColumn,
  ctx: ColumnSlaContext = {},
): ColumnSlaHint {
  const group = ctx.group ?? groupKeyForColumn(column);
  const oldest = ctx.oldestDays ?? null;

  if (group === "closed") {
    return { left: "powody w doku", right: null, rightTone: "normal" };
  }
  if (group === "verification") {
    return { left: "→ CV do klienta", right: null, rightTone: "normal" };
  }

  const sla = ctx.slaDays;
  if (group === "screening" && sla != null) {
    if (oldest == null) {
      return { left: `SLA klienta: ${sla} d`, right: null, rightTone: "normal" };
    }
    const remaining = sla - oldest;
    if (remaining <= 0) {
      return {
        left: `SLA klienta: ${sla} d`,
        right: "po terminie",
        rightTone: "bad",
      };
    }
    return {
      left: `SLA klienta: ${sla} d`,
      right: `${remaining} d zostało`,
      rightTone: remaining <= 2 ? "warn" : "normal",
    };
  }

  return {
    left: "SLA: —",
    right: oldest == null ? null : `najstarszy ${oldest} d`,
    rightTone: oldest != null && oldest >= STUCK_DAYS ? "warn" : "normal",
  };
}

/** Najstarsza karta w kolumnie (dni), albo `null` dla pustej kolumny. */
export function oldestDaysInColumn(column: KanbanColumn): number | null {
  let oldest: number | null = null;
  for (const item of column.items) {
    const days = item.days_in_stage;
    if (days == null) continue;
    if (oldest == null || days > oldest) oldest = days;
  }
  return oldest;
}
