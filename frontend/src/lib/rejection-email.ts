/**
 * Mail odrzucenia do kandydata — kiedy okno odrzucenia go proponuje i co
 * powiedzieć, gdy serwer go nie zaplanował.
 *
 * Runda 9 (R9-N11-2): okno liczyło dostępność maila z KATEGORII kolumny
 * (`external`), a serwer z kodu etapu — przy „CV wysłane” (kategoria
 * `internal`) checkboxa nie było, a przy etapach umowy zaznaczony mail po
 * cichu nie powstawał. Jedna reguła po obu stronach: lustro
 * `rejection_email_scheduler.previous_is_client_visible` (kod etapu z listy
 * albo kolumna Tablicy „CV wysłane” / „Rozmowa u klienta” / „Umowa”).
 */
import { placeStage, type StageLike } from "@/lib/board-stages";
import { countPl } from "@/lib/plural-pl";

/** Lustro `TRIGGER_PREVIOUS_STAGES` w `rejection_email_scheduler.py`. */
export const REJECTION_EMAIL_TRIGGER_STAGES: ReadonlySet<string> = new Set([
  "cv_sent",
  "client_interview",
  "acceptance",
  "negotiation",
  "onboarding",
]);

/** Lustro `TRIGGER_PREVIOUS_COLUMNS` w `rejection_email_scheduler.py`. */
const TRIGGER_COLUMNS: ReadonlySet<string> = new Set([
  "cv_sent",
  "client_interview",
  "contract",
]);

/** Czy osoba z tego etapu była widoczna dla klienta (mail ma sens). */
export function rejectionEmailAvailableFrom(
  col: StageLike | null | undefined
): boolean {
  if (!col) return false;
  if (col.stage && REJECTION_EMAIL_TRIGGER_STAGES.has(col.stage)) return true;
  return TRIGGER_COLUMNS.has(placeStage(col).column);
}

/** Status z `POST /api/pipeline/move` → `rejection_email_status`. */
export type RejectionEmailStatus =
  | "scheduled"
  | "no_mailbox"
  | "not_client_visible"
  | "no_candidate_email"
  | "no_permission";

const SKIP_MESSAGE: Record<Exclude<RejectionEmailStatus, "scheduled">, string> = {
  no_mailbox:
    "Mail odrzucenia nie wyjdzie — nie masz podłączonej skrzynki Microsoft 365 " +
    "(Ustawienia → Integracje). Mail wychodzi z Twojej skrzynki.",
  not_client_visible:
    "Mail odrzucenia nie został zaplanowany — wysyłamy go tylko osobom, " +
    "których CV trafiło do klienta.",
  no_candidate_email:
    "Mail odrzucenia nie został zaplanowany — kandydat nie ma adresu e-mail.",
  no_permission:
    "Mail odrzucenia nie został zaplanowany — nie masz uprawnień do wysyłki.",
};

/** Zdanie dla toastu, gdy zaznaczony mail NIE został zaplanowany. */
export function rejectionEmailSkipMessage(
  status: string | null | undefined
): string | null {
  if (!status || status === "scheduled") return null;
  return (
    SKIP_MESSAGE[status as Exclude<RejectionEmailStatus, "scheduled">] ??
    "Mail odrzucenia nie został zaplanowany."
  );
}

/** Krótkie powody do jednego zdania przy odrzuceniu kilku osób naraz. */
const SKIP_SHORT: Record<Exclude<RejectionEmailStatus, "scheduled">, string> = {
  no_mailbox: "brak podłączonej skrzynki Microsoft 365",
  not_client_visible: "CV nie trafiło do klienta",
  no_candidate_email: "brak adresu e-mail kandydata",
  no_permission: "brak uprawnień do wysyłki",
};

/**
 * Runda 10 (R10-V2-1): odrzucenie kilku osób — JEDNO zdanie o mailach,
 * których serwer nie zaplanował (zamiast ciszy albo toastu na osobę).
 */
export function rejectionEmailBulkSkipMessage(
  statuses: ReadonlyArray<string | null | undefined>
): string | null {
  const skipped = statuses.filter(
    (s): s is string => !!s && s !== "scheduled"
  );
  if (skipped.length === 0) return null;
  if (skipped.length === 1) return rejectionEmailSkipMessage(skipped[0]);
  const counts = new Map<string, number>();
  for (const status of skipped) {
    const label =
      SKIP_SHORT[status as Exclude<RejectionEmailStatus, "scheduled">] ??
      "inny powód";
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  const reasons = Array.from(counts, ([label, n]) =>
    counts.size > 1 ? `${label} (${n})` : label
  ).join(", ");
  return (
    `Mail odrzucenia nie został zaplanowany dla ` +
    `${countPl(skipped.length, "osoby", "osób", "osób")} — ${reasons}.`
  );
}

/** Wynik `POST /api/pipeline/move` potrzebny do komunikatu o mailu. */
export interface RejectionEmailMoveResult {
  scheduled_rejection_email_id?: number | null;
  rejection_email_status?: string | null;
}

export interface RejectionEmailToasts {
  showActionToast: (
    message: string,
    options: { actionLabel: string; onAction: () => void | Promise<void>; durationMs?: number }
  ) => void;
  showSuccess: (message: string) => void;
  showError: (message: string) => void;
}

/**
 * Runda 10 (R10-V2-1): jeden komunikat po odrzuceniu dla KAŻDEGO ekranu —
 * zaplanowany mail dostaje „Cofnij wysyłkę”, a zaznaczony mail, którego
 * serwer nie zaplanował, zdanie z powodem. Warsztat rozmów pokazywał samo
 * „Zapisano decyzję.”, więc rekruter bez skrzynki M365 nie wiedział, że mail
 * nie wyjdzie.
 */
export function announceRejectionEmail(
  data: RejectionEmailMoveResult | null | undefined,
  {
    requested,
    reportSkip = true,
    toast,
    cancel,
  }: {
    /** Czy rekruter zaznaczył mail odrzucenia. */
    requested: boolean | null | undefined;
    /** `false` = wołający zbiera powody i mówi o nich raz (ruch zbiorczy). */
    reportSkip?: boolean;
    toast: RejectionEmailToasts;
    cancel: (scheduledId: number) => Promise<unknown>;
  }
): void {
  const scheduledId = data?.scheduled_rejection_email_id;
  if (scheduledId) {
    toast.showActionToast("Email odrzucenia zostanie wysłany za 15 minut.", {
      actionLabel: "Cofnij wysyłkę",
      onAction: async () => {
        try {
          await cancel(scheduledId);
          toast.showSuccess("Anulowano wysyłkę emaila.");
        } catch (err) {
          console.error("rejection email cancel failed", err);
          toast.showError("Nie udało się anulować wysyłki.");
        }
      },
      durationMs: 10_000,
    });
    return;
  }
  if (!requested || !reportSkip) return;
  const skip = rejectionEmailSkipMessage(data?.rejection_email_status);
  if (skip) toast.showError(skip);
}
