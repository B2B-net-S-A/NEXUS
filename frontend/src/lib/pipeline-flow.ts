/**
 * Czyste helpery kroków 05 („Screening") i 06 („CV do klienta") programu
 * „flow w języku C2" — docs/c2-flow-program.md, PR 6/7.
 *
 * Oba kroki czytają TĘ SAMĄ odpowiedź `GET /api/pipeline/kanban/{job_id}`,
 * którą strona rekrutacji pobiera już dziś dla listwy kroków — żadnego nowego
 * endpointu. Ten moduł nie renderuje niczego i nie woła sieci: przekłada
 * kolumny kanbana na kolejki obu stanowisk i liczy bramkę ruchu. Dzięki temu
 * da się to przetestować bez montowania ekranu, a warstwa widoku nie hoduje
 * własnej kopii tych samych reguł.
 */

import { colId, type KanbanColumn, type KanbanItem } from "@/components/v2/pages/kanban-shared";

/** Legacy-enumy etapów, na których stoją oba stanowiska (`PipelineStage`). */
export const SCREENING_STAGE = "screening";
export const VERIFIED_STAGE = "verified";
export const CV_SENT_STAGE = "cv_sent";

export interface FlowQueueEntry {
  item: KanbanItem;
  /** Kolumna, w której karta stoi TERAZ — potrzebna do `requestMove`. */
  col: KanbanColumn;
  colId: string;
}

/**
 * Znajdź kolumnę po legacy-enumie etapu.
 *
 * Szablon rekrutacji może mieć własne nazwy kolumn (`stage_def_id`), ale każda
 * zmapowana kolumna niesie też `stage` z `PipelineStage` — i to po nim, nie po
 * nazwie, rozpoznaje etapy backend (`dst.stage === "cv_sent"` w `KanbanBoardV2`).
 * Kolumna spoza szablonu („Poza szablonem") raportuje `stage: "new"` i nigdy
 * nie jest celem ruchu — nie trafia tu z definicji.
 */
export function findStageColumn(
  columns: KanbanColumn[],
  stage: string,
): KanbanColumn | null {
  return columns.find((c) => c.stage === stage) ?? null;
}

/** Kandydaci stojący na wskazanym etapie, w kolejności z tablicy. */
function entriesForStage(columns: KanbanColumn[], stage: string): FlowQueueEntry[] {
  const col = findStageColumn(columns, stage);
  if (!col) return [];
  return col.items.map((item) => ({ item, col, colId: colId(col) }));
}

/**
 * Kolejka kroku 05: kandydaci na etapie „Screening".
 *
 * Świadomie BEZ etapów zewnętrznych (`client_interview` i dalej), na których
 * `KanbanBoardV2` też otwiera arkusz Championa — tam screening robi się
 * DLA KLIENTA przed rozmową i to jest krok 07, nie 05. Wrzucenie ich tutaj
 * zamieniłoby „kto czeka na moją rozmowę" w „kto ma gdziekolwiek arkusz".
 */
export function selectScreeningQueue(columns: KanbanColumn[]): FlowQueueEntry[] {
  return entriesForStage(columns, SCREENING_STAGE);
}

/**
 * Karty czekające na akceptację stawki — na DOWOLNYM etapie, nie tylko
 * „Zweryfikowany".
 *
 * `verification_status = "pending"` stawia backend przy ruchu na `verified`,
 * ale karta zostaje w kolumnie docelowej, a odrzucenie weryfikacji cofa ją na
 * etap poprzedni. Skanujemy więc wszystkie kolumny — kolejka, która zna tylko
 * jedną, po cichu gubiłaby część spraw.
 */
export function selectPendingVerifications(
  columns: KanbanColumn[],
): FlowQueueEntry[] {
  const out: FlowQueueEntry[] = [];
  for (const col of columns) {
    if (col.category === "terminal") continue;
    for (const item of col.items) {
      if (item.verification_status === "pending") {
        out.push({ item, col, colId: colId(col) });
      }
    }
  }
  return out;
}

/**
 * Kolejka kroku 06: zweryfikowani, czyli gotowi do wysyłki CV.
 *
 * Karty „Pending" ZOSTAJĄ w kolejce (widać je z powodem), bo to nadal ci sami
 * ludzie, na których czeka klient — ale bramka ruchu je blokuje, patrz
 * {@link moveBlockedReason}. Ukrycie ich zamieniłoby czekającą sprawę
 * w niewidzialną.
 */
export function selectVerifiedQueue(columns: KanbanColumn[]): FlowQueueEntry[] {
  return entriesForStage(columns, VERIFIED_STAGE);
}

/** Ilu kandydatów jest już u klienta — „CV Wysłane" i dalsze etapy zewnętrzne. */
export function countAtClient(columns: KanbanColumn[]): number {
  return columns.reduce((sum, col) => {
    if (col.category === "terminal") return sum;
    if (col.stage === CV_SENT_STAGE || col.category === "external") {
      return sum + col.items.length;
    }
    return sum;
  }, 0);
}

export interface MoveGateInput {
  item: KanbanItem;
  readOnly: boolean;
  /** Etap docelowy jest terminalny (`rejected`/`withdrawn`)? */
  terminal?: boolean;
}

/**
 * Powód, dla którego ruchu NIE wolno wykonać — albo `null`, gdy wolno.
 *
 * Lustro bramki z `KanbanBoardV2` (i `assert_candidate_move_eligible` po
 * stronie serwera), świadomie z tymi samymi trzema regułami:
 *  1. brak prawa zapisu blokuje wszystko,
 *  2. ruchy TERMINALNE przechodzą zawsze — weto HM nie może uwięzić kandydata
 *     w procesie, z którego trzeba go wypisać,
 *  3. weto hiring managera blokuje każdy ruch nie-terminalny.
 *
 * `verification_status = "pending"` NIE jest tu bramką ruchu (backend go tak
 * nie traktuje) — jest ostrzeżeniem pokazywanym osobno.
 */
export function moveBlockedReason({
  item,
  readOnly,
  terminal = false,
}: MoveGateInput): string | null {
  if (readOnly) return "Tylko do odczytu — brak prawa zapisu w tym pipeline.";
  if (terminal) return null;
  if (item.hm_veto) {
    return (
      `Hiring manager tej rekrutacji już odrzucił tego kandydata po rozmowie — ` +
      `${item.hm_veto.rejection_reason_name}.`
    );
  }
  return null;
}

/** Imię i nazwisko z karty, z uczciwym fallbackiem. */
export function itemFullName(item: KanbanItem): string {
  return `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat";
}
