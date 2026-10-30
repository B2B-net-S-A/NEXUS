"use client";

import { useRef, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useApplySettlementImport,
  useSettlementImportPreview,
  type SettlementImportPreview,
  type SettlementImportRow,
  type SettlementRowStatus,
} from "@/lib/api/hr-payroll";
import { formatMoney } from "@/lib/money";

const STATUS: Record<SettlementRowStatus, { label: string; tone: string }> = {
  matches: { label: "Ta sama osoba co w NEXUSIE", tone: "bg-success-muted text-success-muted-foreground" },
  differs: { label: "Inna osoba w NEXUSIE", tone: "bg-warning-muted text-warning-muted-foreground" },
  zero: { label: "0 zł: odrzuci propozycję", tone: "bg-muted text-muted-foreground" },
  inactive: { label: "Konto nieaktywne", tone: "bg-destructive-muted text-destructive-muted-foreground" },
  no_contract: { label: "Bez kontraktu", tone: "bg-warning-muted text-warning-muted-foreground" },
  no_placement: { label: "Bez placementu", tone: "bg-muted text-muted-foreground" },
  no_person: { label: "Nie ma takiej osoby", tone: "bg-destructive-muted text-destructive-muted-foreground" },
  self: { label: "Własnej premii nie przyznajesz", tone: "bg-destructive-muted text-destructive-muted-foreground" },
  already_assigned: { label: "Już przyznana", tone: "bg-muted text-muted-foreground" },
};

const BLOCKED: ReadonlySet<SettlementRowStatus> = new Set(["no_person", "self", "already_assigned"]);

function automatHint(row: SettlementImportRow): string | null {
  if (row.status === "differs" && row.automat_name) return `Automat: ${row.automat_name}`;
  if (row.status === "matches" && row.automat_amount && Number(row.automat_amount) !== Number(row.amount)) {
    return `Automat policzył ${formatMoney(row.automat_amount, "PLN")}`;
  }
  return null;
}

/**
 * Rozliczenie miesiąca z arkusza Delivery. Podgląd niczego nie zapisuje; przyznanie
 * dotyczy tylko zaznaczonych wierszy, a uwagi z pliku nie trafiają do opisu premii.
 */
export function SettlementImportDialog({
  open,
  onOpenChange,
  year,
  month,
  label,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  year: number;
  month: number;
  label: string;
}) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const preview = useSettlementImportPreview(year, month);
  const apply = useApplySettlementImport(year, month);
  const input = useRef<HTMLInputElement>(null);
  const [data, setData] = useState<SettlementImportPreview | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const load = (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setFileName(file.name);
    preview.mutate(file, {
      onSuccess: (result) => {
        setData(result);
        setSelected(new Set(result.rows.filter((row) => row.selected).map((row) => row.index)));
      },
      onError: (err) => {
        setData(null);
        setError(apiErrorMessage(err, "Nie udało się odczytać arkusza."));
      },
    });
  };

  const toggle = (index: number, value: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (value) next.add(index);
      else next.delete(index);
      return next;
    });

  const chosen = data?.rows.filter((row) => selected.has(row.index)) ?? [];
  const sum = chosen.reduce((total, row) => total + Number(row.amount), 0);

  const submit = async () => {
    const ok = await askConfirm({
      title: `Przyznać premie z arkusza: ${chosen.length}?`,
      description: `Razem ${formatMoney(sum, "PLN")} za ${label}. Każda osoba dostanie powiadomienie bez kwoty. Jeśli któryś wiersz nie może wejść, nie wejdzie żaden.`,
      confirmLabel: "Przyznaj",
      cancelLabel: "Wróć",
    });
    if (!ok) return;
    setError(null);
    apply.mutate(chosen, {
      onSuccess: (result) => {
        showToast(
          `Przyznane: ${result.assigned}, odrzucone propozycje: ${result.rejected}, pominięte: ${result.skipped}`,
          "success",
        );
        onOpenChange(false);
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się przyznać premii.")),
    });
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      title={`Rozliczenie z arkusza: ${label}`}
      description={fileName ?? "Kolumny: osoba, kandydat, marża, kwota, uwagi. Plik nie jest zapisywany."}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          {data ? (
            <Button onClick={() => void submit()} disabled={apply.isPending || chosen.length === 0}>
              {apply.isPending ? "Przyznawanie…" : `Przyznaj zaznaczone (${chosen.length})`}
            </Button>
          ) : null}
        </>
      }
    >
      <div className="space-y-3">
        <input
          ref={input}
          type="file"
          accept=".xlsx"
          aria-label="Arkusz rozliczenia"
          className="hidden"
          onChange={(event) => load(event.target.files?.[0])}
        />
        {!data ? (
          <Button variant="secondary" onClick={() => input.current?.click()} disabled={preview.isPending}>
            {preview.isPending ? "Porównywanie…" : "Wybierz plik .xlsx"}
          </Button>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        {data ? (
          <>
            <ul className="flex flex-wrap gap-2 text-xs font-medium">
              {(Object.keys(STATUS) as SettlementRowStatus[])
                .filter((status) => data.counts[status])
                .map((status) => (
                  <li key={status} className={`rounded-full px-2 py-0.5 ${STATUS[status].tone}`}>
                    {STATUS[status].label}: {data.counts[status]}
                  </li>
                ))}
            </ul>
            <div className="relative overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[820px] text-sm">
                <thead>
                  <tr className="bg-muted/40 text-left text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
                    <th className="w-10 py-2 pl-3">
                      <span className="sr-only">Przyznaj</span>
                    </th>
                    <th className="py-2 pr-3">Osoba</th>
                    <th className="py-2 pr-3">Za kogo</th>
                    <th className="py-2 pr-3 text-right">Kwota</th>
                    <th className="py-2 pr-3">Porównanie</th>
                    <th className="py-2 pr-3">Uwagi z arkusza</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => {
                    const blocked = BLOCKED.has(row.status);
                    const hint = automatHint(row);
                    return (
                      <tr key={row.index} className="border-t border-border align-top">
                        <td className="py-2 pl-3">
                          <Checkbox
                            aria-label={`Przyznaj: ${row.person}, ${row.candidate}`}
                            checked={selected.has(row.index)}
                            disabled={blocked}
                            onCheckedChange={(value) => toggle(row.index, value === true)}
                          />
                        </td>
                        <td className="py-2 pr-3 text-foreground">{row.recipient_name ?? row.person}</td>
                        <td className="py-2 pr-3 text-foreground">{row.contract_label ?? row.candidate}</td>
                        <td className="whitespace-nowrap py-2 pr-3 text-right font-semibold tabular-nums text-foreground">
                          {formatMoney(row.amount, "PLN")}
                        </td>
                        <td className="py-2 pr-3">
                          <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${STATUS[row.status].tone}`}>
                            {STATUS[row.status].label}
                          </span>
                          {hint ? <span className="mt-1 block text-xs text-muted-foreground">{hint}</span> : null}
                        </td>
                        <td className="max-w-[240px] py-2 pr-3 text-xs text-muted-foreground">{row.note}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </div>
      {confirmDialog}
    </AppModal>
  );
}
