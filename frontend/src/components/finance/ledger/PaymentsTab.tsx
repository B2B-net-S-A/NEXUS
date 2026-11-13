"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  batchFilePath,
  useAssignDebit,
  useBatchDetail,
  useBatches,
  useCancelBatch,
  useCreateBatch,
  useIgnoreDebit,
  usePaymentPlan,
  usePaymentSettings,
  useReleaseItem,
  useSavePaymentSettings,
  useStatementOverview,
  useUploadStatement,
  type PlanItem,
} from "@/lib/api/finance-payments";
import { downloadBlob, fetchAuthenticatedDownload } from "@/lib/authenticated-files";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

import {
  batchFormat,
  createBlocker,
  describeStatement,
  formatAccount,
  initialSelection,
  selectionSummary,
} from "./payment-model";

const CONTROL =
  "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const LABEL = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className={LABEL}>{title}</h2>
        {aside ? <div className="ml-auto flex flex-wrap items-center gap-2">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}

function SenderSettings({ canWrite }: { canWrite: boolean }) {
  const settings = usePaymentSettings();
  const save = useSavePaymentSettings();
  const { showToast } = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [account, setAccount] = useState("");
  useEffect(() => {
    setName(settings.data?.sender_name ?? "");
    setAccount(settings.data?.sender_account ?? "");
  }, [settings.data]);
  const configured = Boolean(settings.data?.sender_account);
  return (
    <div className="rounded-lg border border-border bg-card px-3.5 py-2.5 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground">Rachunek nadawcy (plik Elixir):</span>
        {configured ? (
          <span className="font-mono text-xs">
            {settings.data?.sender_name} · {formatAccount(settings.data?.sender_account)}
          </span>
        ) : (
          <span className="text-warning-muted-foreground">nie ustawiony — paczka tylko jako CSV</span>
        )}
        {canWrite ? (
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => setOpen((v) => !v)}>
            {open ? "Zamknij" : configured ? "Zmień" : "Ustaw"}
          </Button>
        ) : null}
      </div>
      {open ? (
        <form
          className="mt-2 flex flex-wrap items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate(
              { sender_name: name, sender_account: account },
              {
                onSuccess: () => {
                  showToast("Rachunek nadawcy zapisany.", "success");
                  setOpen(false);
                },
                onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać."), "error"),
              },
            );
          }}
        >
          <input
            aria-label="Nazwa nadawcy"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Nazwa firmy"
            className={cn(CONTROL, "w-56")}
          />
          <input
            aria-label="Rachunek nadawcy"
            value={account}
            onChange={(event) => setAccount(event.target.value)}
            placeholder="PL00 0000 0000 …"
            className={cn(CONTROL, "w-72 font-mono")}
          />
          <Button size="sm" type="submit" loading={save.isPending}>
            Zapisz
          </Button>
        </form>
      ) : null}
    </div>
  );
}

function WhiteList({ item }: { item: PlanItem }) {
  const state = item.white_list.state;
  const variant =
    state === "listed" ? "success" : state === "not_listed" || state === "unchecked" ? "danger" : "neutral";
  return (
    <span className="block min-w-0">
      <Badge
        size="sm"
        variant={item.white_list.informational ? "neutral" : variant}
        title={item.white_list.request_id ?? undefined}
      >
        {item.white_list.label}
        {item.white_list.informational ? " (informacyjnie — faktor)" : ""}
      </Badge>
      {item.white_list.request_id ? (
        <span className={cn(CALM_SUBLINE, "truncate font-mono")}>{item.white_list.request_id}</span>
      ) : null}
    </span>
  );
}

function PlanTable({
  items,
  selected,
  acknowledged,
  canWrite,
  onSelect,
  onAcknowledge,
}: {
  items: PlanItem[];
  selected: Set<number>;
  acknowledged: Set<number>;
  canWrite: boolean;
  onSelect: (id: number, on: boolean) => void;
  onAcknowledge: (id: number, on: boolean) => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <Table density="compact" className="table-fixed">
        <TableHeader>
          <TableRow>
            <TableHead className="w-9" />
            <TableHead className={`${CALM_HEAD} w-[8%]`}>Termin</TableHead>
            <TableHead className={`${CALM_HEAD} w-[18%]`}>Sprzedawca</TableHead>
            <TableHead className={`${CALM_HEAD} w-[14%]`}>Numer</TableHead>
            <TableHead className={`${CALM_HEAD} w-[11%] text-right`}>Do zapłaty</TableHead>
            <TableHead className={`${CALM_HEAD} w-[8%]`}>Tryb</TableHead>
            <TableHead className={`${CALM_HEAD} w-[15%]`}>Rachunek</TableHead>
            <TableHead className={`${CALM_HEAD} w-[11%]`}>Biała lista</TableHead>
            <TableHead className={`${CALM_HEAD} w-[15%]`}>Uwagi</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow
              key={item.entry_id}
              className={cn(CALM_ROW, "align-top", !item.selectable && "text-muted-foreground")}
            >
              <TableCell>
                <Checkbox
                  aria-label={`Zaznacz ${item.invoice_number ?? "fakturę"}`}
                  checked={selected.has(item.entry_id)}
                  disabled={!canWrite || !item.selectable}
                  onCheckedChange={(checked) => onSelect(item.entry_id, checked === true)}
                />
              </TableCell>
              <TableCell className="whitespace-nowrap tabular-nums">
                {item.due_date ? formatIsoDatePl(item.due_date) : <span className={CALM_EMPTY}>—</span>}
              </TableCell>
              <TableCell className="min-w-0">
                <span className="block truncate">{item.seller_name ?? "—"}</span>
                <span className={cn(CALM_SUBLINE, "truncate")}>
                  {item.seller_nip ? `NIP ${item.seller_nip}` : "bez NIP-u"}
                </span>
              </TableCell>
              <TableCell className="min-w-0">
                <Link
                  href={`/finance/costs/${item.entry_id}`}
                  className="block truncate font-medium text-primary hover:underline"
                >
                  {item.invoice_number ?? `Faktura #${item.entry_id}`}
                </Link>
                <span className={cn(CALM_SUBLINE, "truncate")} title={item.title}>
                  {item.title || "—"}
                </span>
              </TableCell>
              <TableCell className={CALM_AMOUNT}>
                {formatMoney(item.to_pay ?? item.gross_amount, item.currency)}
                {item.amount_note ? (
                  <span className={cn(CALM_SUBLINE, "whitespace-normal text-right")}>
                    {item.amount_note}
                  </span>
                ) : null}
              </TableCell>
              <TableCell>
                {item.mode_label ? (
                  <Badge size="sm" variant={item.mode === "standard" ? "outline" : "warning"}>
                    {item.mode_label}
                  </Badge>
                ) : (
                  <span className={CALM_EMPTY}>—</span>
                )}
              </TableCell>
              <TableCell className="min-w-0">
                <span className="block truncate font-mono text-xs" title={formatAccount(item.account)}>
                  {formatAccount(item.account)}
                </span>
                {item.account_source_label ? (
                  <span className={CALM_SUBLINE}>{item.account_source_label}</span>
                ) : null}
                {item.account_note ? (
                  <span className="block text-xs text-warning-muted-foreground">
                    {item.account_note}
                  </span>
                ) : null}
              </TableCell>
              <TableCell className="min-w-0">
                {item.selectable ? <WhiteList item={item} /> : <span className={CALM_EMPTY}>—</span>}
              </TableCell>
              <TableCell className="min-w-0 space-y-1 text-xs">
                {item.block_label ? <span className="block">{item.block_label}</span> : null}
                {item.acks.map((ack) => (
                  <label key={ack.code} className="flex items-start gap-1.5 text-warning-muted-foreground">
                    <Checkbox
                      aria-label={`Sprawdzone: ${ack.label}`}
                      checked={acknowledged.has(item.entry_id)}
                      disabled={!canWrite}
                      onCheckedChange={(checked) => onAcknowledge(item.entry_id, checked === true)}
                    />
                    <span>{ack.label}</span>
                  </label>
                ))}
                {item.hints.map((hint) => (
                  <span key={hint.code} className="block text-muted-foreground">
                    {hint.label}
                  </span>
                ))}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function BatchItems({ batchId, canWrite }: { batchId: number; canWrite: boolean }) {
  const detail = useBatchDetail(batchId);
  const release = useReleaseItem();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showToast } = useToast();
  if (detail.isLoading) return <p className="px-3.5 pb-2 text-xs text-muted-foreground">Wczytywanie…</p>;
  if (detail.isError || !detail.data) {
    return <QueryStateNotice state="error" onRetry={() => detail.refetch()} />;
  }
  return (
    <ul className="space-y-1 px-3.5 pb-2 text-xs">
      {detail.data.items.map((item) => (
        <li key={item.entry_id} className="flex flex-wrap items-center gap-x-2">
          <span className={cn(item.status !== "active" && "text-muted-foreground line-through")}>
            {item.invoice_number ?? `#${item.entry_id}`}
          </span>
          <span className="text-muted-foreground">{item.recipient_name}</span>
          <span className="tabular-nums">{formatMoney(item.amount, item.currency)}</span>
          {item.account_source === "ksef_factor" ? (
            <Badge size="sm" variant="warning">
              faktor
            </Badge>
          ) : null}
          <span className="text-muted-foreground">
            {item.status === "done" ? "zapłacona" : item.status === "released" ? "zdjęta" : ""}
          </span>
          {canWrite && item.status === "active" ? (
            <Button
              size="sm"
              variant="ghost"
              className="ml-auto"
              loading={release.isPending && release.variables?.entryId === item.entry_id}
              onClick={async () => {
                const ok = await askConfirm({
                  title: "Zdjąć fakturę z paczki?",
                  description:
                    "Faktura wróci do „Do zapłaty”. Plik paczki trzeba pobrać ponownie i wymienić w banku.",
                  confirmLabel: "Zdejmij z paczki",
                  variant: "destructive",
                });
                if (!ok) return;
                release.mutate(
                  { batchId, entryId: item.entry_id },
                  {
                    onSuccess: () =>
                      showToast("Faktura zdjęta z paczki — pobierz plik ponownie.", "success"),
                    onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zdjąć faktury."), "error"),
                  },
                );
              }}
            >
              Zdejmij z paczki
            </Button>
          ) : null}
        </li>
      ))}
      {confirmDialog}
    </ul>
  );
}

function Batches({ canWrite }: { canWrite: boolean }) {
  const batches = useBatches();
  const cancel = useCancelBatch();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showToast } = useToast();
  const [open, setOpen] = useState<number | null>(null);
  const items = batches.data?.items ?? [];
  const download = async (id: number, stale: boolean) => {
    try {
      const file = await fetchAuthenticatedDownload(batchFilePath(id));
      downloadBlob(file.blob, file.filename ?? `przelewy-kosztow-${id}`);
      if (stale) {
        showToast(
          "Pobrano NOWY plik paczki (inny skrót) — usuń z banku plik pobrany wcześniej.",
          "info",
        );
      }
      void batches.refetch();
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać pliku paczki."), "error");
    }
  };
  return (
    <Section title="Paczki">
      {batches.isLoading ? (
        <p className="text-sm text-muted-foreground">Wczytywanie paczek…</p>
      ) : batches.isError ? (
        <QueryStateNotice state="error" onRetry={() => batches.refetch()} />
      ) : batches.isSuccess && items.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nie ma jeszcze paczek przelewów.</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card text-sm">
          {items.map((batch) => (
            <li key={batch.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3.5 py-2">
              <span className="font-medium">#{batch.id}</span>
              <span className="tabular-nums">{formatIsoDatePl(batch.execution_date)}</span>
              <span className="text-muted-foreground">
                {batch.count} · {formatMoney(batch.total, batch.currency)} ·{" "}
                {batch.format === "elixir" ? "Elixir-O" : "CSV"}
              </span>
              <Badge
                size="sm"
                variant={batch.status === "done" ? "success" : batch.status === "cancelled" ? "neutral" : "info"}
              >
                {batch.status_label}
              </Badge>
              {batch.created_by_name ? (
                <span className="text-xs text-muted-foreground">{batch.created_by_name}</span>
              ) : null}
              {batch.file_stale ? (
                <Badge size="sm" variant="danger">
                  Plik nieaktualny — pobierz ponownie
                </Badge>
              ) : batch.file_sha256 ? (
                <span className="font-mono text-[11px] text-muted-foreground">
                  plik {batch.file_sha256.slice(0, 8)}
                </span>
              ) : null}
              <span className="ml-auto flex gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  aria-expanded={open === batch.id}
                  onClick={() => setOpen((current) => (current === batch.id ? null : batch.id))}
                >
                  Pozycje
                </Button>
                {batch.status === "active" ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => void download(batch.id, batch.file_stale)}
                  >
                    Pobierz plik
                  </Button>
                ) : null}
                {canWrite && batch.status === "active" ? (
                  <Button
                    size="sm"
                    variant="outline"
                    loading={cancel.isPending && cancel.variables === batch.id}
                    onClick={async () => {
                      const ok = await askConfirm({
                        title: `Anulować paczkę #${batch.id}?`,
                        description:
                          "Faktury, które nie są jeszcze zapłacone, wrócą do „Do zapłaty”. Anuluj tylko paczkę, której bank nie wykonał.",
                        confirmLabel: "Anuluj paczkę",
                        variant: "destructive",
                      });
                      if (!ok) return;
                      cancel.mutate(batch.id, {
                        onSuccess: (result) =>
                          showToast(`Paczka anulowana, zwolnione: ${result.released}.`, "success"),
                        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się anulować."), "error"),
                      });
                    }}
                  >
                    Anuluj
                  </Button>
                ) : null}
              </span>
              {open === batch.id ? (
                <div className="basis-full">
                  <BatchItems batchId={batch.id} canWrite={canWrite} />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {confirmDialog}
    </Section>
  );
}

function Statement({ canWrite }: { canWrite: boolean }) {
  const overview = useStatementOverview();
  const upload = useUploadStatement();
  const assign = useAssignDebit();
  const ignore = useIgnoreDebit();
  const { askReason, confirmDialog } = useConfirmV2();
  const { showToast } = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const lines = overview.data?.unmatched ?? [];
  return (
    <Section
      title="Zapłaty z wyciągu"
      aside={
        canWrite ? (
          <>
            <input
              ref={input}
              type="file"
              accept=".sta,.txt,.xml,.mt940"
              aria-label="Wyciąg MT940 albo CAMT.053"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (!file) return;
                upload.mutate(file, {
                  onSuccess: (result) => setSummary(describeStatement(result)),
                  onError: (err) => showToast(apiErrorMessage(err, "Nie udało się wczytać wyciągu."), "error"),
                });
              }}
            />
            <Button size="sm" variant="outline" loading={upload.isPending} onClick={() => input.current?.click()}>
              Wgraj wyciąg
            </Button>
          </>
        ) : null
      }
    >
      <p className="text-xs text-muted-foreground">
        Obciążenia z wyciągu oznaczają faktury jako zapłacone. Przelewy do osób z zespołu zostają
        Płacom, wpłaty klientów — „Fakturom do klientów”.
      </p>
      {summary ? (
        <div className="rounded-lg border border-border bg-muted/40 px-3.5 py-2 text-sm">{summary}</div>
      ) : null}
      {overview.isError ? (
        <QueryStateNotice state="error" onRetry={() => overview.refetch()} />
      ) : overview.isSuccess && lines.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nic nie czeka na sprawdzenie.</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card text-sm">
          {lines.map((line) => (
            <li key={line.id} className="space-y-1 px-3.5 py-2">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="tabular-nums">{formatIsoDatePl(line.booked_on)}</span>
                <span className="font-medium tabular-nums">{formatMoney(line.amount, line.currency)}</span>
                <span className="min-w-0 flex-1 truncate" title={line.title}>
                  {line.counterparty_name ? `${line.counterparty_name} · ` : ""}
                  {line.title || "—"}
                </span>
                {canWrite ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      const reason = await askReason({
                        title: "Pominąć operację z wyciągu?",
                        description: "Pominięta operacja nie oznaczy żadnej faktury jako zapłaconej.",
                        confirmLabel: "Pomiń",
                        field: { label: "Powód", placeholder: "np. przelew spoza faktur", minLength: 3, maxLength: 500 },
                      });
                      if (!reason) return;
                      ignore.mutate(
                        { id: line.id, reason },
                        { onError: (err) => showToast(apiErrorMessage(err, "Nie udało się pominąć."), "error") },
                      );
                    }}
                  >
                    Pomiń
                  </Button>
                ) : null}
              </div>
              {line.reason ? <p className="text-xs text-warning-muted-foreground">{line.reason}</p> : null}
              {line.hints.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {line.hints.map((hint) => (
                    <Button
                      key={hint.entry_id}
                      size="sm"
                      variant="outline"
                      disabled={!canWrite || assign.isPending}
                      onClick={() =>
                        assign.mutate(
                          { id: line.id, entryId: hint.entry_id },
                          {
                            onSuccess: () => showToast("Zapłata przypisana.", "success"),
                            onError: (err) =>
                              showToast(apiErrorMessage(err, "Nie udało się przypisać."), "error"),
                          },
                        )
                      }
                    >
                      Przypisz: {hint.invoice_number ?? `#${hint.entry_id}`} · {hint.seller_name ?? ""} ·{" "}
                      {formatMoney(hint.gross_amount, hint.currency)}
                    </Button>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {confirmDialog}
    </Section>
  );
}

/**
 * Finanse → „Przelewy” (makieta M6): faktury do zapłaty do daty, paczka
 * Elixir-O / CSV, paczki i zapłaty z wyciągu. `canWrite = false` (podgląd jako
 * inna osoba) — bez zaznaczania i przycisków.
 */
export function PaymentsTab({ canWrite = true }: { canWrite?: boolean }) {
  const today = warsawToday();
  const [until, setUntil] = useState(today);
  const plan = usePaymentPlan(until);
  const create = useCreateBatch();
  const { showToast } = useToast();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [acknowledged, setAcknowledged] = useState<Set<number>>(new Set());
  const [execution, setExecution] = useState(today);
  const [format, setFormat] = useState<"elixir" | "csv">("elixir");
  const items = useMemo(() => plan.data?.items ?? [], [plan.data]);

  useEffect(() => {
    setSelected(initialSelection(items));
    setAcknowledged(new Set());
  }, [items]);

  const summary = selectionSummary(items, selected, acknowledged);
  const blocker = createBlocker(summary);
  const toggle = (setter: typeof setSelected) => (id: number, on: boolean) =>
    setter((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  return (
    <div className="space-y-5">
      <SenderSettings canWrite={canWrite} />
      <Section
        title="Do zapłaty"
        aside={
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            z terminem do
            <input
              type="date"
              aria-label="Termin płatności do"
              value={until}
              onChange={(event) => setUntil(event.target.value || today)}
              className={CONTROL}
            />
          </label>
        }
      >
        <p className="text-xs text-muted-foreground">
          Faktury bez terminu płatności nie trafiają do paczki — termin wpisz na karcie faktury.
        </p>
        {plan.isLoading ? (
          <p className="py-6 text-sm text-muted-foreground">Sprawdzanie faktur i rachunków…</p>
        ) : plan.isError ? (
          <QueryStateNotice state="error" onRetry={() => plan.refetch()} />
        ) : plan.isSuccess && items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
            Nie ma faktur z terminem do {formatIsoDatePl(until)}.
          </div>
        ) : (
          <PlanTable
            items={items}
            selected={selected}
            acknowledged={acknowledged}
            canWrite={canWrite}
            onSelect={toggle(setSelected)}
            onAcknowledge={toggle(setAcknowledged)}
          />
        )}
        {canWrite && items.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card px-3.5 py-2.5 text-sm">
            <span>
              Zaznaczone: <strong className="tabular-nums">{summary.count}</strong>
              {Object.entries(summary.totals).map(([currency, total]) => (
                <span key={currency} className="ml-2 tabular-nums">
                  {formatMoney(total, currency)}
                </span>
              ))}
            </span>
            <label className="ml-auto flex items-center gap-2 text-muted-foreground">
              Data wykonania
              <input
                type="date"
                aria-label="Data wykonania"
                value={execution}
                min={today}
                onChange={(event) => setExecution(event.target.value || today)}
                className={CONTROL}
              />
            </label>
            <select
              aria-label="Format pliku"
              value={batchFormat(summary.currency, format)}
              disabled={summary.currency !== null && summary.currency !== "PLN"}
              onChange={(event) => setFormat(event.target.value as "elixir" | "csv")}
              className={CONTROL}
            >
              <option value="elixir">Elixir-O</option>
              <option value="csv">CSV</option>
            </select>
            <Button
              size="sm"
              disabled={blocker !== null || create.isPending}
              loading={create.isPending}
              title={blocker ?? undefined}
              onClick={() =>
                create.mutate(
                  {
                    entry_ids: items
                      .filter((item) => item.selectable && selected.has(item.entry_id))
                      .map((item) => item.entry_id),
                    acknowledged: Array.from(acknowledged),
                    execution_date: execution,
                    format: batchFormat(summary.currency, format),
                  },
                  {
                    onSuccess: (batch) =>
                      showToast(
                        `Paczka #${batch.id} utworzona: ${batch.count} · ${formatMoney(batch.total, batch.currency)}.`,
                        "success",
                      ),
                    onError: (err) => showToast(apiErrorMessage(err, "Nie udało się utworzyć paczki."), "error"),
                  },
                )
              }
            >
              Utwórz paczkę
            </Button>
            {blocker && summary.count > 0 ? (
              <span className="basis-full text-xs text-warning-muted-foreground">{blocker}</span>
            ) : null}
          </div>
        ) : null}
      </Section>
      <Batches canWrite={canWrite} />
      <Statement canWrite={canWrite} />
    </div>
  );
}

export default PaymentsTab;
