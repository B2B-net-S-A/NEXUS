"use client";

import { useState } from "react";
import { Download } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadHrFile } from "@/lib/api/hr";
import {
  paymentPaths,
  useCancelBatch,
  useConfirmBatch,
  useCreateBatch,
  usePreviewBatch,
  type BatchItem,
  type BatchSummary,
} from "@/lib/api/hr-payments";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";

import { batchStatus } from "./payments-format";

async function downloadBatch(key: string, format: "elixir" | "csv") {
  await downloadHrFile(
    paymentPaths.batchFile(key),
    `przelewy-${key.slice(0, 8)}.${format === "csv" ? "csv" : "pli"}`,
  );
}

function BatchItems({ items }: { items: BatchItem[] }) {
  const included = items.filter((item) => item.included);
  const held = items.filter((item) => !item.included);
  return (
    <div className="space-y-3 text-sm">
      <div>
        <p className="font-medium text-foreground">W paczce: {included.length}</p>
        <ul className="mt-1 space-y-0.5">
          {included.map((item) => (
            <li key={item.settlement_id} className="flex justify-between gap-3">
              <span>
                {item.name} · {item.title}
              </span>
              <span className="tabular-nums">
                {formatMoney(item.amount, item.currency)} · •• {item.account_last4}
              </span>
            </li>
          ))}
        </ul>
      </div>
      {held.length > 0 ? (
        <div>
          <p className="font-medium text-foreground">Poza paczką: {held.length}</p>
          <ul className="mt-1 space-y-0.5 text-muted-foreground">
            {held.map((item) => (
              <li key={item.settlement_id}>
                {item.name} · {item.period} — {item.reason_label}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Paczka przelewów (opcja z Ustawień → Płace): faktury B2B z rachunkiem
 * sprawdzonym w wykazie VAT w dniu paczki. Rachunek spoza listy albo brak
 * odpowiedzi wykazu wstrzymuje pozycję do decyzji Finansów.
 */
export function TransferBatchPanel({
  batches,
  format,
}: {
  batches: BatchSummary[];
  format: "elixir" | "csv";
}) {
  const preview = usePreviewBatch();
  const create = useCreateBatch();
  const confirm = useConfirmBatch();
  const cancel = useCancelBatch();
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [open, setOpen] = useState(false);

  const start = () => {
    setOpen(true);
    preview.mutate(null, {
      onError: (err) =>
        showToast(apiErrorMessage(err, "Nie udało się przygotować paczki."), "error"),
    });
  };

  const createAndDownload = () =>
    create.mutate(
      { settlement_ids: null, execution_date: null },
      {
        onSuccess: async (data) => {
          setOpen(false);
          showToast(`Paczka: ${data.count} przelewów`, "success");
          try {
            await downloadBatch(data.batch_key, data.format);
          } catch (err) {
            showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error");
          }
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się utworzyć paczki."), "error"),
      },
    );

  const markPaid = async (batch: BatchSummary) => {
    const ok = await askConfirm({
      title: "Bank wykonał przelewy z paczki?",
      description: `${batch.active} przelewów na ${formatMoney(batch.total, "PLN")}. Rozliczenia zostaną oznaczone jako opłacone z dzisiejszą datą — osoby zobaczą to u siebie.`,
      confirmLabel: "Oznacz jako opłacone",
      cancelLabel: "Wróć",
    });
    if (!ok) return;
    confirm.mutate(
      { key: batch.batch_key, paidOn: null },
      {
        onSuccess: (data) => showToast(`Opłacono: ${data.paid}`, "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się oznaczyć."), "error"),
      },
    );
  };

  const cancelBatch = async (batch: BatchSummary) => {
    const ok = await askConfirm({
      title: "Anulować paczkę przelewów?",
      description:
        "Rozliczenia wrócą na listę do zapłaty. Jeśli plik był już wgrany do banku, anuluj przelewy także tam.",
      confirmLabel: "Anuluj paczkę",
      cancelLabel: "Zostaw",
      variant: "destructive",
    });
    if (!ok) return;
    cancel.mutate(batch.batch_key, {
      onSuccess: () => showToast("Paczka anulowana", "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się anulować."), "error"),
    });
  };

  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
          Paczki przelewów ({format === "csv" ? "CSV" : "Elixir-O"})
        </h2>
        <Button size="sm" variant="secondary" onClick={start} disabled={preview.isPending}>
          <Download className="h-4 w-4" aria-hidden />
          Pobierz paczkę do banku
        </Button>
      </div>
      {batches.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nie utworzono jeszcze żadnej paczki.</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card text-sm">
          {batches.map((batch) => {
            const status = batchStatus(batch);
            return (
              <li
                key={batch.batch_key}
                className="flex flex-wrap items-center justify-between gap-2 px-3 py-2"
              >
                <span>
                  {formatIsoDatePl(batch.execution_date)} · {batch.active} przelewów ·{" "}
                  {formatMoney(batch.total, "PLN")}
                  {batch.created_by_name ? ` · ${batch.created_by_name}` : ""}
                </span>
                <span className="flex items-center gap-2">
                  <StatusDot tone={status.tone}>{status.text}</StatusDot>
                  {batch.status === "created" ? (
                    <>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          downloadBatch(batch.batch_key, batch.format).catch((err) =>
                            showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error"),
                          )
                        }
                      >
                        Pobierz plik
                      </Button>
                      <Button size="sm" onClick={() => markPaid(batch)} disabled={confirm.isPending}>
                        Bank wykonał
                      </Button>
                      <Button size="sm" variant="quiet" onClick={() => cancelBatch(batch)}>
                        Anuluj
                      </Button>
                    </>
                  ) : null}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {open ? (
        <AppModal
          open={open}
          onOpenChange={setOpen}
          size="lg"
          title="Paczka przelewów do banku"
          description="Rachunki sprawdzamy w wykazie VAT w dniu paczki; identyfikator sprawdzenia zostaje w śladzie zmian."
          footer={
            <>
              <Button variant="ghost" onClick={() => setOpen(false)}>
                Wróć
              </Button>
              <Button
                onClick={createAndDownload}
                disabled={
                  create.isPending ||
                  !preview.data ||
                  !preview.data.items.some((item) => item.included)
                }
              >
                {create.isPending ? "Tworzenie…" : "Utwórz paczkę i pobierz plik"}
              </Button>
            </>
          }
        >
          {preview.isPending ? (
            <p className="text-sm text-muted-foreground">Sprawdzanie rachunków…</p>
          ) : preview.data ? (
            <BatchItems items={preview.data.items} />
          ) : (
            <p className="text-sm text-muted-foreground">
              Nie udało się przygotować paczki — spróbuj ponownie.
            </p>
          )}
        </AppModal>
      ) : null}
      {confirmDialog}
    </section>
  );
}
