"use client";

import Link from "next/link";
import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadBatchFile,
  useBatchAction,
  useBatchCreate,
  useExportPreview,
  type PostingBatch,
} from "@/lib/api/finance-posting";
import { formatIsoDatePl, formatMomentPl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

import { formatGrosze, previousMonth, toGrosze } from "./posting-model";

const CONTROL =
  "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const LABEL = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

function Amount({ value }: { value: string }) {
  return <span className="tabular-nums">{formatGrosze(toGrosze(value) ?? 0)}</span>;
}

function BatchRow({ batch, canWrite }: { batch: PostingBatch; canWrite: boolean }) {
  const action = useBatchAction();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showToast } = useToast();
  const [downloading, setDownloading] = useState(false);
  const run = async (kind: "book" | "cancel") => {
    const ok = await askConfirm(
      kind === "book"
        ? {
            title: `Oznaczyć paczkę ${batch.number} jako zaksięgowaną?`,
            description: `${countPl(batch.entry_count, "faktura przejdzie", "faktury przejdą", "faktur przejdzie")} do „Zaksięgowane”. Potem ich etapu i dekretu nie zmienisz. Zrób to po imporcie pliku do Symfonii FK.`,
            confirmLabel: "Oznacz jako zaksięgowane",
          }
        : {
            title: `Anulować paczkę ${batch.number}?`,
            description: "Faktury wrócą na listę miesiąca jako „Gotowe do księgowania”. Plik tej paczki nie powinien trafić do Symfonii.",
            confirmLabel: "Anuluj paczkę",
            variant: "destructive",
          },
    );
    if (!ok) return;
    action.mutate(
      { id: batch.id, action: kind },
      {
        onSuccess: () =>
          showToast(kind === "book" ? "Paczka zaksięgowana." : "Paczka anulowana.", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zmienić paczki."), "error"),
      },
    );
  };
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border py-2 text-sm first:border-t-0">
      <span className="font-mono text-[12.5px]">{batch.number}</span>
      <Badge
        size="sm"
        variant={batch.status === "booked" ? "success" : batch.status === "cancelled" ? "neutral" : "warning"}
      >
        {batch.status_label}
      </Badge>
      <span className="text-muted-foreground">
        {countPl(batch.entry_count, "faktura", "faktury", "faktur")} · Wn <Amount value={batch.debit_total} /> · Ma{" "}
        <Amount value={batch.credit_total} />
      </span>
      <span className="text-xs text-muted-foreground">
        {batch.created_at ? formatMomentPl(batch.created_at) : ""} · {batch.created_by ?? "—"}
        {batch.booked_at ? ` · zaksięgowano ${formatMomentPl(batch.booked_at)} · ${batch.booked_by ?? "—"}` : ""}
      </span>
      <span className="font-mono text-[11px] text-muted-foreground" title="SHA-256 pliku">
        {batch.file_sha256.slice(0, 12)}…
      </span>
      <span className="ml-auto flex gap-1.5">
        <Button
          size="sm"
          variant="outline"
          loading={downloading}
          onClick={async () => {
            setDownloading(true);
            try {
              await downloadBatchFile(batch);
            } catch (err) {
              showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error");
            } finally {
              setDownloading(false);
            }
          }}
        >
          Pobierz ponownie
        </Button>
        {canWrite && batch.status === "exported" ? (
          <>
            <Button size="sm" variant="ghost" disabled={action.isPending} onClick={() => void run("cancel")}>
              Anuluj paczkę
            </Button>
            <Button size="sm" loading={action.isPending} onClick={() => void run("book")}>
              Oznacz jako zaksięgowane
            </Button>
          </>
        ) : null}
      </span>
      {confirmDialog}
    </li>
  );
}

/** Finanse → „Księgowanie”: eksport miesiąca do Symfonii FK (makieta M3). */
export function BookingTab({ canWrite = true }: { canWrite?: boolean }) {
  const [month, setMonth] = useState(() => previousMonth(warsawToday()));
  const [format, setFormat] = useState<string | null>(null);
  const preview = useExportPreview(month);
  const create = useBatchCreate();
  const { showToast } = useToast();
  const data = preview.data;
  const chosenFormat = format ?? data?.default_format ?? "neutral_xlsx";

  const exportMonth = () =>
    create.mutate(
      { month, format: chosenFormat },
      {
        onSuccess: async (batch) => {
          showToast(`Paczka ${batch.number} gotowa — pobieram plik.`, "success");
          try {
            await downloadBatchFile(batch);
          } catch (err) {
            showToast(apiErrorMessage(err, "Paczka jest, ale pliku nie udało się pobrać."), "error");
          }
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się przygotować paczki."), "error"),
      },
    );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-sm text-muted-foreground" htmlFor="booking-month">
          Miesiąc wpływu
        </label>
        <input
          id="booking-month"
          type="month"
          value={month}
          onChange={(event) => event.target.value && setMonth(event.target.value)}
          className={CONTROL}
        />
        {data ? (
          <span className="text-xs text-muted-foreground">
            {countPl(data.count, "faktura gotowa", "faktury gotowe", "faktur gotowych")} do księgowania
            {data.blocked > 0 ? ` · z wadą: ${data.blocked}` : ""}
          </span>
        ) : null}
        <div className={cn("ml-auto flex flex-wrap items-center gap-2", !canWrite && "hidden")}>
          <select
            aria-label="Format pliku"
            value={chosenFormat}
            onChange={(event) => setFormat(event.target.value)}
            className={CONTROL}
          >
            {(data?.formats ?? []).map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
          <Button size="sm" disabled={!data?.can_export} loading={create.isPending} onClick={exportMonth}>
            Pobierz plik
          </Button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Format importu Symfonii FK czeka na próbkę od Finansów — plik ma wiersz na pozycję dekretu. „Pobierz plik”
        zakłada paczkę z numerem; po imporcie w Symfonii oznacz ją jako zaksięgowaną.
      </p>

      {preview.isLoading ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie miesiąca…</p>
      ) : preview.isError ? (
        <QueryStateNotice state="error" onRetry={() => preview.refetch()} />
      ) : preview.isSuccess && data && data.registers.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          Za ten miesiąc nie ma faktur „Gotowych do księgowania” spoza paczek.
        </div>
      ) : (
        (data?.registers ?? []).map((register) => (
          <section
            key={register.register}
            aria-label={`Rejestr ${register.label}`}
            className="rounded-lg border border-border bg-card"
          >
            <header className="flex flex-wrap items-center gap-3 border-b border-border px-3.5 py-2">
              <h2 className={LABEL}>Rejestr: {register.label}</h2>
              <span className="text-sm text-muted-foreground">
                Wn <Amount value={register.debit_total} /> · Ma <Amount value={register.credit_total} />
              </span>
              <Badge size="sm" variant={register.balanced ? "success" : "danger"}>
                {register.balanced ? "bilans zgodny" : "bilans niezgodny"}
              </Badge>
            </header>
            <ul>
              {register.entries.map((entry) => (
                <li key={entry.id} className="border-t border-border px-3.5 py-2 text-sm first:border-t-0">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                    <Link href={`/finance/costs/${entry.id}`} className="font-medium text-primary hover:underline">
                      {entry.invoice_number ?? `Faktura #${entry.id}`}
                    </Link>
                    <span className="min-w-0 truncate">{entry.seller_name ?? "—"}</span>
                    <span className="text-xs text-muted-foreground">
                      {entry.issue_date ? formatIsoDatePl(entry.issue_date) : ""}
                      {entry.doc_type ? ` · ${entry.doc_type}` : ""}
                      {entry.description ? ` · ${entry.description}` : ""}
                      {entry.manual ? " · dekret ręczny" : ""}
                    </span>
                    <span className="ml-auto text-sm">
                      <Amount value={entry.debit_total} />
                    </span>
                  </div>
                  {entry.issues.length > 0 ? (
                    <p className="mt-0.5 text-xs text-destructive">{entry.issues.join(" ")}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ))
      )}

      {data && data.batches.length > 0 ? (
        <section aria-label="Paczki miesiąca" className="rounded-lg border border-border bg-card px-3.5 py-1">
          <h2 className={cn(LABEL, "pt-2")}>Paczki za {month}</h2>
          <ul>
            {data.batches.map((batch) => (
              <BatchRow key={batch.id} batch={batch} canWrite={canWrite} />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
