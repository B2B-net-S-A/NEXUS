"use client";

// Części skrzynki zgód (0483) używane w „Ludzie → Akceptacje”: wiersz listy,
// szczegół z liczbami „NEXUS sprawdził”, okno decyzji z linku maila i lista
// zgód już rozstrzygniętych („Zdecydowane”). Od 22.10.2026 zgody nie mają
// osobnej skrzynki — stoją w jednej liście z nieobecnościami (`ApprovalsScreen`).

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, ExternalLink } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useApprovalDetail,
  useApprovalList,
  type ApprovalContext,
  type ApprovalRequestRow,
} from "@/lib/api/hr-approvals";
import { CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { formatIsoDatePl, formatMomentPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import {
  STATUS_TONE,
  afterDecision,
  approveLabel,
  canChangeAmount,
  moneyPl,
  payoutLine,
  stageLine,
} from "./approvals-format";
import { DecisionDialog, type DecisionMode } from "./DecisionDialog";
import { KindIcon } from "./KindIcon";

const LABEL = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

/** Wiersz zgody w liście „Akceptacji”. */
export function ConsentInboxRow({
  row,
  active,
  onSelect,
}: {
  row: ApprovalRequestRow;
  active: boolean;
  onSelect: () => void;
}) {
  // Premia: na pierwszym planie osoba (rodzaj w drugiej linii) — w wąskiej
  // liście przy 1280 px „Premia poza umową — …” ucinało nazwisko.
  const subject = row.kind === "bonus" ? (row.beneficiary_name ?? "Osoba") : row.title;
  return (
    <li>
      <button
        type="button"
        aria-current={active ? "true" : undefined}
        onClick={onSelect}
        className={cn(
          "flex w-full items-start gap-2.5 border-t border-border/60 px-3.5 py-2.5 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
          active && "bg-primary/5 shadow-[inset_3px_0_0_hsl(var(--primary))]",
        )}
      >
        <KindIcon kind={row.kind} />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-semibold text-foreground">{subject}</span>
          <span className="block truncate text-[13px] text-muted-foreground">
            {row.kind_label} · {row.requester_name ?? "—"}
          </span>
        </span>
        <span className="shrink-0 text-right text-sm font-semibold tabular-nums text-foreground">
          {moneyPl(row.amount, row.currency)}
          {row.recurrence !== "once" ? (
            <span className="block text-xs font-normal text-muted-foreground">
              {row.recurrence === "monthly" ? "/ mies." : "/ rok"}
            </span>
          ) : null}
        </span>
      </button>
    </li>
  );
}

function ContextTiles({ row, context }: { row: ApprovalRequestRow; context: ApprovalContext }) {
  const tiles: { label: string; value: string; hint?: string }[] = [
    {
      label: `${row.kind_label} · ten miesiąc`,
      value: moneyPl(context.kind_month.amount),
      hint: `${context.kind_month.count} zatwierdzonych`,
    },
    {
      label: `${row.kind_label} · ten rok`,
      value: moneyPl(context.kind_year.amount),
      hint: `${context.kind_year.count} zatwierdzonych`,
    },
    {
      label: "Wszystkie zgody · ten miesiąc",
      value: moneyPl(context.all_month.amount),
      hint: `${context.all_month.count} zatwierdzonych`,
    },
  ];
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
      {tiles.map((tile) => (
        <div key={tile.label} className="rounded-lg bg-muted/50 px-3 py-2.5">
          <p className="text-xs text-muted-foreground">{tile.label}</p>
          <p className="text-base font-semibold tabular-nums text-foreground">{tile.value}</p>
          {tile.hint ? <p className="text-xs text-muted-foreground">{tile.hint}</p> : null}
        </div>
      ))}
    </div>
  );
}

function BonusFacts({ context }: { context: ApprovalContext }) {
  const year = context.beneficiary_year;
  if (!year) return null;
  const sameMonth = Number(year.same_month_automatic) > 0;
  return (
    <ul className="space-y-1.5 text-sm" aria-label="NEXUS sprawdził">
      <li className="flex gap-2">
        <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
        <span>
          Wynagrodzenie dodatkowe tej osoby w tym roku: z umowy i reguł {moneyPl(year.automatic)} ·
          ze zgód {moneyPl(year.outside_contract)} · inne ręczne {moneyPl(year.manual)}
        </span>
      </li>
      {sameMonth ? (
        <li className="flex gap-2 text-warning-muted-foreground">
          <span aria-hidden className="mt-0.5 font-bold">
            !
          </span>
          <span>
            W tym samym miesiącu wypłaty jest wynagrodzenie z reguł umowy ({moneyPl(year.same_month_automatic)})
            — sprawdź, czy to nie dubel.
          </span>
        </li>
      ) : null}
    </ul>
  );
}

/** Szczegół zgody z liczbami „NEXUS sprawdził” i przyciskami decyzji. */
export function ConsentDetail({
  row,
  onDecide,
}: {
  row: ApprovalRequestRow;
  onDecide: (mode: DecisionMode) => void;
}) {
  const detail = useApprovalDetail(row.id);
  const full = detail.data ?? row;
  const payout = payoutLine(full);
  return (
    <section
      aria-label={`Zgoda: ${full.title}`}
      className="min-w-0 flex-[999_1_480px] space-y-4 p-4 md:p-5"
    >
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-muted px-2 py-px text-xs font-medium text-foreground">
            {full.kind_label}
          </span>
          {full.needed_by ? (
            <span className="rounded-full bg-warning-muted px-2 py-px text-xs font-medium text-warning-muted-foreground">
              potrzebne do {formatIsoDatePl(full.needed_by)}
            </span>
          ) : null}
        </div>
        <h2 className="text-lg font-semibold text-foreground">
          {full.kind === "bonus" ? `${full.beneficiary_name ?? "Osoba"} — ` : ""}
          {full.amount_text}
        </h2>
        <p className="text-sm text-muted-foreground">
          {full.title} · prosi {full.requester_name ?? "—"} · {formatMomentPl(full.submitted_at)}
        </p>
        <p className="text-sm text-muted-foreground">{stageLine(full)}</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <p className={LABEL}>Po co — słowami autora</p>
          <p className="mt-1 whitespace-pre-line text-sm text-foreground">{full.purpose}</p>
          {full.link_url ? (
            <a
              href={full.link_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-flex items-center gap-1 text-sm text-primary hover:underline"
            >
              Oferta / cennik <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            </a>
          ) : null}
        </div>
        <div className="space-y-2">
          {payout ? (
            <p className="text-sm">
              <span className="text-muted-foreground">Wypłata z listą: </span>
              <span className="font-medium text-foreground">{payout}</span>
            </p>
          ) : null}
          {full.contract_basis ? (
            <p className="text-sm">
              <span className="text-muted-foreground">Podstawa w umowie: </span>
              <span className="font-medium text-foreground">{full.contract_basis}</span>
            </p>
          ) : null}
          {full.endorsed_by_name ? (
            <p className="text-sm">
              <span className="text-muted-foreground">Poparł(a): </span>
              <span className="font-medium text-foreground">{full.endorsed_by_name}</span>
              {full.endorse_note ? ` — „${full.endorse_note}”` : null}
            </p>
          ) : null}
          {full.context ? <BonusFacts context={full.context} /> : null}
        </div>
      </div>

      {full.context ? <ContextTiles row={full} context={full.context} /> : null}
      {detail.isError ? (
        <p className="text-xs text-muted-foreground">Nie udało się wczytać liczb obok decyzji.</p>
      ) : null}

      <p className="border-t border-border/60 pt-3 text-sm text-foreground">
        <span className="font-semibold">{afterDecision(full).label}: </span>
        {afterDecision(full).text}
      </p>

      {full.can_decide ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => onDecide("approve")}>
            <Check className="h-4 w-4" aria-hidden />
            {approveLabel(full)}
          </Button>
          {canChangeAmount(full) ? (
            <Button variant="outline" onClick={() => onDecide("approve_amount")}>
              Zatwierdź inną kwotę…
            </Button>
          ) : null}
          <Button variant="outline" onClick={() => onDecide("return")}>
            Dopytaj
          </Button>
          <Button
            variant="ghost"
            className="ml-auto text-destructive"
            onClick={() => onDecide("reject")}
          >
            Odrzuć…
          </Button>
        </div>
      ) : null}
    </section>
  );
}


/** Zdanie pod listą, gdy widać zgody: premie z umowy liczą się same. */
export const CONSENT_RULES_NOTE =
  "Wynagrodzenie z reguł umowy (placementy, ligi, reguły Płac) tu nie trafia — liczy się samo.";

/**
 * Okno decyzji zgody — z przycisku w szczególe albo z linku maila
 * (`?request=…&decide=approve|reject`): raz po wczytaniu skrzynki i tylko,
 * gdy zgoda nadal czeka na tę osobę.
 */
export function useConsentDecision({
  rows,
  isSuccess,
  linkedId,
  wanted,
}: {
  rows: readonly ApprovalRequestRow[] | undefined;
  isSuccess: boolean;
  linkedId: number | null;
  wanted: string | null;
}): { open: (row: ApprovalRequestRow, mode: DecisionMode) => void; dialog: ReactNode } {
  const [decision, setDecision] = useState<{
    row: ApprovalRequestRow;
    mode: DecisionMode;
  } | null>(null);
  const openedFromLink = useRef(false);
  useEffect(() => {
    if (openedFromLink.current || !isSuccess) return;
    openedFromLink.current = true;
    const row = (rows ?? []).find((item) => item.id === linkedId);
    if (row && row.can_decide && (wanted === "approve" || wanted === "reject")) {
      setDecision({ row, mode: wanted });
    }
  }, [isSuccess, rows, linkedId, wanted]);
  return {
    open: (row, mode) => setDecision({ row, mode }),
    dialog: (
      <DecisionDialog
        row={decision?.row ?? null}
        mode={decision?.mode ?? null}
        onClose={() => setDecision(null)}
      />
    ),
  };
}

/** „Zdecydowane”: zgody, o których czytający zdecydował albo które poparł (`scope=decided`). */
export function DecidedConsents({ enabled = true }: { enabled?: boolean }) {
  const decided = useApprovalList("decided", enabled);
  const rows = decided.data ?? [];
  const state = resolveViewState({
    isLoading: decided.isLoading,
    isError: decided.isError,
    error: decided.error,
    isSuccess: decided.isSuccess,
    isEmpty: rows.length === 0,
  });
  return (
    <section aria-labelledby="decided-consents-title" className="space-y-2">
      <h2 id="decided-consents-title" className="text-sm font-semibold text-foreground">
        Zgody
      </h2>
      {state === "loading" ? (
        <p className="py-4 text-sm text-muted-foreground">Wczytywanie zgód…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => decided.refetch()} />
      ) : state === "empty" ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          Nie decydowałeś jeszcze o żadnej zgodzie.
        </p>
      ) : (
        <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
          <Table density="compact" className="min-w-[760px]" aria-label="Zgody — zdecydowane">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Zgoda</TableHead>
                <TableHead className={CALM_HEAD}>Kto prosi</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Kwota</TableHead>
                <TableHead className={CALM_HEAD}>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id} className={`${CALM_ROW} h-[48px]`}>
                  <TableCell>
                    <span className="block font-medium text-foreground">
                      {row.kind === "bonus" ? (row.beneficiary_name ?? "Osoba") : row.title}
                    </span>
                    <span className="block text-xs text-muted-foreground">{row.kind_label}</span>
                  </TableCell>
                  <TableCell>{row.requester_name ?? "—"}</TableCell>
                  <TableCell className="whitespace-nowrap text-right tabular-nums">
                    {moneyPl(row.decided_amount ?? row.amount, row.currency)}
                  </TableCell>
                  <TableCell>
                    <StatusDot
                      tone={STATUS_TONE[row.status]}
                      note={[
                        row.decided_by_name,
                        row.decided_at ? formatMomentPl(row.decided_at) : null,
                      ]
                        .filter(Boolean)
                        .join(" · ") || undefined}
                    >
                      {row.status_label}
                    </StatusDot>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}
