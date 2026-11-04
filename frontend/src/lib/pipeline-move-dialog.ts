/**
 * Jakiego dialogu wymaga ruch na daną kolumnę kanbana.
 *
 * `KanbanBoardV2.requestMove` rozgałęzia się na cztery przypadki, zanim
 * cokolwiek wyśle: stawka kandydata („Zweryfikowany"), stawka do klienta
 * („CV Wysłane"), potwierdzenie zatrudnienia (`hired`) i powód terminalny
 * (`rejected`/`withdrawn`). Dok „Decyzja" w kroku 07 pokazuje pigułki „Przenieś
 * na etap" i musi wiedzieć DOKŁADNIE to samo — inaczej albo wysyłałby ruch
 * z pominięciem modala (kandydat na „CV Wysłane" bez stawki do klienta), albo
 * blokowałby coś, co tablica przepuszcza.
 *
 * Osobny moduł, a nie kopia warunków w doku: dwie listy nazw etapów rozjeżdżają
 * się przy pierwszej zmianie szablonu, a objaw jest cichy (ruch przechodzi, tyle
 * że bez zapytania o stawkę). Precedens w repo: `kanban-terminal.ts`.
 */

import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import { terminalOf, type TerminalAwareColumn } from "@/lib/kanban-terminal";

export type PipelineMoveDialog =
  /** Wysyłamy od razu — `POST /api/pipeline/move` bez dodatkowego pytania. */
  | "none"
  /** „Zweryfikowany" — modal stawki oczekiwanej kandydata. */
  | "verified_rate"
  /** „CV Wysłane" — modal stawki do klienta. */
  | "client_rate"
  /** `hired` — jawne potwierdzenie (powstaje szkic kontraktu i zamówienia). */
  | "hired_confirm"
  /** `rejected` / `withdrawn` — modal powodu (`RejectionV2`). */
  | "rejection"
  /**
   * „Rozmowa u klienta” — „Kiedy rozmowa?” (20.10.2026). Bez terminu w NEXUSIE
   * nie było telefonu po rozmowie ani przypomnienia o pytaniach klienta (88 z 99
   * par w 30 dniach). Pytanie można pominąć („Nie znam jeszcze terminu”).
   */
  | "interview_date";

export function moveDialogFor(col: TerminalAwareColumn): PipelineMoveDialog {
  if (col.stage === "verified") return "verified_rate";
  if (col.stage === "cv_sent") return "client_rate";
  if (col.stage === "client_interview") return "interview_date";
  const terminal = terminalOf(col);
  if (terminal === "hired") return "hired_confirm";
  if (terminal === "rejected" || terminal === "withdrawn") return "rejection";
  return "none";
}

/**
 * Polski powód wyszarzenia pigułki w doku, który nie hostuje danego dialogu.
 *
 * `null` = ruch da się wykonać stąd. Bramka dopuszczalności programu wymaga,
 * żeby akcja była WIDOCZNA i wyszarzona z powodem, a nie znikała ani nie
 * kończyła się 409 po kliknięciu.
 */
export function dialogUnavailableReason(
  dialog: PipelineMoveDialog,
): string | null {
  switch (dialog) {
    case "verified_rate":
      return "Ten ruch pyta o stawkę kandydata — wykonaj go na tablicy pipeline'u.";
    case "client_rate":
      return "Ten ruch pyta o stawkę do klienta — wykonaj go na tablicy pipeline'u.";
    case "hired_confirm":
      return "Zatrudnienie potwierdzasz na tablicy pipeline'u — powstaje szkic kontraktu i zamówienia.";
    default:
      return null;
  }
}

/**
 * Czy przesunięcie na „Rozmowa u klienta” ma zapytać o termin. Nie pyta, gdy
 * para ma już zaplanowaną rozmowę albo otwarty wniosek o terminy od klienta —
 * termin ustala wtedy ścieżka „Terminy od klienta”.
 */
export function needsInterviewDate(item: Pick<KanbanItem, "interview_badge">): boolean {
  const badge = item.interview_badge;
  if (!badge) return true;
  const interview = badge.steps?.find((s) => s.key === "interview");
  if (interview?.state === "scheduled") return false;
  const slots = badge.slot_request?.status;
  return slots !== "awaiting_recruiter" && slots !== "awaiting_dl";
}

/**
 * Czy ruch WRACA na kolumnę `dst` z kolumny, która stoi za nią w szablonie
 * (np. „Cofnij akceptację klienta” → „Rozmowa u klienta”). Taka karta była
 * już na rozmowie — „Kiedy rozmowa u klienta?” pytałoby o termin rozmowy,
 * która się odbyła (audyt 21.10.2026). Zamknięci (odrzucony, rezygnacja,
 * zatrudniony) nie liczą się: przywrócenie z nich nie mówi, czy rozmowa była.
 */
export function movesBackTo<C extends TerminalAwareColumn>(
  columns: readonly C[],
  srcColId: string,
  dst: C,
  idOf: (col: C) => string,
): boolean {
  const srcIdx = columns.findIndex((c) => idOf(c) === srcColId);
  const dstIdx = columns.findIndex((c) => idOf(c) === idOf(dst));
  if (srcIdx < 0 || dstIdx < 0) return false;
  return srcIdx > dstIdx && terminalOf(columns[srcIdx]) == null;
}
