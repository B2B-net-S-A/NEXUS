/**
 * Zatwierdzenie CV w tle (generator CV v3).
 *
 * Edytor CV ma jeden przycisk „Zapisz”: zapisuje szkic, zamyka okno i zleca
 * zatwierdzenie (kontrola AI treści + utworzenie wersji) TUTAJ — w module,
 * który żyje dłużej niż okno. Wcześniej zatwierdzenie trwało w oknie z osobnym
 * potwierdzeniem „Sfinalizować?”, a zamknięcie okna przerywało czekanie
 * (`AbortSignal` edytora).
 *
 * Świadomie BEZ `AbortSignal`: zamknięcie okna ani przejście na inny ekran nie
 * może przerwać zatwierdzenia, o które rekruter poprosił. Zamknięta KARTA
 * przeglądarki przerywa — zostaje wtedy zapisany szkic bez zatwierdzenia,
 * a `needs_review` na liście CV to pokazuje.
 *
 * Wynik wraca toastem (liczba uwag kontroli AI albo prośba o ponowny zapis).
 * Starsze zatwierdzenie tego samego dokumentu, które przegrało z nowszym
 * (nieaktualna rewizja), nie zgłasza błędu — rekruter widziałby „nie udało
 * się” po udanym zapisie.
 */

import type { CVBrandedFinalizeResponseT } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";

export interface ApprovalNotifier {
  success(message: string): void;
  error(message: string): void;
}

export interface BackgroundApprovalRequest {
  /** Dokument: `stage:<id>` albo `generated:<id>`. */
  key: string;
  /** Kogo dotyczy (nazwisko) — do treści toasta. */
  label?: string;
  /** Właściwe zatwierdzenie — np. `candidateStageCvApi.branded.finalize`. */
  run: () => Promise<{ data: CVBrandedFinalizeResponseT }>;
  /** Po zakończeniu (sukces albo porażka) — odświeżenie zapytań. */
  onSettled?: () => void;
}

export type BackgroundApprovalOutcome =
  | { status: "approved"; findings: number; reviewStatus: string | null }
  | { status: "failed"; message: string }
  | { status: "superseded" };

const running = new Map<string, number>();
let sequence = 0;

/** Czy dla tego dokumentu trwa zatwierdzenie w tle. */
export function isBackgroundApprovalRunning(key: string): boolean {
  return running.has(key);
}

export function stageApprovalKey(stageId: number): string {
  return `stage:${stageId}`;
}

export function generatedApprovalKey(generatedId: number): string {
  return `generated:${generatedId}`;
}

function plural(count: number): string {
  if (count === 1) return "uwagę";
  const lastTwo = count % 100;
  const last = count % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return "uwagi";
  return "uwag";
}

/** Treść toasta po udanym zatwierdzeniu. */
export function describeApprovalSuccess(
  outcome: { findings: number; reviewStatus: string | null },
  label?: string,
): string {
  const who = label ? ` (${label})` : "";
  if (outcome.findings > 0) {
    return `CV zatwierdzone${who}. Kontrola treści zgłosiła ${outcome.findings} ${plural(outcome.findings)} — sprawdź przed wysyłką.`;
  }
  if (outcome.reviewStatus === "unverified") {
    return `CV zatwierdzone${who}. Kontrola treści nie wykonała się — sprawdź CV z oryginałem.`;
  }
  return `CV zatwierdzone${who}. Kontrola treści bez uwag.`;
}

export const APPROVAL_FAILED_HINT = "Nie udało się zatwierdzić — otwórz CV i zapisz ponownie.";

/**
 * Zleca zatwierdzenie i od razu wraca. Toasty idą przez `notify` — dostawca
 * toastów żyje w layoucie aplikacji, więc przeżywa zamknięcie edytora.
 */
export function startBackgroundApproval(
  request: BackgroundApprovalRequest,
  notify: ApprovalNotifier,
): Promise<BackgroundApprovalOutcome> {
  const token = ++sequence;
  running.set(request.key, token);
  const isLatest = () => running.get(request.key) === token;

  return request
    .run()
    .then((response): BackgroundApprovalOutcome => {
      const outcome = {
        status: "approved" as const,
        findings: Math.max(0, response.data?.content_review_findings ?? 0),
        reviewStatus: response.data?.content_review_status ?? null,
      };
      notify.success(describeApprovalSuccess(outcome, request.label));
      return outcome;
    })
    .catch((error: unknown): BackgroundApprovalOutcome => {
      // Nowsze zatwierdzenie tego samego dokumentu już ruszyło — to starsze
      // przegrało rewizją. Jego porażka nie jest wiadomością dla rekrutera.
      if (!isLatest()) return { status: "superseded" };
      const detail = apiErrorMessage(error, "");
      const message = detail ? `${APPROVAL_FAILED_HINT} (${detail})` : APPROVAL_FAILED_HINT;
      notify.error(message);
      return { status: "failed", message };
    })
    .finally(() => {
      if (isLatest()) running.delete(request.key);
      request.onSettled?.();
    });
}
