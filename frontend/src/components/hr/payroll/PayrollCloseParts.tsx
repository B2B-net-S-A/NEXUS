"use client";

import { useState } from "react";
import { Check, MoreHorizontal, Plus, Upload } from "lucide-react";

import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { apiErrorMessage } from "@/lib/api-error";
import { useApproveBonuses, type BonusRow, type PayrollPerson } from "@/lib/api/hr-payroll";
import { formatDayMonthPl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

import {
  batchSelectable,
  bonusDecision,
  bonusTitle,
  payoutBreakdown,
  progressPercent,
  selectionSummary,
  type CloseStep,
  type CloseStepState,
} from "./payroll-format";

const SECTION_TITLE = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

const STEP_NUMBER: Record<CloseStepState, string> = {
  done: "bg-success-muted text-success-muted-foreground",
  current: "bg-primary text-primary-foreground",
  warn: "bg-warning-muted text-warning-muted-foreground",
  todo: "bg-muted text-muted-foreground",
};

/** Stepper zamknięcia: widać, który krok blokuje „Zamknij miesiąc”. */
export function CloseStepper({ steps }: { steps: readonly CloseStep[] }) {
  return (
    <ol
      aria-label="Kroki zamknięcia miesiąca"
      className="grid overflow-hidden rounded-xl border border-border bg-card sm:grid-cols-2 xl:grid-cols-4"
    >
      {steps.map((step, index) => (
        <li
          key={step.key}
          aria-current={step.state === "current" ? "step" : undefined}
          className={cn(
            "relative flex min-w-0 items-start gap-2.5 border-border px-4 py-3 [&:not(:last-child)]:border-b xl:[&:not(:last-child)]:border-b-0 xl:[&:not(:last-child)]:border-r",
            step.state === "current" && "bg-primary/5",
          )}
        >
          {step.state === "current" ? (
            <span aria-hidden className="absolute inset-x-0 bottom-0 h-[3px] bg-primary" />
          ) : null}
          <span
            className={cn(
              "flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-bold",
              STEP_NUMBER[step.state],
            )}
            aria-hidden
          >
            {step.state === "done" ? <Check className="size-3.5" /> : index + 1}
          </span>
          <div className="min-w-0">
            <p className={cn("text-sm font-semibold", step.state === "current" ? "text-primary" : "text-foreground")}>
              {step.label}
              <span className="sr-only">
                {step.state === "done"
                  ? " — zrobione"
                  : step.state === "warn"
                    ? " — do sprawdzenia"
                    : step.state === "current"
                      ? " — teraz"
                      : ""}
              </span>
            </p>
            <p className="text-xs text-muted-foreground">{step.detail}</p>
            {step.progress !== undefined && step.state !== "done" ? (
              <div className="mt-1.5 h-1 w-32 overflow-hidden rounded-full bg-muted" aria-hidden>
                <div className="h-full bg-success" style={{ width: `${step.progress}%` }} />
              </div>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** „Razem do wypłaty”: godziny i premie (pasek) oraz per forma współpracy. */
export function PayoutCard({ people }: { people: readonly PayrollPerson[] }) {
  const { currencies, forms } = payoutBreakdown(people);
  const main = currencies[0];
  return (
    <section aria-label="Razem do wypłaty" className="flex flex-col gap-2.5 rounded-xl border border-border bg-card p-4">
      <h2 className={SECTION_TITLE}>Razem do wypłaty</h2>
      {!main ? (
        <p className="text-sm text-muted-foreground">Jeszcze nic — liczą się zaakceptowane godziny i przyznane premie.</p>
      ) : (
        <>
          <p className="text-2xl font-bold tabular-nums text-foreground">{formatMoney(main.total, main.currency)}</p>
          {main.total > 0 ? (
            <div
              role="img"
              aria-label={`Za godziny ${formatMoney(main.hours, main.currency)}, premie ${formatMoney(main.bonuses, main.currency)}`}
              className="flex h-2.5 overflow-hidden rounded-full bg-muted"
            >
              <span className="h-full bg-primary" style={{ width: `${(main.hours / main.total) * 100}%` }} />
              <span className="h-full bg-warning" style={{ width: `${(main.bonuses / main.total) * 100}%` }} />
            </div>
          ) : null}
          <p className="flex flex-wrap justify-between gap-x-3 text-sm">
            <span>
              <span className="mr-1 inline-block size-2 rounded-sm bg-primary" aria-hidden />
              za godziny {formatMoney(main.hours, main.currency)}
            </span>
            <span>
              <span className="mr-1 inline-block size-2 rounded-sm bg-warning" aria-hidden />
              premie {formatMoney(main.bonuses, main.currency)}
            </span>
          </p>
          {currencies.slice(1).map((other) => (
            <p key={other.currency} className="text-sm text-muted-foreground">
              + {formatMoney(other.total, other.currency)} (godziny {formatMoney(other.hours, other.currency)}, premie{" "}
              {formatMoney(other.bonuses, other.currency)})
            </p>
          ))}
          <ul className="space-y-1 border-t border-border pt-2 text-sm">
            {forms.map((form) => (
              <li key={form.form} className="flex justify-between gap-2">
                <span className="text-muted-foreground">
                  {form.label} · {form.people} os.
                </span>
                <span className="tabular-nums text-foreground">
                  {Object.entries(form.totals)
                    .map(([currency, value]) => formatMoney(value, currency))
                    .join(" · ")}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

interface DecisionPanelProps {
  rows: BonusRow[];
  meId: number | undefined;
  /** Miesiąc otwarty — zamknięty nie ma akcji. */
  open: boolean;
  canCreate: boolean;
  onCreate: () => void;
  /** Płace: „Wczytaj arkusz” — rozliczenie miesiąca z pliku Delivery. */
  onImport?: () => void;
  onApprove: (row: BonusRow) => void;
  onEdit: (row: BonusRow) => void;
  onCancel: (row: BonusRow) => void;
  approving: boolean;
}

/**
 * „Premie do decyzji” dla Płac: zaznaczanie i „Zatwierdź zaznaczone” z sumą
 * (jedna trasa, wszystko albo nic); pojedyncze decyzje w menu „⋯”.
 */
export function DecisionPanel({
  rows,
  meId,
  open,
  canCreate,
  onCreate,
  onImport,
  onApprove,
  onEdit,
  onCancel,
  approving,
}: DecisionPanelProps) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const batch = useApproveBonuses();
  const selectable = open ? rows.filter((row) => batchSelectable(row, meId)) : [];
  // Domyślnie zaznaczone wszystko, co da się zatwierdzić; odznaczone pamiętamy.
  const [unchecked, setUnchecked] = useState<ReadonlySet<number>>(new Set());
  const selected = new Set(selectable.filter((row) => !unchecked.has(row.id)).map((row) => row.id));
  const summary = selectionSummary(rows, selected);
  const allChecked = selectable.length > 0 && selected.size === selectable.length;

  const toggle = (id: number, value: boolean) =>
    setUnchecked((prev) => {
      const next = new Set(prev);
      if (value) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleAll = (value: boolean) =>
    setUnchecked(value ? new Set() : new Set(selectable.map((row) => row.id)));

  const approveSelected = async () => {
    const ok = await askConfirm({
      title: summary.count === 1 ? "Zatwierdzić premię?" : `Zatwierdzić ${summary.count} premie?`,
      description: `Razem ${summary.label}. Każda osoba dostanie powiadomienie o premii. Jeśli któraś premia nie może wejść, nie wejdzie żadna.`,
      confirmLabel: "Zatwierdź",
      cancelLabel: "Wróć",
    });
    if (!ok) return;
    batch.mutate([...selected], {
      onSuccess: (result) => {
        setUnchecked(new Set());
        showToast(
          result.approved === 1 ? "Premia zatwierdzona" : `Zatwierdzono premie: ${result.approved}`,
          "success",
        );
      },
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zatwierdzić premii."), "error"),
    });
  };

  return (
    <section aria-label="Premie do decyzji" className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex items-center justify-between gap-2 px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          Premie do decyzji
          <span className="rounded-full bg-info-muted px-2 text-xs font-medium text-info-muted-foreground">
            {rows.length}
          </span>
        </h2>
        <div className="flex items-center gap-1">
          {onImport ? (
            <Button size="sm" variant="ghost" onClick={onImport}>
              <Upload className="h-4 w-4" aria-hidden />
              Wczytaj arkusz
            </Button>
          ) : null}
          {canCreate ? (
            <Button size="sm" variant="ghost" onClick={onCreate}>
              <Plus className="h-4 w-4" aria-hidden />
              Nowa premia
            </Button>
          ) : null}
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="border-t border-border px-4 py-3 text-sm text-muted-foreground">
          Nic nie czeka na decyzję.
        </p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead>
              <tr className="border-t border-border bg-muted/40 text-left text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
                <th className="w-10 py-2 pl-4">
                  {selectable.length > 0 ? (
                    <Checkbox
                      aria-label="Zaznacz wszystkie"
                      checked={allChecked ? true : selected.size > 0 ? "indeterminate" : false}
                      onCheckedChange={(value) => toggleAll(value === true)}
                    />
                  ) : null}
                </th>
                <th className="py-2 pr-3 font-semibold">Za co</th>
                <th className="py-2 pr-3 font-semibold">Osoba</th>
                <th className="py-2 pr-3 text-right font-semibold">Kwota</th>
                <th className="w-12 py-2 pr-4">
                  <span className="sr-only">Akcje</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const can = selectable.some((item) => item.id === row.id);
                const decision = bonusDecision(row, meId);
                const mine = row.recipient_user_id === meId;
                return (
                  <tr key={row.id} className="border-t border-border">
                    <td className="py-2 pl-4 align-middle">
                      {can ? (
                        <Checkbox
                          aria-label={`Zaznacz: ${bonusTitle(row)} · ${row.recipient_name ?? ""}`}
                          checked={selected.has(row.id)}
                          onCheckedChange={(value) => toggle(row.id, value === true)}
                        />
                      ) : null}
                    </td>
                    <td className="max-w-[320px] py-2 pr-3">
                      <span className="block truncate font-medium text-foreground" title={bonusTitle(row)}>
                        {bonusTitle(row)}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {row.category_label}
                        {row.eligible_on ? ` · termin ${formatDayMonthPl(row.eligible_on)}` : ""}
                        {row.edited ? " · kwota poprawiona" : ""}
                        {!can && open && !mine && row.can_approve === false ? " · zatwierdzi inna osoba z Płac" : ""}
                      </span>
                    </td>
                    <td className="whitespace-nowrap py-2 pr-3 text-foreground">{row.recipient_name ?? "—"}</td>
                    <td className="whitespace-nowrap py-2 pr-3 text-right font-semibold tabular-nums text-foreground">
                      {formatMoney(row.amount, row.currency)}
                    </td>
                    <td className="py-2 pr-4 text-right">
                      {open && !mine ? (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button size="icon" variant="ghost" className="h-7 w-7" aria-label={`Decyzja: ${bonusTitle(row)}`}>
                              <MoreHorizontal className="h-4 w-4" aria-hidden />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {decision.approve ? (
                              <DropdownMenuItem disabled={approving} onSelect={() => onApprove(row)}>
                                Zatwierdź tylko tę
                              </DropdownMenuItem>
                            ) : null}
                            <DropdownMenuItem onSelect={() => onEdit(row)}>Zmień</DropdownMenuItem>
                            <DropdownMenuItem onSelect={() => onCancel(row)}>{decision.rejectLabel}</DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {selectable.length > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border bg-primary/5 px-4 py-2.5">
          <span className="text-sm text-foreground">
            Zaznaczono <strong>{summary.count}</strong>
            {summary.count > 0 ? (
              <>
                {" "}
                · <strong className="tabular-nums">{summary.label}</strong>
              </>
            ) : null}
          </span>
          <Button size="sm" onClick={() => void approveSelected()} disabled={summary.count === 0 || batch.isPending}>
            {batch.isPending ? "Zatwierdzanie…" : "Zatwierdź zaznaczone"}
          </Button>
        </div>
      ) : null}
      {confirmDialog}
    </section>
  );
}

/** Placementy „liczą się”: paski dni do terminu premii. */
export function PlacementsStrip({
  rows,
  assignedCount,
  assignedOpen,
  onToggleAssigned,
}: {
  rows: readonly BonusRow[];
  assignedCount: number;
  assignedOpen: boolean;
  onToggleAssigned: () => void;
}) {
  return (
    <section aria-label="Placementy w drodze" className="space-y-2.5 rounded-xl border border-border bg-card px-4 py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">Placementy w drodze · premie liczą się</h2>
        <button
          type="button"
          onClick={onToggleAssigned}
          aria-expanded={assignedOpen}
          className="text-sm font-medium text-primary underline-offset-2 hover:underline"
        >
          Przyznane w tym miesiącu ({assignedCount}) {assignedOpen ? "‹" : "›"}
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Żaden placement nie czeka na termin premii.</p>
      ) : (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {rows.map((row) => {
            const percent = progressPercent(row.business_days_elapsed, row.business_days_required);
            return (
              <li key={row.id} className="rounded-lg bg-muted/50 px-3 py-2.5">
                <div className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="min-w-0 truncate" title={bonusTitle(row)}>
                    <strong className="text-foreground">{row.recipient_name ?? "—"}</strong>
                    <span className="text-muted-foreground"> · {bonusTitle(row)}</span>
                  </span>
                  <strong className="shrink-0 tabular-nums text-foreground">
                    {formatMoney(row.amount, row.currency)}
                  </strong>
                </div>
                <div
                  role="progressbar"
                  aria-label={`Dni do terminu premii: ${row.recipient_name ?? ""}`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={percent}
                  className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-border"
                >
                  <div className="h-full bg-primary" style={{ width: `${percent}%` }} />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {row.business_days_required
                    ? `${row.business_days_elapsed ?? 0} z ${row.business_days_required} dni roboczych`
                    : "liczy się"}
                  {row.eligible_on ? ` · termin ${formatDayMonthPl(row.eligible_on)}` : ""}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
