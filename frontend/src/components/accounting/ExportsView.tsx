"use client";

import Link from "next/link";
import { useState } from "react";

import { QueryStateNotice, StatusDot, type StatusDotTone } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  exportFilePath,
  useChangeExport,
  useCreateExport,
  useExports,
  type ExportDocument,
  type ExportKind,
  type ExportsOverview,
  type LedgerExportItem,
} from "@/lib/api/accounting";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard, useAccounting } from "./AccountingShell";
import { datePl, findPeriod, gr, monthTitle } from "./ledger-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const DOCS_SHOWN = 12;
const STATUS_TONE: Record<LedgerExportItem["status"], StatusDotTone> = {
  exported: "warning",
  booked: "success",
  cancelled: "neutral",
};

/** Rodzaje zaznaczone na start: domyślne — reszta idzie do Symfonii inną drogą. */
export function defaultKinds(data: ExportsOverview): Set<ExportKind> {
  return new Set(data.kinds.filter((kind) => kind.default).map((kind) => kind.key));
}

/** Dokumenty, które wejdą do paczki: zaznaczone rodzaje, zwykłe albo płacowe (D2). */
export function packedDocuments(
  documents: ExportDocument[],
  kinds: Set<ExportKind>,
  payroll: boolean,
): ExportDocument[] {
  return documents.filter((doc) => kinds.has(doc.kind) && doc.payroll === payroll);
}

export function ExportsView() {
  const { config, period } = useAccounting();
  const { year } = findPeriod(config, period);
  const exports = useExports(period.year, period.month, year != null);

  if (!year) {
    return (
      <div className="rounded-lg border border-dashed border-border px-6 py-10 text-center">
        <p className="text-sm font-medium">Nie ma roku obrotowego {period.year}</p>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
          Paczki powstają z dokumentów założonego roku. Rok zakłada osoba z listy „Księgowi” w{" "}
          <Link href="/accounting/settings" className="text-primary hover:underline">
            Ustawieniach
          </Link>
          .
        </p>
      </div>
    );
  }
  if (exports.isError) {
    return <QueryStateNotice state="error" onRetry={() => exports.refetch()} />;
  }
  if (!exports.isSuccess) {
    return <p className="text-sm text-muted-foreground">Wczytywanie paczek…</p>;
  }
  const data = exports.data;
  return (
    <div className="space-y-3.5">
      <p className="rounded-md border border-border bg-muted/40 px-3.5 py-2 text-[13px] text-muted-foreground">
        {data.exportable
          ? "Paczka zbiera zatwierdzone dokumenty miesiąca w pliku do importu w Symfonii FK — każdy dokument trafia do niej raz."
          : data.refusal}
      </p>
      {data.exportable ? <NewExportCard key={`${period.year}-${period.month}`} data={data} /> : null}
      <ExportsCard items={data.exports} title={monthTitle(period.year, period.month)} />
    </div>
  );
}

function NewExportCard({ data }: { data: ExportsOverview }) {
  const { config, period } = useAccounting();
  const { showToast } = useToast();
  const create = useCreateExport();
  const [kinds, setKinds] = useState<Set<ExportKind>>(() => defaultKinds(data));
  const [payroll, setPayroll] = useState(false);
  const [format, setFormat] = useState(data.default_format);
  const [all, setAll] = useState(false);
  const approver = config.me.approver;
  const payrollTotal = data.kinds.reduce((sum, kind) => sum + kind.payroll_count, 0);
  // Tryb płacowy tylko, gdy są dokumenty płacowe: paczka płacowa, która zabrała
  // ostatnie, chowa przełącznik — ekran wraca do zwykłej paczki zamiast pokazywać
  // fałszywą pustkę (przegląd K3b 14.11.2026).
  const payrollMode = payroll && payrollTotal > 0;
  const docs = packedDocuments(data.documents, kinds, payrollMode);
  const shown = all ? docs : docs.slice(0, DOCS_SHOWN);
  const total = docs.reduce((sum, doc) => sum + doc.debit_total, 0);
  const title = monthTitle(period.year, period.month);

  const toggle = (kind: ExportKind) =>
    setKinds((current) => {
      const next = new Set(current);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });

  const run = () =>
    create.mutate(
      {
        year: period.year,
        month: period.month,
        kinds: data.kinds.map((kind) => kind.key).filter((key) => kinds.has(key)),
        file_format: format,
        payroll: payrollMode,
      },
      {
        onSuccess: async (item) => {
          showToast(`Paczka ${item.number}: ${item.document_count} dokumentów. Pobieram plik.`);
          try {
            await downloadAuthenticatedFile(exportFilePath(item.id), item.file_name);
          } catch (error) {
            showToast(apiErrorMessage(error, "Paczka powstała, ale pliku nie udało się pobrać — pobierz go z listy paczek."), "error");
          }
        },
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zrobić paczki."), "error"),
      },
    );

  return (
    <SectionCard title="Nowa paczka do Symfonii" aside={title}>
      <div className="grid gap-0 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="space-y-3 px-3.5 py-3 xl:border-r xl:border-border/70">
          {approver ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                disabled={docs.length === 0}
                title={docs.length === 0 ? "Nie ma zatwierdzonych dokumentów w zaznaczonych rodzajach" : undefined}
                loading={create.isPending}
                onClick={run}
              >
                Pobierz paczkę ({docs.length})
              </Button>
              <select
                aria-label="Format pliku"
                className={CONTROL}
                value={format}
                onChange={(event) => setFormat(event.target.value)}
              >
                {data.formats.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <p className="text-[12px] leading-5 text-muted-foreground">
              Paczkę robi osoba z listy „Księgowi” albo administrator — tu widać, co do niej wejdzie.
            </p>
          )}
          {data.drafts ? (
            <p className="text-[12px] leading-5 text-warning-muted-foreground">
              W buforze tego miesiąca {data.drafts === 1 ? "jest 1 dokument" : `są dokumenty (${data.drafts})`} — do
              paczki wchodzą tylko zatwierdzone.{" "}
              <Link
                href={`/accounting/documents?year=${period.year}&month=${period.month}&status=draft`}
                className="text-primary hover:underline"
              >
                Bufor
              </Link>
            </p>
          ) : null}
          {config.me.payroll && payrollTotal ? (
            <label className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-[13px]">
              <span>
                Paczka płacowa
                <span className={CALM_SUBLINE}>
                  Dokumenty płacowe ({payrollTotal}) idą osobną paczką — widzą ją tylko Płace i administrator.
                </span>
              </span>
              <Switch checked={payrollMode} onCheckedChange={setPayroll} aria-label="Paczka płacowa" />
            </label>
          ) : null}
          <ul className="space-y-1.5">
            {data.kinds.map((kind) => {
              const count = payrollMode ? kind.payroll_count : kind.count;
              const amount = payrollMode ? kind.payroll_debit_total : kind.debit_total;
              return (
                <li key={kind.key} className="flex items-start gap-2.5">
                  <Checkbox
                    id={`export-kind-${kind.key}`}
                    checked={kinds.has(kind.key)}
                    onCheckedChange={() => toggle(kind.key)}
                    className="mt-0.5"
                  />
                  <label htmlFor={`export-kind-${kind.key}`} className="min-w-0 flex-1 text-[13px]">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="font-medium">{kind.label}</span>
                      <span className="shrink-0 tabular-nums text-muted-foreground">
                        {count ? `${count} · ${gr(amount)} zł` : "—"}
                      </span>
                    </span>
                    {kind.note ? <span className={CALM_SUBLINE}>{kind.note}</span> : null}
                  </label>
                </li>
              );
            })}
          </ul>
          <p className="text-[12px] leading-5 text-muted-foreground">
            Format neutralny (wiersz na pozycję dekretu, jak paczka E2) — format importu Symfonii dopiszemy po
            próbce pliku od Finansów.
          </p>
        </div>
        <div className="min-w-0 border-t border-border/70 xl:border-t-0">
          {docs.length ? (
            <>
              <table className="w-full table-fixed text-sm">
                <thead>
                  <tr className="border-b border-border/70">
                    <th className={cn(CALM_HEAD, "w-[15%] px-3.5 py-2 text-left")}>Dziennik</th>
                    <th className={cn(CALM_HEAD, "px-2 py-2 text-left")}>Dokument</th>
                    <th className={cn(CALM_HEAD, "w-[16%] px-2 py-2 text-left")}>Data</th>
                    <th className={cn(CALM_HEAD, "w-[21%] px-3.5 py-2 text-right")}>Kwota, zł</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((doc) => (
                    <tr key={doc.id} className={cn(CALM_ROW, "last:border-0")}>
                      <td className="whitespace-nowrap px-3.5 py-1.5 tabular-nums text-muted-foreground">{doc.journal_no}</td>
                      <td className="min-w-0 px-2 py-1.5">
                        <span className="block truncate font-medium" title={doc.number}>
                          {doc.number}
                        </span>
                        <span className={cn(CALM_SUBLINE, "truncate")} title={doc.description}>
                          {doc.doc_type} · {doc.description || "bez opisu"}
                        </span>
                      </td>
                      <td className="px-2 py-1.5 tabular-nums">{datePl(doc.op_date)}</td>
                      <td className={cn(CALM_AMOUNT, "px-3.5 py-1.5")}>{gr(doc.debit_total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex items-center justify-between gap-3 border-t border-border/70 px-3.5 py-2 text-[12px] text-muted-foreground">
                <span>
                  W paczce: {docs.length} dokumentów, Wn {gr(total)} zł
                </span>
                {docs.length > DOCS_SHOWN ? (
                  <button type="button" className="text-primary hover:underline" onClick={() => setAll((value) => !value)}>
                    {all ? "Pokaż mniej" : `Pokaż wszystkie (${docs.length})`}
                  </button>
                ) : null}
              </div>
            </>
          ) : (
            <p className="px-3.5 py-6 text-center text-[13px] text-muted-foreground">
              {data.documents.length
                ? "W zaznaczonych rodzajach nie ma dokumentów spoza paczek."
                : "W tym miesiącu nie ma zatwierdzonych dokumentów spoza paczek."}
            </p>
          )}
        </div>
      </div>
    </SectionCard>
  );
}

function ExportsCard({ items, title }: { items: LedgerExportItem[]; title: string }) {
  const { config } = useAccounting();
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const change = useChangeExport();
  const approver = config.me.approver;

  const download = async (item: LedgerExportItem) => {
    try {
      await downloadAuthenticatedFile(exportFilePath(item.id), item.file_name);
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się pobrać pliku paczki."), "error");
    }
  };

  const book = async (item: LedgerExportItem) => {
    const ok = await askConfirm({
      title: `Paczka ${item.number} zaksięgowana w Symfonii?`,
      description: "Paczka zostanie zamknięta — anulować się jej już nie da. Poprawka dokumentu to storno w NEXUSIE, które pójdzie następną paczką.",
      confirmLabel: "Zaksięgowana",
    });
    if (!ok) return;
    change.mutate(
      { id: item.id, action: "book" },
      {
        onSuccess: () => showToast(`Paczka ${item.number} oznaczona jako zaksięgowana w Symfonii.`),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się oznaczyć paczki."), "error"),
      },
    );
  };

  const cancel = async (item: LedgerExportItem) => {
    const ok = await askConfirm({
      title: `Anulować paczkę ${item.number}?`,
      description: "Jej dokumenty wrócą do następnej paczki. Jeśli plik był już importowany w Symfonii, usuń tam ten import.",
      confirmLabel: "Anuluj paczkę",
      variant: "destructive",
    });
    if (!ok) return;
    change.mutate(
      { id: item.id, action: "cancel" },
      {
        onSuccess: () => showToast(`Paczka ${item.number} anulowana — dokumenty wróciły do miesiąca.`),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się anulować paczki."), "error"),
      },
    );
  };

  return (
    <SectionCard title="Paczki miesiąca" aside={title}>
      {items.length ? (
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-border/70">
              <th className={cn(CALM_HEAD, "w-[15%] px-3.5 py-2 text-left")}>Paczka</th>
              <th className={cn(CALM_HEAD, "w-[24%] px-2 py-2 text-left")}>Stan</th>
              <th className={cn(CALM_HEAD, "px-2 py-2 text-left")}>Rodzaje</th>
              <th className={cn(CALM_HEAD, "w-[15%] px-2 py-2 text-right")}>Wn, zł</th>
              <th className={cn(CALM_HEAD, "w-[230px] px-3.5 py-2")} />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} className={cn(CALM_ROW, "align-top last:border-0")}>
                <td className="px-3.5 py-2">
                  <span className="font-medium">{item.number}</span>
                  <span className={CALM_SUBLINE}>
                    {item.document_count} dok.{item.has_payroll ? " · płacowa" : ""}
                  </span>
                </td>
                <td className="px-2 py-2">
                  <StatusDot tone={STATUS_TONE[item.status]}>
                    <span className="text-[13px]">{item.status_label}</span>
                  </StatusDot>
                  <span className={CALM_SUBLINE}>{statusLine(item)}</span>
                </td>
                <td className="min-w-0 px-2 py-2 text-[13px]">
                  <span className="block truncate" title={item.kind_labels.join(", ")}>
                    {item.kind_labels.join(", ")}
                  </span>
                  <span className={CALM_SUBLINE}>{item.file_format_label}</span>
                </td>
                <td className={cn(CALM_AMOUNT, "px-2 py-2")}>{gr(item.debit_total)}</td>
                <td className="px-3.5 py-2">
                  <div className="flex flex-wrap justify-end gap-1.5">
                    <Button size="sm" variant="outline" onClick={() => download(item)}>
                      Pobierz
                    </Button>
                    {approver && item.status === "exported" ? (
                      <>
                        <Button size="sm" variant="outline" disabled={change.isPending} onClick={() => book(item)}>
                          Zaksięgowana
                        </Button>
                        <Button size="sm" variant="ghost" disabled={change.isPending} onClick={() => cancel(item)}>
                          Anuluj
                        </Button>
                      </>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="px-3.5 py-4 text-[13px] text-muted-foreground">Za ten miesiąc nie ma jeszcze paczek.</p>
      )}
      {confirmDialog}
    </SectionCard>
  );
}

function statusLine(item: LedgerExportItem): string {
  if (item.status === "booked") return `${item.booked_by ?? "—"}, ${datePl(item.booked_at)}`;
  if (item.status === "cancelled") return `${item.cancelled_by ?? "—"}, ${datePl(item.cancelled_at)}`;
  return `${item.created_by ?? "—"}, ${datePl(item.created_at)}`;
}
