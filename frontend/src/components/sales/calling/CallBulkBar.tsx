"use client";

import { useEffect, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { apiErrorMessage } from "@/lib/api-error";
import { useOwnerCandidates } from "@/lib/api/sales";
import {
  fetchRecordIds,
  useBulkRecords,
  useCallCampaigns,
  type BulkInput,
  type BulkResult,
  type CallRecordFilters,
} from "@/lib/api/sales-calling";

import { SalesSelect } from "../SalesSelect";
import { BULK_TITLES, bulkDoneLine, bulkSkippedLine } from "./calling";

type DialogAction = keyof typeof BULK_TITLES;

const DESCRIPTIONS: Record<DialogAction, string> = {
  assign: "Rekordy trafią do kolejki wybranej osoby. Opiekun szansy się nie zmienia.",
  move: "Rekord przechodzi do innej kampanii ze statusem i historią. Firma, która ma już rekord w kampanii docelowej, zostaje na miejscu.",
  remove:
    "Rekordy znikną z kolejki, Tabeli i Przypomnień. Firma i historia telefonów zostają, a ta sama firma nie wróci z kolejnym importem.",
};

interface CallBulkBarProps {
  selected: readonly number[];
  /** Ile rekordów pasuje do filtra Tabeli (do „Zaznacz wszystkie z filtra”). */
  total: number;
  filters: CallRecordFilters;
  onSelect: (ids: number[]) => void;
  onClear: () => void;
}

/**
 * Akcje zbiorcze Tabeli (decyzja Artura 27.11.2026, wariant A): przypisz osobie, przenieś
 * do kampanii, usuń z listy z „Cofnij”. Komponent zostaje zamontowany także bez zaznaczenia,
 * żeby „Cofnij” w dymku działało po zamknięciu okna i wyczyszczeniu wyboru.
 */
export function CallBulkBar({ selected, total, filters, onSelect, onClear }: CallBulkBarProps) {
  const [dialog, setDialog] = useState<DialogAction | null>(null);
  const [selecting, setSelecting] = useState(false);
  const restore = useBulkRecords();
  const { showError, showInfo, showSuccess, showActionToast } = useToast();

  const selectAll = () => {
    setSelecting(true);
    fetchRecordIds(filters)
      .then(({ ids, truncated }) => {
        onSelect(ids);
        if (truncated) showInfo(`Zaznaczono pierwsze ${ids.length}. Zawęź filtr, żeby objąć resztę.`);
      })
      .catch((error: unknown) =>
        showError(apiErrorMessage(error, "Nie udało się zaznaczyć rekordów z filtra.")),
      )
      .finally(() => setSelecting(false));
  };

  const onSaved = (action: DialogAction, result: BulkResult) => {
    const count = result.done.length;
    onClear();
    setDialog(null);
    if (action !== "remove") {
      showSuccess(action === "assign" ? `Przypisano: ${count}.` : `Przeniesiono: ${count}.`);
      return;
    }
    showActionToast(`Usunięto z listy: ${count}.`, {
      actionLabel: "Cofnij",
      onAction: () =>
        restore
          .mutateAsync({ action: "restore", record_ids: result.done })
          .then(() => showSuccess(`Przywrócono na listę: ${count}.`))
          .catch((error: unknown) =>
            showError(apiErrorMessage(error, "Nie udało się przywrócić rekordów.")),
          ),
    });
  };

  return (
    <>
      {selected.length > 0 && (
        <div
          role="region"
          aria-label="Akcje zbiorcze"
          className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/40 bg-primary/5 px-3 py-1.5 text-xs"
        >
          <span className="font-medium text-foreground">Zaznaczone: {selected.length}</span>
          {total > selected.length && (
            <Button size="sm" variant="ghost" className="h-7 px-2" disabled={selecting} onClick={selectAll}>
              Zaznacz wszystkie {total} z filtra
            </Button>
          )}
          <span className="ml-auto flex flex-wrap items-center gap-1.5">
            {(Object.keys(BULK_TITLES) as DialogAction[]).map((action) => (
              <Button
                key={action}
                size="sm"
                variant={action === "remove" ? "quiet" : "outline"}
                className="h-7 px-2"
                onClick={() => setDialog(action)}
              >
                {BULK_TITLES[action]}
              </Button>
            ))}
            <Button size="sm" variant="ghost" className="h-7 px-2" onClick={onClear}>
              Odznacz
            </Button>
          </span>
        </div>
      )}
      {dialog && (
        <BulkDialog
          key={dialog}
          action={dialog}
          ids={selected}
          onClose={() => setDialog(null)}
          onSaved={(result) => onSaved(dialog, result)}
        />
      )}
    </>
  );
}

interface BulkDialogProps {
  action: DialogAction;
  ids: readonly number[];
  onClose: () => void;
  onSaved: (result: BulkResult) => void;
}

/** Najpierw liczby (`dry_run`), potem zapis: przeniesienie i usunięcie dotykają setek rekordów. */
function BulkDialog({ action, ids, onClose, onSaved }: BulkDialogProps) {
  const counting = useBulkRecords();
  const saving = useBulkRecords();
  const people = useOwnerCandidates(action === "assign");
  const campaigns = useCallCampaigns(action === "move");
  const [target, setTarget] = useState("");
  const [preview, setPreview] = useState<BulkResult | null>(null);
  const [countError, setCountError] = useState<string | null>(null);
  const { showError } = useToast();
  const needsTarget = action !== "remove";
  const count = counting.mutateAsync;

  useEffect(() => {
    setPreview(null);
    setCountError(null);
    if (needsTarget && !target) return;
    let live = true;
    count(payload(action, ids, target, true))
      .then((result) => live && setPreview(result))
      .catch(
        (error: unknown) =>
          live && setCountError(apiErrorMessage(error, "Nie udało się policzyć rekordów.")),
      );
    return () => {
      live = false;
    };
  }, [action, ids, target, needsTarget, count]);

  const done = preview?.done.length ?? 0;
  const save = () => {
    saving
      .mutateAsync(payload(action, ids, target, false))
      .then(onSaved)
      .catch((error: unknown) => showError(apiErrorMessage(error, "Nie udało się zapisać zmian.")));
  };
  const options =
    action === "assign"
      ? (people.data ?? []).map((person) => ({ value: String(person.id), label: person.name }))
      : (campaigns.data ?? []).map((campaign) => ({ value: String(campaign.id), label: campaign.name }));
  const skipped = preview ? bulkSkippedLine(preview.skipped) : null;
  const confirmLabel =
    action === "assign" ? `Przypisz ${done}` : action === "move" ? `Przenieś ${done}` : `Usuń ${done} z listy`;

  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title={`${BULK_TITLES[action]}: ${ids.length}`}
      description={DESCRIPTIONS[action]}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            variant={action === "remove" ? "destructive" : "primary"}
            disabled={!preview || done === 0 || saving.isPending}
            onClick={save}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        {needsTarget && (
          <div className="space-y-1">
            <Label htmlFor="call-bulk-target">{action === "assign" ? "Osoba" : "Kampania"}</Label>
            <SalesSelect
              id="call-bulk-target"
              ariaLabel={action === "assign" ? "Osoba" : "Kampania"}
              value={target}
              onValueChange={setTarget}
              options={options}
              anyLabel={action === "assign" ? "Wybierz osobę" : "Wybierz kampanię"}
            />
          </div>
        )}
        {countError ? (
          <p className="text-destructive">{countError}</p>
        ) : preview ? (
          <div className="space-y-1">
            <p className="font-medium text-foreground">{bulkDoneLine(action, done)}</p>
            {skipped && <p className="text-muted-foreground">{skipped}</p>}
          </div>
        ) : needsTarget && !target ? null : (
          <p className="text-muted-foreground">Liczenie rekordów…</p>
        )}
      </div>
    </AppModal>
  );
}

function payload(action: DialogAction, ids: readonly number[], target: string, dryRun: boolean): BulkInput {
  return {
    action,
    record_ids: [...ids],
    ...(action === "assign" && target ? { assignee_user_id: Number(target) } : {}),
    ...(action === "move" && target ? { campaign_id: Number(target) } : {}),
    dry_run: dryRun,
  };
}
