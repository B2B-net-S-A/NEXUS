"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useConvertLead, useUpdateLead, type Lead } from "@/lib/api/sales";

/** Powody, gdy serwer ich nie podał (np. wyłączony kanał); te same co w `signals.py`. */
export const DEFAULT_REJECT_REASONS = [
  "Nieaktualne",
  "Nie nasza usługa",
  "Już wiemy",
  "Słabe źródło",
  "Inna firma",
] as const;

interface SignalActionsProps {
  lead: Lead;
  reasons?: readonly string[];
}

/** Decyzja handlowca: szansa albo odrzucenie z powodem, który wraca do bota. */
export function SignalActions({ lead, reasons = DEFAULT_REJECT_REASONS }: SignalActionsProps) {
  const router = useRouter();
  const convert = useConvertLead();
  const update = useUpdateLead();
  const { showError, showSuccess } = useToast();
  const [rejecting, setRejecting] = useState(false);
  const onError = (error: unknown) => showError(apiErrorMessage(error, "Nie udało się zapisać decyzji."));

  if (lead.status === "converted" && lead.opportunity_id) {
    return (
      <Button size="sm" variant="outline" onClick={() => router.push(`/sales/opportunities/${lead.opportunity_id}`)}>
        Otwórz szansę
      </Button>
    );
  }
  if (lead.status === "dismissed") {
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>Odrzucone{lead.dismissed_reason ? `: ${lead.dismissed_reason}` : ""}</span>
        <Button
          size="sm"
          variant="quiet"
          loading={update.isPending}
          onClick={() => update.mutate({ id: lead.id, status: "new" }, { onError })}
        >
          Przywróć
        </Button>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          loading={convert.isPending}
          onClick={() =>
            convert.mutate(lead.id, {
              onSuccess: (result) => router.push(`/sales/opportunities/${result.opportunity_id}`),
              onError,
            })
          }
        >
          Załóż szansę
        </Button>
        {lead.status === "new" && (
          <Button
            size="sm"
            variant="outline"
            loading={update.isPending && !rejecting}
            onClick={() =>
              update.mutate(
                { id: lead.id, status: "contacted" },
                { onSuccess: () => showSuccess("Oznaczono: w kontakcie."), onError },
              )
            }
          >
            W kontakcie
          </Button>
        )}
        <Button size="sm" variant="quiet" aria-expanded={rejecting} onClick={() => setRejecting((value) => !value)}>
          Odrzuć
        </Button>
      </div>
      {rejecting && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-foreground">Dlaczego odrzucasz?</p>
          <div className="flex flex-wrap gap-1">
            {reasons.map((reason) => (
              <Button
                key={reason}
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs"
                disabled={update.isPending}
                onClick={() =>
                  update.mutate(
                    { id: lead.id, status: "dismissed", dismissed_reason: reason },
                    {
                      onSuccess: () => {
                        setRejecting(false);
                        showSuccess("Odrzucono. Powód trafi do bota przy następnym biegu.");
                      },
                      onError,
                    },
                  )
                }
              >
                {reason}
              </Button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
