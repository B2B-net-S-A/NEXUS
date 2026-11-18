"use client";

/**
 * „Proces u klienta” na `/jobs/new` (18.11.2026), w sekcji „Warunki”.
 * Opcjonalne. Pole nie wypełnia się samo po wyborze klienta (pusta strona
 * nie może zapisać formularza), tylko podpowiada etapy z poprzedniej
 * rekrutacji klienta: „Użyj”. Po utworzeniu edytuje się je z nagłówka.
 */

import { Button } from "@/components/ui/button";
import { ClientProcessEditor } from "@/components/v2/jobs/ClientProcessEditor";
import {
  EMPTY_PROCESS,
  STEP_LABEL,
  type ClientProcessInput,
} from "@/lib/job-client-process";
import { useClientProcessHints } from "@/lib/job-client-process-api";

interface NewJobClientProcessFieldProps {
  clientId: number | null;
  value: ClientProcessInput | null;
  onChange: (next: ClientProcessInput | null) => void;
}

export function NewJobClientProcessField({ clientId, value, onChange }: NewJobClientProcessFieldProps) {
  const hints = useClientProcessHints(clientId);
  const suggested = hints.data?.suggested ?? null;
  const measured = hints.data?.measured ?? null;

  return (
    <div className="flex flex-col gap-2 border-t border-border pt-4" data-testid="new-job-client-process">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium">
          Proces u klienta po wysłaniu CV{" "}
          <span className="font-normal text-muted-foreground">· opcjonalnie</span>
        </p>
        {measured ? (
          <p className="text-xs text-muted-foreground">
            U tego klienta od CV do decyzji zwykle ~{measured.cv_to_decision_days} dni (mediana z{" "}
            {measured.decisions})
          </p>
        ) : null}
      </div>

      {value ? (
        <>
          <ClientProcessEditor value={value} onChange={onChange} idPrefix="new-job-process" />
          <Button
            type="button"
            size="sm"
            variant="quiet"
            className="self-start"
            onClick={() => onChange(null)}
          >
            Usuń proces
          </Button>
        </>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {suggested ? (
            <div className="flex items-center gap-2 rounded-md bg-muted/60 px-3 py-1.5">
              <span className="text-xs">
                Poprzednia rekrutacja tego klienta:{" "}
                <b>{suggested.steps.map((s) => STEP_LABEL[s.kind]).join(" + ")}</b>
              </span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() =>
                  onChange({
                    steps: suggested.steps.map((s) => ({ ...s })),
                    decision_workdays: suggested.decision_workdays,
                  })
                }
              >
                Użyj
              </Button>
            </div>
          ) : null}
          <Button type="button" size="sm" variant="ghost" onClick={() => onChange(EMPTY_PROCESS)}>
            Wpisz etapy
          </Button>
        </div>
      )}
    </div>
  );
}
