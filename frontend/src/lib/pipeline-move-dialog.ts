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
  | "rejection";

export function moveDialogFor(col: TerminalAwareColumn): PipelineMoveDialog {
  if (col.stage === "verified") return "verified_rate";
  if (col.stage === "cv_sent") return "client_rate";
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
