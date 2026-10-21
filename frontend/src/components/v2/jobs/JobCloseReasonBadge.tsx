/**
 * Powód zamknięcia w nagłówku zamkniętej rekrutacji (21.10.2026): czy liczy
 * się do hit ratio i dlaczego. „Inny” i brak powodu = do przejrzenia.
 * Jedna krótka plakietka, bo nagłówek przy 1280 px ucinał pełną etykietę
 * i chował drugą („Poza hit ratio”) pod zakładkami; grupa w dymku razem
 * z pełnym powodem i uzasadnieniem.
 */

import { Badge } from "@/components/ui/badge";
import { closeReasonGroup, closeReasonLabel } from "@/lib/job-close-reasons";
import type { JobCloseReason } from "@/types/client-profile";

const VARIANT = { won: "info", lost: "warning", neutral: "outline" } as const;

const GROUP_NOTE = {
  won: "Liczy się do hit ratio jako wygrana.",
  lost: "Liczy się do hit ratio jako przegrana.",
  neutral: "Nie liczy się do hit ratio.",
} as const;

const SHORT: Partial<Record<JobCloseReason, string>> = {
  filled_by_us: "obsadzona przez nas",
  competitor: "wzięła inna firma",
  duplicate: "duplikat",
  internal_hire: "zatrudnienie u klienta",
  budget: "anulowana przez klienta",
  paused: "wstrzymana",
  client_ghosted: "klient milczy",
  no_match: "bez kandydata",
};

export function JobCloseReasonBadge({
  reason,
  notes,
}: {
  reason: JobCloseReason | null | undefined;
  notes?: string | null;
}) {
  const group = closeReasonGroup(reason);
  const short = (reason && SHORT[reason]) || "powód do przejrzenia";
  const title = [
    closeReasonLabel(reason),
    group ? GROUP_NOTE[group] : "Liczy się jak przegrana, dopóki ktoś nie wybierze powodu.",
    notes,
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <Badge
      variant={group ? VARIANT[group] : "warning"}
      title={title}
      className="whitespace-nowrap"
      data-testid="job-close-reason-badge"
    >
      Zamknięta · {short}
    </Badge>
  );
}
