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

/** Kartoteka „do uzupełnienia” z katalogu: kto i czego brakuje („forma i przełożony”). */
export interface PendingPerson {
  user_id: number;
  name: string;
  what: string;
}

/** Ile pozycji pokazujemy z imienia w pasku (reszta w „+N”). */
const NAMED_LIMIT = 4;

/**
 * Kartoteka a konto NEXUSA (decyzja Artura 19.10.2026: „Konto decyduje + lista
 * rozjazdów”) — dla admina, Finansów i Kadr. Nowe rozjazdy nie powinny
 * powstawać (status idzie za kontem sam), lista zbiera stan sprzed zmiany
 * i to, co ominęło zwykłe ścieżki.
 */
export function AccountMismatchesPanel({
  pendingPeople = [],
}: {
  pendingPeople?: readonly PendingPerson[];
}) {
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
  if (
    items.length === 0 &&
    pendingPeople.length === 0 &&
    pending.employment_type === 0 &&
    pending.manager === 0
  ) {
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

  const total = items.length + pendingPeople.length;
  const named = [
    ...items.map((item) => ({
      key: `m-${item.user_id}`,
      href: item.kind === "missing" ? null : `/people/${item.user_id}`,
      text: `${item.name}: ${KIND_LABELS[item.kind].toLowerCase()}${
        item.reports > 0 ? ` · ${countPl(item.reports, "osoba", "osoby", "osób")} pod sobą` : ""
      }`,
    })),
    ...pendingPeople.map((person) => ({
      key: `p-${person.user_id}`,
      href: `/people/${person.user_id}`,
      text: `${person.name}: ${person.what}`,
    })),
  ];
  const extra = named.length - NAMED_LIMIT;

  return (
    <section
      aria-label="Kartoteki a konta NEXUSA"
      className="rounded-xl border border-warning/40 bg-warning-muted/40 px-4 py-3 text-sm"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex min-w-[200px] flex-col">
          <span className="font-semibold text-warning-muted-foreground">
            Do wyrównania · {total > 0 ? total : pending.employment_type + pending.manager}
          </span>
          <span className="text-xs text-warning-muted-foreground">
            kartoteka idzie za kontem NEXUSA
          </span>
        </div>
        <ul aria-label="Do wyrównania" className="flex flex-1 flex-wrap gap-1.5">
          {named.slice(0, NAMED_LIMIT).map((entry) => (
            <li key={entry.key}>
              {entry.href ? (
                <Link
                  href={entry.href}
                  className="inline-flex rounded-full border border-warning/40 bg-card px-2 py-0.5 text-xs font-medium text-foreground hover:underline"
                >
                  {entry.text}
                </Link>
              ) : (
                <span className="inline-flex rounded-full border border-warning/40 bg-card px-2 py-0.5 text-xs font-medium text-foreground">
                  {entry.text}
                </span>
              )}
            </li>
          ))}
          {extra > 0 ? (
            <li className="px-1 py-0.5 text-xs text-warning-muted-foreground">+{extra}</li>
          ) : null}
          {pendingPeople.length === 0 && pending.employment_type > 0 ? (
            <li className="text-xs text-warning-muted-foreground">
              Forma do uzupełnienia: {pending.employment_type}
            </li>
          ) : null}
          {pendingPeople.length === 0 && pending.manager > 0 ? (
            <li className="text-xs text-warning-muted-foreground">
              Przełożony do uzupełnienia: {pending.manager}
            </li>
          ) : null}
        </ul>
        {items.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              aria-expanded={open}
              onClick={() => setOpen((value) => !value)}
            >
              {open ? (
                <ChevronDown className="h-4 w-4" aria-hidden />
              ) : (
                <ChevronRight className="h-4 w-4" aria-hidden />
              )}
              {open ? "Zwiń" : "Przejrzyj po kolei"}
            </Button>
            <Button size="sm" variant="outline" disabled={align.isPending} onClick={alignAll}>
              {align.isPending ? "Wyrównywanie…" : "Wyrównaj wg konta"}
            </Button>
          </div>
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
