"use client";

import { useEffect, useMemo, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { useImportTemplates, useTemplateSuggestions } from "@/lib/api/issued-invoices";
import { shiftMonth } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";

import { splitPeriod } from "../invoicing-format";

const BENEFIT_SHORT: Record<string, string> = {
  sport: "sport",
  medical: "medyczny",
  other: "refaktura",
};

/**
 * „Szablony z faktur z KSeF” (E6): faktury bez zamówienia z wybranego miesiąca
 * (to, co wystawił eBI24) → szablony. Domyślnie zaznaczone są faktury bez
 * szablonu; jednorazowe (np. sprzedaż sprzętu) odznacz i wystaw „Nową fakturą”.
 * Faktura do klienta, której automat nie dopasował do zamówienia, jest z zamówienia
 * („Wystaw za miesiąc”) — widać ją, ale szablonu z niej nie ma.
 */
export function ImportTemplatesDialog({ period, onClose }: { period: string; onClose: () => void }) {
  const { showToast } = useToast();
  const [source, setSource] = useState(() => shiftMonth(period, -1));
  const query = useTemplateSuggestions(source);
  const importMany = useImportTemplates();
  const rows = useMemo(() => query.data?.rows ?? [], [query.data]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSelected(
      new Set(rows.filter((row) => !row.has_template && !row.from_order).map((row) => row.ksef_number)),
    );
  }, [rows]);

  const toggle = (key: string, on: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });

  const submit = () => {
    const { year, month } = splitPeriod(source);
    importMany.mutate(
      { year, month, ksef_numbers: [...selected] },
      {
        onSuccess: (result) => {
          showToast(
            `Utworzono ${countPl(result.created.length, "szablon", "szablony", "szablonów")}`,
            "success",
          );
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się utworzyć szablonów.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title="Szablony z faktur z KSeF"
      description="Faktury sprzedaży bez zamówienia w NEXUSIE z wybranego miesiąca. Miesiąc w nazwie pozycji zamieni się na bieżący przy każdym wystawieniu."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={selected.size === 0 || importMany.isPending}>
            {importMany.isPending
              ? "Tworzenie…"
              : `Utwórz szablony${selected.size ? ` (${selected.size})` : ""}`}
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <FormField label="Faktury z miesiąca" htmlFor="import-month">
            <Input
              id="import-month"
              type="month"
              value={source}
              onChange={(event) => event.target.value && setSource(event.target.value)}
              className="w-44"
            />
          </FormField>
          {query.data ? (
            <p className="text-sm text-muted-foreground">
              {countPl(query.data.counts.all, "faktura", "faktury", "faktur")} bez zamówienia, w tym{" "}
              {countPl(query.data.counts.benefit, "refaktura benefitu", "refaktury benefitów", "refaktur benefitów")}
              {query.data.counts.from_order
                ? `; ${query.data.counts.from_order} z zamówień idzie przez „Wystaw za miesiąc”`
                : ""}
            </p>
          ) : null}
        </div>
        {query.isLoading ? (
          <p className="py-6 text-sm text-muted-foreground">Wczytywanie faktur…</p>
        ) : query.isError ? (
          <QueryStateNotice state="error" onRetry={() => query.refetch()} />
        ) : query.isSuccess && rows.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
            W tym miesiącu nie ma faktur sprzedaży bez zamówienia.
          </p>
        ) : (
          <div className="max-h-[55dvh] overflow-y-auto rounded-lg border border-border">
            <ul className="divide-y divide-border">
              {rows.map((row) => (
                <li key={row.ksef_number} className="flex items-start gap-3 px-3 py-2 text-sm">
                  <Checkbox
                    aria-label={`Szablon z faktury ${row.invoice_number ?? row.ksef_number}`}
                    checked={selected.has(row.ksef_number)}
                    disabled={row.has_template || row.from_order}
                    onCheckedChange={(value) => toggle(row.ksef_number, value === true)}
                    className="mt-0.5"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-foreground" title={row.buyer_name ?? ""}>
                      {row.buyer_name || row.buyer_number}
                    </p>
                    <p className="truncate text-xs text-muted-foreground" title={row.lines[0]?.name}>
                      {row.invoice_number} · {row.lines[0]?.name ?? "bez pozycji"}
                      {row.lines.length > 1 ? ` (+${row.lines.length - 1})` : ""}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-0.5">
                    <span className="tabular-nums">
                      {row.net ? formatMoney(row.net, row.currency) : "—"}
                    </span>
                    {row.has_template ? (
                      <StatusDot tone="success">ma szablon</StatusDot>
                    ) : row.from_order ? (
                      <StatusDot tone="neutral">z zamówienia</StatusDot>
                    ) : row.benefit ? (
                      <StatusDot tone="info">{BENEFIT_SHORT[row.benefit]}</StatusDot>
                    ) : row.address_missing ? (
                      <StatusDot tone="warning">brak adresu</StatusDot>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
