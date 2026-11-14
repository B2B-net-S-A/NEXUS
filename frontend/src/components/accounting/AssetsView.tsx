"use client";

import { useState } from "react";

import { InlineStats, QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { useAssets, useSyncAssets, type AssetListItem, type AssetScope } from "@/lib/api/accounting-assets";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE, CALM_UNIT } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { useAccounting } from "./AccountingShell";
import { AssetPanel } from "./AssetPanel";
import { AccountsModal, AssetFormModal, ImportModal } from "./AssetForms";
import { assetsSyncMessage, monthText, rateText } from "./assets-model";
import { datePl, findPeriod, gr, short } from "./ledger-model";

const SCOPES: ReadonlyArray<{ value: AssetScope; label: string }> = [
  { value: "month", label: "W miesiącu" },
  { value: "all", label: "Cała ewidencja" },
];

type Modal = { kind: "create" } | { kind: "import" } | { kind: "accounts" } | null;

/** „ST/2026/001 · KŚT 491 · 30% · MPK Koszty ogólne” — druga linia wiersza. */
export function assetSubline(item: AssetListItem): string {
  const parts = [item.inventory_number, item.kind === "fixed" ? `KŚT ${item.kst ?? "—"}` : "WNiP"];
  if (item.balance_method === "linear" || item.balance_method === "degressive") parts.push(rateText(item.balance_rate));
  else parts.push(item.method_label);
  parts.push(`MPK ${item.mpk_label}`);
  return parts.join(" · ");
}

/**
 * Środki trwałe i WNiP (K6): ewidencja z wartościami na koniec miesiąca,
 * odpis miesiąca, karta z planem amortyzacji. „Nalicz amortyzację” robi
 * dokumenty środków i AM miesiąca w buforze — zatwierdza lista „Księgowi”.
 */
export function AssetsView() {
  const { config, period } = useAccounting();
  const open = config.modules.find((module) => module.key === "assets")?.open ?? false;
  const [scope, setScope] = useState<AssetScope>("month");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [modal, setModal] = useState<Modal>(null);
  const data = useAssets(period.year, period.month, scope, open);
  const sync = useSyncAssets();
  const { showToast } = useToast();
  const { year, period: ledgerPeriod } = findPeriod(config, period);
  const label = monthText(`${period.year}-${String(period.month).padStart(2, "0")}`);

  if (!open) {
    return (
      <p className="rounded-md border border-border bg-muted/40 px-3.5 py-2 text-[13px] text-muted-foreground">
        Moduł „Środki trwałe” jest wyłączony — włącza go administrator w Ustawieniach.
      </p>
    );
  }
  if (data.isError) return <QueryStateNotice state="error" onRetry={() => data.refetch()} />;
  if (!data.isSuccess) return <p className="text-sm text-muted-foreground">Wczytywanie ewidencji…</p>;

  const overview = data.data;
  const stats = overview.stats;
  const periodOpen = year?.status === "open" && ledgerPeriod?.status === "open";
  const runSync = () =>
    sync.mutate(
      { year: period.year, month: period.month },
      {
        onSuccess: (result) => showToast(assetsSyncMessage(result)),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się naliczyć amortyzacji."), "error"),
      },
    );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-x-5 gap-y-3">
        <InlineStats
          stats={[
            { id: "count", label: "Środki i WNiP", value: stats.count },
            { id: "value", label: "Wartość początkowa", value: short(stats.value) },
            { id: "accumulated", label: "Umorzenie", value: short(stats.accumulated) },
            { id: "month", label: `Odpis ${label}`, value: `${gr(stats.month_amount)} zł` },
            {
              id: "equipment",
              label: "Niskocenne w „Sprzęcie”",
              value: stats.equipment_unlinked,
              title: "Pozycje „Sprzętu” firmy bez karty środka trwałego (koszt od razu)",
            },
          ]}
        />
        <div className="flex flex-wrap items-center gap-2">
          {overview.can_configure ? (
            <Button size="sm" variant="ghost" onClick={() => setModal({ kind: "accounts" })}>
              Konta
            </Button>
          ) : null}
          {overview.can_manage ? (
            <>
              <Button size="sm" variant="outline" onClick={() => setModal({ kind: "import" })}>
                Import z Symfonii
              </Button>
              <Button size="sm" variant="outline" onClick={() => setModal({ kind: "create" })}>
                Przyjmij środek (OT)
              </Button>
            </>
          ) : null}
          <Button
            size="sm"
            loading={sync.isPending}
            disabled={!periodOpen}
            title={periodOpen ? undefined : "Okres jest zamknięty albo rok nie jest założony"}
            onClick={runSync}
          >
            Nalicz amortyzację {label.replace(".", "/")}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-muted-foreground">
        <SegmentedRadio label="Zakres ewidencji" size="sm" value={scope} onChange={setScope} options={SCOPES} />
        <span>
          {overview.am
            ? `${overview.am.number}: ${overview.am.status === "approved" ? `zatwierdzony, zapis nr ${overview.am.journal_no}` : "w buforze"} · ${gr(overview.am.total)} zł`
            : stats.month_amount
              ? `AM ${label} nie jest jeszcze naliczony`
              : `W ${label} nie ma odpisów`}
          {" · "}amortyzacja {overview.accounts.cost_account}, przyjęcie {overview.accounts.intake_account}, zbycie{" "}
          {overview.accounts.disposal_account}
        </span>
      </div>
      {!overview.allocation_complete ? (
        <p className="rounded-md border border-border bg-muted/40 px-3.5 py-2 text-[13px] text-muted-foreground">
          AM dzieli amortyzację na konta „5” z MPK — ustawia je administrator w Ustawieniach („Rozliczenie kosztów na
          „5””). Bez nich AM czeka w „Źródłach” z problemem.
        </p>
      ) : null}

      <div className={cn("grid gap-3", selectedId != null && "xl:grid-cols-[minmax(0,1fr)_360px]")}>
        <div className="min-w-0">
          {overview.items.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-6 py-10 text-center">
              <p className="text-sm font-medium">
                {scope === "month" ? `W ewidencji nie ma środków w ${label}` : "Ewidencja jest pusta"}
              </p>
              <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
                Środek przyjmuje dokumentem OT osoba z listy „Księgowi”; ewidencję z Symfonii Środki Trwałe wczytasz
                przyciskiem „Import z Symfonii” (stan umorzenia na koniec miesiąca).
              </p>
            </div>
          ) : (
            <AssetTable items={overview.items} selectedId={selectedId} onSelect={setSelectedId} label={label} />
          )}
        </div>
        {selectedId != null ? <AssetPanel id={selectedId} onClose={() => setSelectedId(null)} /> : null}
      </div>

      <AssetFormModal
        open={modal?.kind === "create"}
        editing={null}
        intakeAccount={overview.accounts.intake_account}
        onClose={() => setModal(null)}
        onSaved={(id) => setSelectedId(id)}
      />
      <ImportModal open={modal?.kind === "import"} onClose={() => setModal(null)} />
      <AccountsModal open={modal?.kind === "accounts"} accounts={overview.accounts} onClose={() => setModal(null)} />
    </div>
  );
}

function AssetTable({
  items,
  selectedId,
  onSelect,
  label,
}: {
  items: AssetListItem[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  label: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <table className="w-full table-fixed text-sm">
        <thead>
          <tr className="border-b border-border/70">
            <th className={cn(CALM_HEAD, "px-3.5 py-2 text-left")}>Środek · nr · KŚT</th>
            <th className={cn(CALM_HEAD, "w-[5.75rem] px-2 py-2 text-left")}>Przyjęto</th>
            <th className={cn(CALM_HEAD, "w-[6.75rem] px-2 py-2 text-right")}>
              Wartość<span className={CALM_UNIT}>zł</span>
            </th>
            <th className={cn(CALM_HEAD, "w-[6.75rem] px-2 py-2 text-right")}>
              Netto<span className={CALM_UNIT}>zł</span>
            </th>
            <th className={cn(CALM_HEAD, "w-[6.5rem] px-3.5 py-2 text-right")}>
              Odpis {label}
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.id}
              onClick={() => onSelect(item.id)}
              className={cn(
                CALM_ROW,
                "cursor-pointer align-top last:border-0 hover:bg-muted/40",
                item.id === selectedId && "bg-primary/5",
              )}
            >
              <td className="min-w-0 px-3.5 py-2">
                <button
                  type="button"
                  className="block w-full truncate text-left font-medium hover:underline"
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelect(item.id);
                  }}
                >
                  {item.name}
                </button>
                <span className={cn(CALM_SUBLINE, "truncate")}>
                  {assetSubline(item)}
                  {item.status !== "in_use" ? ` · ${item.status_label} ${datePl(item.disposed_on)}` : ""}
                </span>
              </td>
              <td className="whitespace-nowrap px-2 py-2 tabular-nums">{datePl(item.accepted_on)}</td>
              <td className={cn(CALM_AMOUNT, "px-2 py-2")}>{item.accepted ? gr(item.value) : <span className={CALM_EMPTY}>—</span>}</td>
              <td className={cn(CALM_AMOUNT, "px-2 py-2")}>{item.accepted ? gr(item.net) : <span className={CALM_EMPTY}>—</span>}</td>
              <td className={cn(CALM_AMOUNT, "px-3.5 py-2")}>
                {item.month_amount ? (
                  gr(item.month_amount)
                ) : item.fully_depreciated ? (
                  <span className="text-muted-foreground">umorzony</span>
                ) : (
                  <span className={CALM_EMPTY}>—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
