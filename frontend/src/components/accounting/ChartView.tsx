"use client";

import { useMemo, useState } from "react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useChart,
  useCreateAccount,
  useUpdateAccount,
  type AccountInput,
  type ChartAccount,
  type LedgerConfig,
} from "@/lib/api/accounting";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { useAccounting } from "./AccountingShell";

const CONTROL = "h-8 w-full min-w-0 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const LABEL = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";
const KIND_LABELS: Record<string, string> = {
  cost: "koszt",
  vat: "VAT",
  settlement: "rozrachunek",
  revenue: "przychód",
  other: "inne",
};

/**
 * Plan kont księgi: tabela kont z dekretu E2 rozszerzona o syntetykę, typ
 * i słownik analityki. Numeru się nie zmienia (nowy numer = nowe konto),
 * kont się nie kasuje — wyłącza się je.
 */
export function ChartView() {
  const { config } = useAccounting();
  const chart = useChart();
  const [needle, setNeedle] = useState("");
  const [cls, setCls] = useState("");
  const [editing, setEditing] = useState<ChartAccount | "new" | null>(null);
  const rows = useMemo(() => {
    const text = needle.trim().toLowerCase();
    return (chart.data ?? []).filter(
      (row) =>
        (!cls || row.class === cls) &&
        (!text || row.number.toLowerCase().includes(text) || row.name.toLowerCase().includes(text)),
    );
  }, [chart.data, needle, cls]);
  const classes = useMemo(
    () => [...new Set((chart.data ?? []).map((row) => row.class))].sort(),
    [chart.data],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Zespół kont" value={cls} onChange={(e) => setCls(e.target.value)} className={cn(CONTROL, "w-auto")}>
          <option value="">Wszystkie zespoły</option>
          {classes.map((item) => (
            <option key={item} value={item}>
              Zespół {item}
            </option>
          ))}
        </select>
        <input
          type="search"
          value={needle}
          onChange={(e) => setNeedle(e.target.value)}
          placeholder="Numer albo nazwa konta…"
          aria-label="Szukaj konta"
          className={cn(CONTROL, "w-56")}
        />
        <span className="text-[12px] text-muted-foreground">
          Ten sam plan kont co dekret faktur w Finansach. Pełny plan przyjdzie importem z Symfonii FK.
        </span>
        <Button size="sm" className="ml-auto" onClick={() => setEditing("new")}>
          Dodaj konto
        </Button>
      </div>
      {chart.isLoading ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie planu kont…</p>
      ) : chart.isError ? (
        <QueryStateNotice state="error" onRetry={() => chart.refetch()} />
      ) : chart.isSuccess && rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          Nie ma kont dla wybranych filtrów.
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card">
          <table className="w-full table-fixed text-sm">
            <thead>
              <tr className="border-b border-border/70">
                <th className={cn(CALM_HEAD, "w-[14%] px-3 py-2 text-left")}>Konto</th>
                <th className={cn(CALM_HEAD, "px-2 py-2 text-left")}>Nazwa</th>
                <th className={cn(CALM_HEAD, "w-[17%] px-2 py-2 text-left")}>Typ · rodzaj</th>
                <th className={cn(CALM_HEAD, "w-[15%] px-2 py-2 text-left")}>Analityka</th>
                <th className={cn(CALM_HEAD, "w-[11%] px-2 py-2 text-right")}>Zapisy</th>
                <th className={cn(CALM_HEAD, "w-[13%] px-3 py-2 text-left")}>Stan</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.id}
                  onClick={() => setEditing(row)}
                  className={cn(CALM_ROW, "cursor-pointer align-top hover:bg-muted/40", !row.active && "text-muted-foreground")}
                >
                  <td className="px-3 py-1.5 font-mono text-[12.5px] font-medium text-primary">{row.number}</td>
                  <td className="min-w-0 px-2 py-1.5">
                    <span className="block truncate">{row.name}</span>
                    {row.parent_number ? <span className={CALM_SUBLINE}>pod {row.parent_number}</span> : null}
                  </td>
                  <td className="px-2 py-1.5 text-[12.5px]">
                    {row.account_type_label ?? <span className={CALM_EMPTY}>—</span>}
                    <span className={CALM_SUBLINE}>{KIND_LABELS[row.kind] ?? row.kind}</span>
                  </td>
                  <td className="px-2 py-1.5 text-[12.5px]">
                    {row.dictionary_label ? `słownik: ${row.dictionary_label}` : row.has_children ? "konta pod spodem" : <span className={CALM_EMPTY}>—</span>}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{row.used || <span className={CALM_EMPTY}>—</span>}</td>
                  <td className="px-3 py-1.5">
                    <StatusDot
                      tone={!row.active ? "neutral" : row.postable ? "success" : "info"}
                      note={row.in_rules ? `w regułach dekretu: ${row.in_rules}` : undefined}
                    >
                      {!row.active ? "Wyłączone" : row.postable ? "Księgowalne" : "Syntetyczne"}
                    </StatusDot>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing ? (
        <AccountDialog
          key={editing === "new" ? "new" : editing.id}
          account={editing === "new" ? null : editing}
          config={config}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </div>
  );
}

function AccountDialog({
  account,
  config,
  onClose,
}: {
  account: ChartAccount | null;
  config: LedgerConfig;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const create = useCreateAccount();
  const update = useUpdateAccount();
  const [form, setForm] = useState<AccountInput>({
    number: account?.number ?? "",
    name: account?.name ?? "",
    kind: account?.kind ?? "other",
    account_type: account?.account_type ?? "",
    parent_number: account?.parent_number ?? "",
    dictionary: account?.dictionary ?? "",
    report_line: account?.report_line ?? "",
    active: account?.active ?? true,
  });
  const set = (changes: Partial<AccountInput>) => setForm((current) => ({ ...current, ...changes }));
  const save = () => {
    const body: AccountInput = {
      name: form.name,
      kind: form.kind || null,
      account_type: form.account_type || null,
      parent_number: form.parent_number || null,
      dictionary: form.dictionary || null,
      report_line: form.report_line || null,
    };
    const done = {
      onSuccess: () => {
        showToast(account ? "Zapisano konto." : "Dodano konto do planu.");
        onClose();
      },
      onError: (error: unknown) => showToast(apiErrorMessage(error, "Nie udało się zapisać konta."), "error"),
    };
    if (account) update.mutate({ id: account.id, changes: { ...body, active: form.active } }, done);
    else create.mutate({ ...body, number: form.number }, done);
  };
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{account ? `Konto ${account.number}` : "Nowe konto"}</DialogTitle>
        </DialogHeader>
        <DialogBody className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1">
            <span className={LABEL}>Numer</span>
            <input
              className={cn(CONTROL, "font-mono")}
              value={form.number ?? ""}
              disabled={Boolean(account)}
              placeholder="np. 402-215"
              onChange={(e) => set({ number: e.target.value })}
            />
          </label>
          <label className="space-y-1">
            <span className={LABEL}>Konto nadrzędne</span>
            <input
              className={cn(CONTROL, "font-mono")}
              value={form.parent_number ?? ""}
              placeholder="np. 402"
              onChange={(e) => set({ parent_number: e.target.value })}
            />
          </label>
          <label className="space-y-1 sm:col-span-2">
            <span className={LABEL}>Nazwa</span>
            <input className={CONTROL} value={form.name ?? ""} maxLength={255} onChange={(e) => set({ name: e.target.value })} />
          </label>
          <label className="space-y-1">
            <span className={LABEL}>Typ konta</span>
            <select className={CONTROL} value={form.account_type ?? ""} onChange={(e) => set({ account_type: e.target.value })}>
              <option value="">—</option>
              {config.account_types.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className={LABEL}>Rodzaj w dekrecie faktur</span>
            <select
              className={CONTROL}
              value={form.kind ?? "other"}
              disabled={Boolean(account?.in_rules)}
              title={account?.in_rules ? "Konto jest w regule dekretu — rodzaj zmienisz po zmianie reguły" : undefined}
              onChange={(e) => set({ kind: e.target.value })}
            >
              {config.account_kinds.map((kind) => (
                <option key={kind} value={kind}>
                  {KIND_LABELS[kind] ?? kind}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className={LABEL}>Słownik analityki</span>
            <select className={CONTROL} value={form.dictionary ?? ""} onChange={(e) => set({ dictionary: e.target.value })}>
              <option value="">brak</option>
              {config.dictionaries.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className={LABEL}>Pozycja sprawozdania</span>
            <input
              className={CONTROL}
              value={form.report_line ?? ""}
              maxLength={32}
              placeholder="np. RZiS B.III"
              onChange={(e) => set({ report_line: e.target.value })}
            />
          </label>
          {account ? (
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" checked={form.active ?? true} onChange={(e) => set({ active: e.target.checked })} />
              Konto aktywne (wyłączonego nie użyjesz w nowym dekrecie)
            </label>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button loading={create.isPending || update.isPending} onClick={save}>
            {account ? "Zapisz" : "Dodaj konto"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
