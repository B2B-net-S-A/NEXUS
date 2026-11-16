"use client";

import { useRef, useState } from "react";
import { Send } from "lucide-react";

import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { sendIssued, useInvalidateIssued } from "@/lib/api/issued-invoices";
import { countPl } from "@/lib/plural-pl";

export interface BatchOutcome {
  accepted: number;
  inFlight: number;
  problems: { id: number; label: string; reason: string }[];
  stopped: boolean;
}

/**
 * Wysyłka seryjna (E6): zaznaczone szkice idą do KSeF po kolei tą samą trasą co
 * przycisk na karcie (`POST /{id}/send`) — numer z serii, plik, wynik, UPO.
 * Zatrzymanie albo zamknięcie karty zostawia resztę jako szkice (bez numeru);
 * faktura z wynikiem nieznanym zostaje „w drodze” do „Sprawdź status”.
 */
export function BatchSendBar({
  ids,
  labels,
  disabledReason,
  onDone,
}: {
  ids: number[];
  labels: Record<number, string>;
  disabledReason: string | null;
  onDone: () => void;
}) {
  const { askConfirm, confirmDialog } = useConfirmV2();
  const invalidate = useInvalidateIssued();
  const stop = useRef(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [outcome, setOutcome] = useState<BatchOutcome | null>(null);

  const run = async () => {
    const ok = await askConfirm({
      title: `Wysłać ${countPl(ids.length, "fakturę", "faktury", "faktur")} do KSeF?`,
      description:
        "Każda dostanie kolejny numer z serii i trafi do KSeF po kolei. Nie zamykaj karty do końca — zatrzymanie zostawi resztę jako szkice.",
      confirmLabel: "Wyślij do KSeF",
    });
    if (!ok) return;
    stop.current = false;
    setOutcome(null);
    const result: BatchOutcome = { accepted: 0, inFlight: 0, problems: [], stopped: false };
    setProgress({ done: 0, total: ids.length });
    for (const [index, id] of ids.entries()) {
      if (stop.current) {
        result.stopped = true;
        break;
      }
      try {
        const card = await sendIssued(id);
        if (card.status === "accepted") result.accepted += 1;
        else if (card.status === "sending" || card.status === "sent") result.inFlight += 1;
        else
          result.problems.push({
            id,
            label: card.invoice_number ?? labels[id] ?? `#${id}`,
            reason: card.ksef_status_text ?? card.status_label,
          });
      } catch (err) {
        result.problems.push({
          id,
          label: labels[id] ?? `#${id}`,
          reason: apiErrorMessage(err, "Nie udało się wysłać."),
        });
      }
      setProgress({ done: index + 1, total: ids.length });
    }
    setProgress(null);
    setOutcome(result);
    invalidate();
    onDone();
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2">
        <p className="text-sm text-muted-foreground">
          {progress
            ? `Wysyłanie… wysłano ${progress.done} z ${progress.total}`
            : ids.length
              ? `Zaznaczone: ${countPl(ids.length, "faktura", "faktury", "faktur")}.`
              : "Zaznacz szkice, które mają pójść do KSeF razem."}
        </p>
        {progress ? (
          <Button size="sm" variant="outline" onClick={() => (stop.current = true)}>
            Zatrzymaj
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={run}
            disabled={ids.length === 0 || disabledReason !== null}
            title={disabledReason ?? undefined}
          >
            <Send className="h-4 w-4" aria-hidden />
            {`Wyślij zaznaczone do KSeF${ids.length ? ` (${ids.length})` : ""}`}
          </Button>
        )}
      </div>
      {outcome ? (
        <div role="status" className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm">
          <p className="text-foreground">
            Przyjęte w KSeF: {outcome.accepted}
            {outcome.inFlight ? ` · w drodze (sprawdź status): ${outcome.inFlight}` : ""}
            {outcome.problems.length ? ` · do poprawy: ${outcome.problems.length}` : ""}
            {outcome.stopped ? " · zatrzymane — reszta została w szkicach" : ""}
          </p>
          {outcome.problems.length ? (
            <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
              {outcome.problems.slice(0, 10).map((problem) => (
                <li key={problem.id}>
                  <a href={`/finance/faktury/${problem.id}`} className="text-primary hover:underline">
                    {problem.label}
                  </a>
                  : {problem.reason}
                </li>
              ))}
              {outcome.problems.length > 10 ? <li>… i {outcome.problems.length - 10} więcej</li> : null}
            </ul>
          ) : null}
        </div>
      ) : null}
      {confirmDialog}
    </div>
  );
}
