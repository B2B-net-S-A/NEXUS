"use client";

import { Lock, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  useAssetCard,
  useDeleteAsset,
  useDeleteAssetOperation,
  type AssetOperation,
  type AssetOperationType,
  type AssetPlanRow,
} from "@/lib/api/accounting-assets";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { useAccounting } from "./AccountingShell";
import { AssetFormModal, OperationModal } from "./AssetForms";
import { monthText, planLabel, planWindow, rateText } from "./assets-model";
import { datePl, gr } from "./ledger-model";

type Tab = "balance" | "tax" | "documents";
const TABS: ReadonlyArray<{ value: Tab; label: string }> = [
  { value: "balance", label: "Plan bilansowy" },
  { value: "tax", label: "Podatkowy" },
  { value: "documents", label: "Dokumenty" },
];
const ACTIONS: ReadonlyArray<{ type: Exclude<AssetOperationType, "OT">; label: string }> = [
  { type: "UL", label: "Ulepszenie" },
  { type: "MT", label: "Zmiana MPK" },
  { type: "LT", label: "Likwidacja" },
  { type: "SP", label: "Sprzedaż" },
];

/** Stan dokumentu środka w księdze po polsku. */
export function operationState(op: AssetOperation): string {
  if (!op.posted) return op.op_type === "MT" ? "bez zapisu — zmienia podział AM" : "bez zapisu w księdze";
  if (!op.document) return "do zaksięgowania („Nalicz amortyzację”)";
  return op.document.status === "approved" ? `zapis nr ${op.document.journal_no}` : "w buforze";
}

/** Karta środka: fakty, plan bilansowy i podatkowy, dokumenty i akcje. */
export function AssetPanel({ id, onClose }: { id: number; onClose: () => void }) {
  const { period } = useAccounting();
  const card = useAssetCard(id, period.year, period.month);
  const [tab, setTab] = useState<Tab>("balance");
  const [full, setFull] = useState(false);
  const [operation, setOperation] = useState<Exclude<AssetOperationType, "OT"> | null>(null);
  const [editing, setEditing] = useState(false);
  const removeAsset = useDeleteAsset();
  const removeOperation = useDeleteAssetOperation();
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();

  if (card.isLoading) {
    return <aside className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">Wczytywanie…</aside>;
  }
  if (card.isError || !card.data) {
    return <QueryStateNotice state="error" onRetry={() => card.refetch()} />;
  }
  const asset = card.data;
  const month = `${period.year}-${String(period.month).padStart(2, "0")}`;
  const rows = tab === "tax" ? asset.tax_plan : asset.balance_plan;
  const shown = full ? rows : planWindow(rows, month);

  const dropAsset = async () => {
    const ok = await askConfirm({
      title: `Usunąć środek ${asset.inventory_number}?`,
      description: "Środek bez zatwierdzonych zapisów znika z ewidencji razem ze szkicami w buforze.",
      confirmLabel: "Usuń środek",
      variant: "destructive",
    });
    if (!ok) return;
    removeAsset.mutate(asset.id, {
      onSuccess: () => {
        showToast(`Usunięto ${asset.inventory_number}.`);
        onClose();
      },
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się usunąć środka."), "error"),
    });
  };

  const dropOperation = async (op: AssetOperation) => {
    const ok = await askConfirm({
      title: `Usunąć ${op.number}?`,
      description: "Usuwa się tylko ostatni dokument środka bez zapisu w dzienniku; jego szkic zniknie z bufora.",
      confirmLabel: "Usuń dokument",
      variant: "destructive",
    });
    if (!ok) return;
    removeOperation.mutate(op.id, {
      onSuccess: () => showToast(`Usunięto ${op.number}.`),
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się usunąć dokumentu."), "error"),
    });
  };

  return (
    <aside className="min-w-0 self-start rounded-lg border border-border bg-card" aria-label={`Środek ${asset.inventory_number}`}>
      <div className="flex items-start justify-between gap-2 border-b border-border/70 px-3.5 py-2.5">
        <div className="min-w-0">
          <p className="flex flex-wrap items-baseline gap-x-2 text-[13px]">
            <span className="font-mono font-semibold">{asset.inventory_number}</span>
            <span className="text-muted-foreground">{planLabel(asset.balance_method, asset.balance_rate)}</span>
          </p>
          <h2 className="mt-0.5 text-sm font-semibold">{asset.name}</h2>
        </div>
        <Button size="icon-sm" variant="ghost" aria-label="Zamknij kartę" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="space-y-1 px-3.5 py-2.5 text-[12.5px] text-muted-foreground">
        <p>
          {asset.kind_label}
          {asset.kst ? ` · KŚT ${asset.kst}` : ""} · przyjęty {datePl(asset.accepted_on)} · wartość{" "}
          <span className="whitespace-nowrap tabular-nums text-foreground">
            {gr(asset.position.value || asset.initial_value)} zł
          </span>
        </p>
        <p className="font-mono text-[12px]">
          Konto {asset.asset_account} · umorzenie {asset.depreciation_account} → MPK {asset.mpk_label}
        </p>
        <p>
          Odpis {monthText(month)}:{" "}
          <span className="whitespace-nowrap tabular-nums text-foreground">{gr(asset.position.amount)} zł</span>
          {asset.position.plan_end ? ` · plan do ${monthText(asset.position.plan_end)}` : " · bez planu odpisów"}
          {" · "}podatkowo {planLabel(asset.tax_method, asset.tax_rate)}
          {asset.balance_method === "degressive" || asset.tax_method === "degressive"
            ? ` (współczynnik ${rateText(asset.coefficient).replace("%", "")})`
            : ""}
        </p>
        <p>
          Umorzenie na koniec {monthText(month)}:{" "}
          <span className="whitespace-nowrap tabular-nums text-foreground">{gr(asset.position.accumulated)} zł</span> · netto{" "}
          <span className="whitespace-nowrap tabular-nums text-foreground">{gr(asset.position.net)} zł</span>
        </p>
        {asset.opening ? (
          <p>
            Stan z Symfonii na koniec {monthText(asset.opening.month)}: umorzenie {gr(asset.opening.balance)} zł (podatkowe{" "}
            {gr(asset.opening.tax)} zł)
          </p>
        ) : null}
        {asset.equipment ? (
          <p>
            „Sprzęt”: {asset.equipment.model}
            {asset.equipment.inventory_number ? ` · nr ${asset.equipment.inventory_number}` : ""}
            {asset.equipment.serial_number ? ` · SN ${asset.equipment.serial_number}` : ""}
          </p>
        ) : null}
        {asset.status !== "in_use" ? (
          <StatusDot tone="neutral">
            {asset.status_label} {datePl(asset.disposed_on)}
          </StatusDot>
        ) : null}
        {asset.locked ? (
          <p className="flex items-start gap-1.5 text-[12px]">
            <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            Plan zatwierdzony ({asset.locked}) — parametrów już się nie zmienia; zmianę robi się dokumentem albo stornem.
          </p>
        ) : null}
        {asset.note ? <p className="italic">{asset.note}</p> : null}
      </div>

      {asset.can_manage ? (
        <div className="flex flex-wrap gap-1.5 border-t border-border/70 px-3.5 py-2">
          {asset.status === "in_use"
            ? ACTIONS.map((action) => (
                <Button key={action.type} size="sm" variant="outline" onClick={() => setOperation(action.type)}>
                  {action.label}
                </Button>
              ))
            : null}
          <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
            Edytuj
          </Button>
          {asset.can_delete ? (
            <Button size="sm" variant="quiet" onClick={() => void dropAsset()}>
              Usuń
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="border-t border-border/70 px-3.5 pt-2.5">
        <SegmentedRadio label="Widok karty środka" size="sm" value={tab} onChange={setTab} options={TABS} />
      </div>
      {tab === "documents" ? (
        <OperationsList operations={asset.operations} onDelete={(op) => void dropOperation(op)} />
      ) : (
        <PlanTable rows={shown} month={month} withState={tab === "balance"} />
      )}
      {tab !== "documents" && rows.length > shown.length ? (
        <div className="px-3.5 pb-2.5">
          <Button size="sm" variant="tertiary" onClick={() => setFull(true)}>
            Pokaż cały plan ({rows.length} mies.)
          </Button>
        </div>
      ) : null}
      {tab !== "documents" && rows.length === 0 ? (
        <p className="px-3.5 pb-3 text-[13px] text-muted-foreground">
          {asset.opening ? "Środek jest w pełni umorzony według stanu z Symfonii." : "Ten plan nie ma odpisów."}
        </p>
      ) : null}
      <p className="px-3.5 pb-2.5 text-[11.5px] text-muted-foreground">
        AM miesiąca robi „Nalicz amortyzację”; zatwierdza lista „Księgowi” w{" "}
        <Link className="text-primary hover:underline" href={`/accounting/documents?year=${period.year}&month=${period.month}&type=AM`}>
          Dokumentach
        </Link>
        .
      </p>

      {operation ? <OperationModal asset={asset} type={operation} onClose={() => setOperation(null)} /> : null}
      <AssetFormModal open={editing} editing={asset} intakeAccount="" onClose={() => setEditing(false)} />
      {confirmDialog}
    </aside>
  );
}

function PlanTable({ rows, month, withState }: { rows: AssetPlanRow[]; month: string; withState: boolean }) {
  if (rows.length === 0) return null;
  return (
    <table className="mt-1 w-full table-fixed text-[13px]">
      <thead>
        <tr className="border-b border-border/70">
          <th className={cn(CALM_HEAD, "px-3.5 py-1.5 text-left")}>Miesiąc</th>
          <th className={cn(CALM_HEAD, "px-2 py-1.5 text-right")}>Odpis</th>
          <th className={cn(CALM_HEAD, "px-3.5 py-1.5 text-right")}>Umorzenie</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.month} className={cn(CALM_ROW, "last:border-0", row.month === month && "bg-primary/5")}>
            <td className="px-3.5 py-1.5 tabular-nums">
              {monthText(row.month)}
              {withState && row.state && row.state !== "plan" ? (
                <span className={CALM_SUBLINE}>
                  {row.state === "approved" ? `AM — zapis nr ${row.journal_no}` : "AM w buforze"}
                </span>
              ) : null}
              {row.degressive ? <span className={CALM_SUBLINE}>degresywnie</span> : null}
            </td>
            <td className={cn(CALM_AMOUNT, "px-2 py-1.5")}>{gr(row.amount)}</td>
            <td className={cn(CALM_AMOUNT, "px-3.5 py-1.5")}>{gr(row.accumulated)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OperationsList({ operations, onDelete }: { operations: AssetOperation[]; onDelete: (op: AssetOperation) => void }) {
  if (operations.length === 0) {
    return (
      <p className="px-3.5 py-3 text-[13px] text-muted-foreground">
        Środek przeniesiony z Symfonii — jego dokumenty do miesiąca stanu są w Symfonii Środki Trwałe.
      </p>
    );
  }
  return (
    <ul className="mt-1">
      {operations.map((op) => (
        <li key={op.id} className={cn(CALM_ROW, "flex items-start justify-between gap-2 px-3.5 py-2 text-[13px] last:border-0")}>
          <div className="min-w-0">
            <p>
              <span className="font-medium">{op.number}</span> · {op.label} · {datePl(op.op_date)}
            </p>
            <span className={CALM_SUBLINE}>
              {[
                op.amount ? `${gr(op.amount)} zł` : null,
                op.mpk_to ? `${op.mpk_from} → ${op.mpk_to}` : null,
                op.cost_entry ? `faktura ${op.cost_entry.invoice_number ?? op.cost_entry.id}` : null,
                operationState(op),
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
            {op.note ? <span className={CALM_SUBLINE}>{op.note}</span> : null}
          </div>
          {op.can_delete ? (
            <Button size="sm" variant="quiet" onClick={() => onDelete(op)}>
              Usuń
            </Button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
