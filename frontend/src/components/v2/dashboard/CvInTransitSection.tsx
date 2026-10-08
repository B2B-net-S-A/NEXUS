"use client";

/**
 * „Twoje CV w drodze” (02.10.2026) — druga strona przekazań karty.
 *
 * Rekruter po przekazaniu CV do QC miał tylko dzwonek, który znika po
 * kliknięciu. Lista stoi w panelu „Czeka na Ciebie” (kolumna) albo — gdy nic
 * nie wróciło i panel jest pusty — jako wąski pasek nad pulpitem. Każdy ma ją
 * domyślnie; „Usuń z pulpitu” zapisuje się na koncie, a przywraca ją
 * „Dodaj kafelek” (decyzja Artura 02.10.2026).
 */

import Link from "next/link";
import { useState } from "react";
import { ChevronDown, ChevronUp, MoreHorizontal, Send } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { apiErrorMessage } from "@/lib/api-error";
import { waitingFor, type CvInTransit, type CvTransitRow } from "@/lib/api/boardTasks";
import { useSetDashboardPanelHidden } from "@/lib/api/userDashboard";
import {
  CV_TRANSIT_EMPTY,
  CV_TRANSIT_HINT,
  CV_TRANSIT_RETURNED_LABEL,
  CV_TRANSIT_TITLE,
  transitAgo,
  transitIsEmpty,
  transitJobLabel,
  transitCardEdit,
  transitRemark,
  transitFixList,
  transitReturnedDetail,
  transitRowWho,
  transitSummary,
} from "@/lib/cv-in-transit";

function boardLink(row: CvTransitRow): string {
  return `/jobs/${row.job_id}?candidate=${row.candidate_id}`;
}

function RemoveMenu() {
  const { showSuccess, showError } = useToast();
  const setHidden = useSetDashboardPanelHidden();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          className="shrink-0"
          aria-label={`Menu listy ${CV_TRANSIT_TITLE}`}
        >
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem
          className="text-destructive"
          disabled={setHidden.isPending}
          onSelect={() =>
            setHidden.mutate(
              { panel: "cv_in_transit", hidden: true },
              {
                onSuccess: () =>
                  showSuccess("Usunięto z pulpitu. Przywrócisz w „Dodaj kafelek”."),
                onError: (error) =>
                  showError(apiErrorMessage(error, "Nie udało się usunąć listy z pulpitu.")),
              },
            )
          }
        >
          Usuń z pulpitu
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ReturnedRow({ row }: { row: CvTransitRow }) {
  const detail = transitReturnedDetail(row);
  const remark = transitRemark(row);
  const fixes = transitFixList(row);
  const cardEdit = transitCardEdit(row);
  const rejected = row.kind === "rejected_by_dl";
  return (
    <li className="flex flex-col gap-1 px-3 py-2">
      <div className="flex items-baseline gap-2">
        <Link href={boardLink(row)} className="min-w-0 flex-1 truncate text-sm font-medium hover:underline">
          {row.candidate_name}
        </Link>
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{transitAgo(row.since)}</span>
      </div>
      <p className="truncate text-xs text-muted-foreground">{transitJobLabel(row)}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        <span
          className={`inline-flex shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
            rejected ? "bg-destructive/10 text-destructive" : "bg-warning-muted text-warning-muted-foreground"
          }`}
        >
          {CV_TRANSIT_RETURNED_LABEL[row.kind as keyof typeof CV_TRANSIT_RETURNED_LABEL]}
        </span>
        {detail ? <span className="min-w-0 break-words text-xs">{detail}</span> : null}
      </div>
      {remark ? <p className="break-words text-xs">{remark}</p> : null}
      {fixes ? (
        <p className="break-words text-xs font-medium text-warning-muted-foreground" data-testid="cv-transit-fixes">
          {fixes}
        </p>
      ) : null}
      {cardEdit ? <p className="break-words text-xs text-muted-foreground">{cardEdit}</p> : null}
    </li>
  );
}

function InfoRow({ row }: { row: CvTransitRow }) {
  const who = transitRowWho(row);
  const remark = transitRemark(row);
  const cardEdit = transitCardEdit(row);
  return (
    <li className="flex flex-col gap-1 px-3 py-2">
      <div className="flex items-baseline gap-2">
        <Link href={boardLink(row)} className="min-w-0 flex-1 truncate text-sm font-medium hover:underline">
          {row.candidate_name}
        </Link>
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {row.kind === "sent" ? transitAgo(row.since) : waitingFor(row.since)}
        </span>
      </div>
      <p className="truncate text-xs text-muted-foreground">{transitJobLabel(row)}</p>
      {who ? <p className="truncate text-xs">{who}</p> : null}
      {remark ? <p className="break-words text-xs">{remark}</p> : null}
      {cardEdit ? <p className="break-words text-xs text-muted-foreground">{cardEdit}</p> : null}
    </li>
  );
}

function GroupHeading({ children }: { children: React.ReactNode }) {
  return <li className="bg-muted px-3 py-1.5 text-xs font-semibold text-muted-foreground">{children}</li>;
}

/** Wiersze listy: zwrócone zawsze, reszta po „Pokaż”. */
function TransitList({
  transit,
  open,
  onToggle,
}: {
  transit: CvInTransit;
  open: boolean;
  onToggle: () => void;
}) {
  const inTransit = transit.in_review_total + transit.sent_total;
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border">
      {open && transit.returned.length > 0 ? (
        <GroupHeading>Wróciło do Ciebie · {transit.returned_total}</GroupHeading>
      ) : null}
      {transit.returned.map((row) => (
        <ReturnedRow key={row.stage_id} row={row} />
      ))}
      {open && transit.in_review.length > 0 ? (
        <>
          <GroupHeading>W przeglądzie · {transit.in_review_total}</GroupHeading>
          {transit.in_review.map((row) => (
            <InfoRow key={row.stage_id} row={row} />
          ))}
        </>
      ) : null}
      {open && transit.sent.length > 0 ? (
        <>
          <GroupHeading>
            Wysłane do klienta, ostatnie {transit.sent_window_days} dni · {transit.sent_total}
          </GroupHeading>
          {transit.sent.map((row) => (
            <InfoRow key={row.stage_id} row={row} />
          ))}
        </>
      ) : null}
      {inTransit > 0 ? (
        <li>
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={open}
            className="flex w-full items-center gap-2 bg-muted/60 px-3 py-2 text-left text-xs hover:bg-muted"
          >
            <span className="min-w-0 flex-1">{open ? "" : transitSummary(transit)}</span>
            <span className="inline-flex shrink-0 items-center gap-1 font-medium text-primary">
              {open ? "Zwiń" : "Pokaż"}
              {open ? <ChevronUp className="h-3.5 w-3.5" aria-hidden /> : <ChevronDown className="h-3.5 w-3.5" aria-hidden />}
            </span>
          </button>
        </li>
      ) : null}
    </ul>
  );
}

function SectionBody({
  transit,
  open,
  onToggle,
}: {
  transit: CvInTransit;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <section aria-label={CV_TRANSIT_TITLE} className="min-w-0">
      <header className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-semibold">{CV_TRANSIT_TITLE}</h3>
        {transit.returned_total > 0 ? (
          <span className="rounded-full bg-primary/10 px-1.5 text-xs font-semibold tabular-nums text-primary">
            {transit.returned_total}
          </span>
        ) : null}
        <span className="flex-1" />
        <RemoveMenu />
      </header>
      <p className="mb-2 text-xs text-muted-foreground">{CV_TRANSIT_HINT}</p>
      {transitIsEmpty(transit) ? (
        <p className="rounded-lg border border-border px-3 py-2 text-xs text-muted-foreground">{CV_TRANSIT_EMPTY}</p>
      ) : (
        <TransitList transit={transit} open={open} onToggle={onToggle} />
      )}
    </section>
  );
}

/**
 * `standalone` = panel „Czeka na Ciebie” nie ma nic innego i nic nie wróciło:
 * wąski pasek nad pulpitem, który „Pokaż” rozwija do pełnej listy.
 */
export function CvInTransitSection({
  transit,
  standalone = false,
}: {
  transit: CvInTransit;
  standalone?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const toggle = () => setOpen((value) => !value);
  if (!standalone) return <SectionBody transit={transit} open={open} onToggle={toggle} />;
  if (open) {
    return (
      <div className="rounded-xl border border-border bg-card p-4">
        <SectionBody transit={transit} open onToggle={toggle} />
      </div>
    );
  }
  const empty = transitIsEmpty(transit);
  return (
    <section
      aria-label={CV_TRANSIT_TITLE}
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-border bg-card px-4 py-2"
    >
      <Send className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
      <h3 className="text-sm font-semibold">{CV_TRANSIT_TITLE}</h3>
      <p className="min-w-0 flex-1 basis-48 text-xs text-muted-foreground">
        {empty ? CV_TRANSIT_EMPTY : `${transitSummary(transit)} · nic nie wróciło`}
      </p>
      {empty ? null : (
        <Button size="sm" variant="outline" className="shrink-0" onClick={toggle} aria-expanded={false}>
          Pokaż
        </Button>
      )}
      <RemoveMenu />
    </section>
  );
}
