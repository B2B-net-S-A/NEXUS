"use client";

import { useState } from "react";
import { FileDown, Upload } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
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
  downloadImportControlSheet,
  useApplyImport,
  useImportBatch,
  useImports,
  useUpdateImportRow,
  useUploadImport,
  type EquipmentHolder,
  type ImportDecision,
  type ImportRow,
} from "@/lib/api/equipment";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";
import { formatIsoDatePl } from "@/lib/date-pl";

import {
  CATEGORY_LABELS,
  DECISION_LABELS,
  ITEM_STATUS_LABELS,
} from "./equipment-format";
import { FilterSelect } from "./FilterSelect";
import { HolderPicker } from "./HolderPicker";

const DECISIONS = Object.keys(DECISION_LABELS) as ImportDecision[];

function rowNumber(row: ImportRow): string {
  const d = row.data;
  return (
    d.inventory_number ??
    d.serial_number ??
    d.imei ??
    d.phone_number ??
    d.access_card_number ??
    "—"
  );
}

function ResolveRowDialog({
  batchId,
  row,
  onClose,
}: {
  batchId: number;
  row: ImportRow;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const update = useUpdateImportRow(batchId);
  const [holder, setHolder] = useState<EquipmentHolder | null>(null);
  const [error, setError] = useState<string | null>(null);

  const save = (decision: ImportDecision, withHolder: boolean) => {
    setError(null);
    update.mutate(
      {
        rowId: row.id,
        decision,
        holder_user_id: withHolder && holder?.kind === "user" ? holder.id : null,
        holder_contract_id: withHolder && holder?.kind === "contract" ? holder.id : null,
      },
      {
        onSuccess: () => {
          showToast("Decyzja zapisana", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać decyzji.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={`Wiersz ${row.row_number} · ${row.sheet}`}
      description={`${CATEGORY_LABELS[row.data.category ?? "inne"]} ${row.data.model ?? ""} · ${rowNumber(row)}${
        row.data.holder_text ? ` · w pliku: ${row.data.holder_text}` : ""
      }`}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button variant="outline" disabled={update.isPending} onClick={() => save("pomin", false)}>
            Pomiń
          </Button>
          <Button variant="outline" disabled={update.isPending} onClick={() => save("przyjmij", false)}>
            Przyjmij jako wolny
          </Button>
          <Button
            disabled={!holder || holder.kind === "external" || update.isPending}
            onClick={() => save("przyjmij", true)}
          >
            Przyjmij u tej osoby
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        {row.reason ? <p className="text-muted-foreground">Powód: {row.reason}</p> : null}
        <HolderPicker value={holder} onChange={setHolder} />
        {holder?.kind === "external" ? (
          <p className="text-xs text-destructive">
            Import przypisuje sprzęt do konta albo kontraktu. Osobie spoza NEXUSA wydaj go kreatorem.
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}

function BatchView({ batchId }: { batchId: number }) {
  const { showToast } = useToast();
  const [decision, setDecision] = useState<ImportDecision | "">("do_wyjasnienia");
  const batch = useImportBatch(batchId, decision);
  const apply = useApplyImport();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [resolving, setResolving] = useState<ImportRow | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const rows = batch.data?.rows ?? [];
  const state = resolveViewState({
    isLoading: batch.isLoading,
    error: batch.error,
    isSuccess: batch.isSuccess,
  });
  if (state === "loading") return <p className="text-sm text-muted-foreground">Wczytywanie partii…</p>;
  if (state !== "ready" || !batch.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        onRetry={() => batch.refetch()}
      />
    );
  }
  const summary = batch.data.summary;
  const counts = summary.counts ?? {};

  const onApply = async () => {
    const ok = await askConfirm({
      title: "Zapisać partię do rejestru?",
      description: `Powstanie ${counts.przyjmij ?? 0} pozycji (bez tych, które są już w rejestrze). Wiersze do wyjaśnienia poczekają na decyzję.`,
      confirmLabel: "Zapisz do rejestru",
    });
    if (!ok) return;
    apply.mutate(batchId, {
      onSuccess: (result) =>
        showToast(
          `Zapisano ${result.created} pozycji${result.conflicts ? `, konflikty: ${result.conflicts}` : ""}`,
          "success",
        ),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać partii."), "error"),
    });
  };

  const onDownload = async () => {
    setDownloadError(null);
    try {
      await downloadImportControlSheet(batchId);
    } catch (err) {
      setDownloadError(apiErrorMessage(err, "Nie udało się pobrać arkusza kontrolnego."));
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <InlineStats
          stats={DECISIONS.map((key) => ({
            id: key,
            label: DECISION_LABELS[key].toLowerCase(),
            value: counts[key] ?? 0,
          }))}
        />
        <div className="ml-auto flex gap-2">
          <Button variant="outline" onClick={onDownload}>
            <FileDown className="h-4 w-4" aria-hidden />
            Arkusz kontrolny
          </Button>
          <Button onClick={onApply} disabled={apply.isPending}>
            {apply.isPending ? "Zapisywanie…" : "Zatwierdź i zapisz"}
          </Button>
        </div>
      </div>
      {downloadError ? (
        <p role="alert" className="text-sm text-destructive">
          {downloadError}
        </p>
      ) : null}
      {(summary.removed_columns?.length ?? 0) > 0 ? (
        <div className="rounded-md border border-border bg-muted/40 p-3 text-xs">
          <p className="font-medium text-foreground">
            Kolumny pominięte — dane, których NEXUS nie przechowuje:
          </p>
          <ul className="mt-1 list-disc pl-5 text-muted-foreground">
            {summary.removed_columns?.map((column) => (
              <li key={`${column.sheet}-${column.column}`}>
                {column.sheet} · „{column.column}” — {column.reason}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-muted-foreground">
            Usuń te dane także z pliku źródłowego — klucz BitLocker powinien być tylko w Intune.
          </p>
        </div>
      ) : null}
      <FilterSelect
        label="Decyzja"
        value={decision}
        allLabel="Wszystkie wiersze"
        options={DECISIONS.map((value) => ({ value, label: DECISION_LABELS[value] }))}
        onChange={setDecision}
      />
      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          Brak wierszy z tą decyzją.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table density="compact" className="min-w-[900px]">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Arkusz · wiersz</TableHead>
                <TableHead className={CALM_HEAD}>Pozycja</TableHead>
                <TableHead className={CALM_HEAD}>Numer</TableHead>
                <TableHead className={CALM_HEAD}>Osoba w pliku → w NEXUSIE</TableHead>
                <TableHead className={CALM_HEAD}>Decyzja</TableHead>
                <TableHead className={CALM_HEAD} />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id} className={`${CALM_ROW} h-[46px]`}>
                  <TableCell className="text-xs">
                    {row.sheet} · {row.row_number}
                  </TableCell>
                  <TableCell>
                    {CATEGORY_LABELS[row.data.category ?? "inne"]} {row.data.model}
                    {row.data.item_status ? (
                      <span className={CALM_SUBLINE}>
                        po imporcie: {ITEM_STATUS_LABELS[row.data.item_status]}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{rowNumber(row)}</TableCell>
                  <TableCell>
                    {row.data.holder_text ?? <span className={CALM_EMPTY}>—</span>}
                    <span className={CALM_SUBLINE}>{row.holder_name ?? "bez dopasowania"}</span>
                  </TableCell>
                  <TableCell>
                    {DECISION_LABELS[row.decision]}
                    {row.reason ? <span className={CALM_SUBLINE}>{row.reason}</span> : null}
                  </TableCell>
                  <TableCell className="text-right">
                    {row.applied ? (
                      <span className="text-xs text-muted-foreground">w rejestrze</span>
                    ) : (
                      <Button variant="ghost" size="sm" onClick={() => setResolving(row)}>
                        Rozstrzygnij
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {resolving ? (
        <ResolveRowDialog
          key={resolving.id}
          batchId={batchId}
          row={resolving}
          onClose={() => setResolving(null)}
        />
      ) : null}
      {confirmDialog}
    </div>
  );
}

/** Import plików recepcji: wgranie → arkusz kontrolny → decyzje → zapis. */
export function ImportTab() {
  const { showToast } = useToast();
  const imports = useImports();
  const upload = useUploadImport();
  const [selected, setSelected] = useState<number | null>(null);
  const batches = imports.data ?? [];
  const current = selected ?? batches[0]?.id ?? null;
  const state = resolveViewState({
    isLoading: imports.isLoading,
    error: imports.error,
    isSuccess: imports.isSuccess,
    isEmpty: batches.length === 0,
  });

  const onFile = (file: File | null) => {
    if (!file) return;
    upload.mutate(file, {
      onSuccess: (batch) => {
        setSelected(batch.id);
        showToast("Plik wczytany — sprawdź arkusz kontrolny przed zapisem", "success");
      },
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się wczytać pliku."), "error"),
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-border p-4 text-sm">
        <Upload className="h-5 w-5 text-muted-foreground" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="font-medium">Wgraj plik recepcji (.xlsx)</p>
          <p className="text-xs text-muted-foreground">
            Nic nie trafia do rejestru przed zatwierdzeniem. Kolumny z kluczami BitLocker, PUK,
            PESEL-ami i prywatnymi e-mailami są pomijane.
          </p>
        </div>
        <label className="inline-flex h-9 cursor-pointer items-center rounded-md bg-primary px-4 text-sm text-primary-foreground hover:bg-primary/90">
          {upload.isPending ? "Wczytywanie…" : "Wybierz plik"}
          <input
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            className="sr-only"
            disabled={upload.isPending}
            onChange={(event) => {
              onFile(event.target.files?.[0] ?? null);
              event.target.value = "";
            }}
          />
        </label>
      </div>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie importów…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => imports.refetch()} />
      ) : state === "empty" ? null : (
        <>
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Partie importu">
            {batches.map((batch) => (
              <button
                key={batch.id}
                type="button"
                role="tab"
                aria-selected={batch.id === current}
                onClick={() => setSelected(batch.id)}
                className={`rounded-md border px-3 py-1.5 text-left text-xs ${
                  batch.id === current
                    ? "border-primary bg-primary/5 text-foreground"
                    : "border-border text-muted-foreground hover:bg-muted"
                }`}
              >
                <span className="block font-medium">{batch.file_name}</span>
                {formatIsoDatePl(batch.created_at)} ·{" "}
                {batch.status === "zatwierdzona" ? "zapisana" : "czeka na zatwierdzenie"}
              </button>
            ))}
          </div>
          {current ? <BatchView key={current} batchId={current} /> : null}
        </>
      )}
    </div>
  );
}
