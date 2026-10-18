"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight } from "lucide-react";

import { StatusDot } from "@/components/ds/StatusDot";
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
  EMPLOYMENT_STATUS_LABELS,
  useAccountMismatches,
  useAlignWithAccounts,
  type AccountMismatch,
} from "@/lib/api/hr";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";

import { STATUS_TONE } from "./hr-format";

const KIND_LABELS: Record<AccountMismatch["kind"], string> = {
  exit: "Konto wyłączone",
  return: "Konto włączone",
  missing: "Konto bez kartoteki",
};

/** Co się stanie po „Wyrównaj wg konta” — jedno zdanie na wiersz. */
export function mismatchOutcome(item: AccountMismatch): string {
  if (item.kind === "missing") {
    return "Nowa kartoteka „Aktywny” — forma i przełożony do uzupełnienia";
  }
  const status = EMPLOYMENT_STATUS_LABELS[item.proposed_status];
  if (item.kind === "exit" && item.proposed_last_working_day) {
    return `${status}, ostatni dzień ${formatIsoDatePl(item.proposed_last_working_day)}`;
  }
  return status;
}

/**
 * Kartoteka a konto NEXUSA (decyzja Artura 19.10.2026: „Konto decyduje + lista
 * rozjazdów”) — dla admina, Finansów i Kadr. Nowe rozjazdy nie powinny
 * powstawać (status idzie za kontem sam), lista zbiera stan sprzed zmiany
 * i to, co ominęło zwykłe ścieżki.
 */
export function AccountMismatchesPanel() {
  const mismatches = useAccountMismatches(true);
  const align = useAlignWithAccounts();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showToast } = useToast();
  const [open, setOpen] = useState(false);

  if (mismatches.isLoading) return null;
  if (mismatches.isError || !mismatches.data) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {apiErrorMessage(mismatches.error, "Nie udało się sprawdzić kartotek z kontami.")}
      </p>
    );
  }
  const { items, pending } = mismatches.data;
  if (items.length === 0 && pending.employment_type === 0 && pending.manager === 0) {
    return null;
  }

  const alignAll = async () => {
    const ok = await askConfirm({
      title: "Wyrównać kartoteki według kont?",
      description: `${countPl(items.length, "kartoteka", "kartoteki", "kartotek")} dostanie status konta NEXUSA: wyłączone konto = „Zakończył współpracę”, włączone = „Aktywny”, konto bez kartoteki = nowa kartoteka do uzupełnienia. Każda zmiana zostaje w historii kartoteki.`,
      confirmLabel: "Wyrównaj",
      cancelLabel: "Anuluj",
    });
    if (!ok) return;
    align.mutate(
      items.map((item) => item.user_id),
      {
        onSuccess: (done) =>
          showToast(
            `Wyrównano: zakończone ${done.exit}, przywrócone ${done.return}, nowe kartoteki ${done.missing}.`,
            "success",
          ),
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się wyrównać kartotek."), "error"),
      },
    );
  };

  return (
    <section
      aria-label="Kartoteki a konta NEXUSA"
      className="rounded-lg border border-warning/40 bg-warning-muted/40 px-3 py-2 text-sm"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {items.length > 0 ? (
          <button
            type="button"
            className="inline-flex items-center gap-1 font-medium text-foreground"
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? (
              <ChevronDown className="h-4 w-4" aria-hidden />
            ) : (
              <ChevronRight className="h-4 w-4" aria-hidden />
            )}
            Rozjazdy z kontami NEXUSA: {items.length}
          </button>
        ) : null}
        {pending.employment_type > 0 ? (
          <span className="text-warning-muted-foreground">
            Forma do uzupełnienia: {pending.employment_type}
          </span>
        ) : null}
        {pending.manager > 0 ? (
          <span className="text-warning-muted-foreground">
            Przełożony do uzupełnienia: {pending.manager}
          </span>
        ) : null}
        {items.length > 0 ? (
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            disabled={align.isPending}
            onClick={alignAll}
          >
            {align.isPending ? "Wyrównywanie…" : "Wyrównaj wg konta"}
          </Button>
        ) : null}
      </div>
      {open && items.length > 0 ? (
        <div className="mt-2 overflow-x-auto rounded-md border border-border bg-card">
          <Table density="compact" className="min-w-[720px]">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Osoba</TableHead>
                <TableHead className={CALM_HEAD}>Konto</TableHead>
                <TableHead className={CALM_HEAD}>Kartoteka teraz</TableHead>
                <TableHead className={CALM_HEAD}>Po wyrównaniu</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.user_id} className={CALM_ROW}>
                  <TableCell>
                    {item.kind === "missing" ? (
                      <span className="font-medium text-foreground">{item.name}</span>
                    ) : (
                      <Link
                        href={`/people/${item.user_id}`}
                        className="font-medium text-foreground hover:underline"
                      >
                        {item.name}
                      </Link>
                    )}
                    <span className={CALM_SUBLINE}>{item.email}</span>
                  </TableCell>
                  <TableCell>{KIND_LABELS[item.kind]}</TableCell>
                  <TableCell>
                    {item.employment_status ? (
                      <StatusDot tone={STATUS_TONE[item.employment_status]}>
                        {EMPLOYMENT_STATUS_LABELS[item.employment_status]}
                      </StatusDot>
                    ) : (
                      <span className={CALM_EMPTY}>brak kartoteki</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {mismatchOutcome(item)}
                    {item.reports > 0 ? (
                      <span className={CALM_SUBLINE}>
                        {countPl(item.reports, "osoba", "osoby", "osób")} pod sobą — przepnij w{" "}
                        <Link href="/people/structure" className="underline">
                          Strukturze
                        </Link>
                      </span>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
      {confirmDialog}
    </section>
  );
}
