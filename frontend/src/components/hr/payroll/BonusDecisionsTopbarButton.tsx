"use client";

// Ikona „Premie do decyzji” w górnym pasku (decyzja Artura 30.10.2026): ten sam
// ekran dla wszystkich z uprawnieniem Płace. Licznik ze stanu, nie z dzwonków;
// przy zerze ikony nie ma, żeby nie rozpychać paska na laptopie 1280 px.

import Link from "next/link";
import { Award } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { apiErrorMessage } from "@/lib/api-error";
import { useHrConfig } from "@/lib/api/hr";
import {
  useApproveBonus,
  useBonusDecisions,
  useConfirmVoucher,
  type BonusRow,
} from "@/lib/api/hr-payroll";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

import { ymSegment } from "./payroll-format";

const PREVIEW_LIMIT = 4;

function GroupHeader({ children }: { children: React.ReactNode }) {
  return (
    <p className="border-t border-border bg-muted/40 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
      {children}
    </p>
  );
}

function BonusLine({
  row,
  action,
}: {
  row: BonusRow;
  action: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-border px-3 py-2 text-sm">
      <span className="min-w-0">
        <span className="block truncate font-medium text-foreground" title={row.description ?? undefined}>
          {row.description ?? "Premia"}
        </span>
        <span className="block truncate text-xs text-muted-foreground">
          {row.recipient_name ?? "—"}
          {row.flags?.length ? ` · ${row.flags.map((flag) => flag.label).join(", ")}` : ""}
        </span>
      </span>
      <span className="flex shrink-0 items-center gap-2">
        <strong className="tabular-nums text-foreground">{formatMoney(row.amount, row.currency)}</strong>
        {action}
      </span>
    </div>
  );
}

export function BonusDecisionsTopbarButton({ className }: { className?: string }) {
  const { showToast } = useToast();
  const user = useAuthStore((state) => state.user);
  const config = useHrConfig(Boolean(user));
  const allowed = Boolean(config.data?.me.payroll && config.data?.open_modules.payroll);
  const decisions = useBonusDecisions(allowed);
  const approve = useApproveBonus();
  const confirm = useConfirmVoucher();
  if (!allowed || !decisions.isSuccess) return null;
  const { signed, league, check, vouchers } = decisions.data;
  const total = signed.length + league.length + check.length + vouchers.length;
  if (total === 0) return null;

  const approveRow = (row: BonusRow) =>
    approve.mutate(row.id, {
      onSuccess: () => showToast("Premia zatwierdzona", "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zatwierdzić."), "error"),
    });
  const approveButton = (row: BonusRow) => (
    <Button size="sm" variant="secondary" disabled={approve.isPending} onClick={() => approveRow(row)}>
      Zatwierdź
    </Button>
  );
  const monthHref = (row: BonusRow) => `/people/payroll/${ymSegment(row.period_year, row.period_month)}`;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={`Premie do decyzji: ${countPl(total, "pozycja", "pozycje", "pozycji")}`}
          className={cn(
            "relative rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
            className,
          )}
        >
          <Award className="h-5 w-5" aria-hidden />
          <span className="absolute -right-0.5 -top-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-primary px-1 text-xs font-bold tabular-nums text-primary-foreground">
            {total > 99 ? "99+" : total}
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-[80dvh] w-[min(600px,calc(100vw-1rem))] overflow-y-auto p-0">
        <div className="flex items-center justify-between gap-2 px-3 py-2.5">
          <strong className="text-sm text-foreground">Premie do decyzji</strong>
          <Link href="/people/payroll" className="text-xs font-medium text-primary hover:underline">
            Otwórz w Płacach
          </Link>
        </div>
        {signed.length > 0 ? (
          <>
            <GroupHeader>Z podpisanych umów · {signed.length}</GroupHeader>
            {signed.slice(0, PREVIEW_LIMIT).map((row) => (
              <BonusLine key={row.id} row={row} action={approveButton(row)} />
            ))}
          </>
        ) : null}
        {league.length + vouchers.length > 0 ? (
          <>
            <GroupHeader>Liga i wyścigi · {league.length + vouchers.length}</GroupHeader>
            {league.slice(0, PREVIEW_LIMIT).map((row) => (
              <BonusLine key={row.id} row={row} action={approveButton(row)} />
            ))}
            {vouchers.slice(0, PREVIEW_LIMIT).map((voucher) => (
              <div key={voucher.id} className="flex items-center justify-between gap-3 border-t border-border px-3 py-2 text-sm">
                <span className="min-w-0">
                  <span className="block truncate font-medium text-foreground">
                    {voucher.label} {voucher.period}: {voucher.rank}. miejsce
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">{voucher.name} · voucher, bez przelewu</span>
                </span>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={confirm.isPending}
                  onClick={() =>
                    confirm.mutate(voucher.id, {
                      onSuccess: () => showToast("Voucher potwierdzony", "success"),
                      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się potwierdzić."), "error"),
                    })
                  }
                >
                  Potwierdź
                </Button>
              </div>
            ))}
          </>
        ) : null}
        {check.length > 0 ? (
          <>
            <GroupHeader>Do sprawdzenia · {check.length}</GroupHeader>
            {check.slice(0, PREVIEW_LIMIT).map((row) => (
              <BonusLine
                key={row.id}
                row={row}
                action={
                  <Link href={monthHref(row)} className="text-xs font-medium text-primary hover:underline">
                    Sprawdź
                  </Link>
                }
              />
            ))}
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
