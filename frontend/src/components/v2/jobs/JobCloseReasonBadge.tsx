/**
 * Powód zamknięcia w nagłówku zamkniętej rekrutacji (21.10.2026): czy liczy
 * się do hit ratio i dlaczego. „Inny” i brak powodu = do przejrzenia.
 */

import { Badge } from "@/components/ui/badge";
import { closeReasonGroup, closeReasonLabel } from "@/lib/job-close-reasons";
import type { JobCloseReason } from "@/types/client-profile";

const VARIANT = { won: "info", lost: "warning", neutral: "outline" } as const;

export function JobCloseReasonBadge({
  reason,
  notes,
}: {
  reason: JobCloseReason | null | undefined;
  notes?: string | null;
}) {
  const group = closeReasonGroup(reason);
  return (
    <>
      <Badge
        variant={group ? VARIANT[group] : "warning"}
        title={notes ?? undefined}
        data-testid="job-close-reason-badge"
      >
        Zamknięta · {closeReasonLabel(reason)}
      </Badge>
      {group === "neutral" ? <Badge variant="outline">Poza hit ratio</Badge> : null}
    </>
  );
}
