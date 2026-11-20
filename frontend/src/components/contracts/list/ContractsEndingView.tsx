"use client";
// „Kończące się” (przebudowa 20.11.2026): odejścia do domknięcia (wariant A)
// i ten sam zbiór na osi czasu (wariant B). Zbiór, filtry i liczba na pigułce
// zostają z listy (`bucket=ending`); tu jest tylko inny widok tych wierszy.
import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { rowActivationProps } from "@/hooks/useRowNavigation";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_UNIT } from "@/lib/calm-table";
import { fmtDatePl, relativeDays, URGENT_DAYS } from "@/lib/contract-happening";
import {
  AGREEMENT_STATE_LABEL,
  agreementState,
  endingSummary,
  groupByMonth,
  lastWorkingDay,
  monthYearLabel,
  orderConflict,
  sortByLastDay,
  timelineScale,
  type EndingRowFacts,
} from "@/lib/contract-ending";
import { formatPlnWhole, monthlyMargin, peopleLabel, terminationReasonLabel } from "@/lib/contract-list-next";
import { cn } from "@/lib/utils";
import { ContractRowNote } from "./ContractNextCell";

export interface EndingListRow extends EndingRowFacts {
  candidate_name?: string | null;
  client_id?: number | null;
  client_name?: string | null;
  job_title?: string | null;
}

export type EndingViewState = "loading" | "error" | "forbidden" | "not_found" | "empty" | "ready";

export interface ContractsEndingViewProps {
  rows: readonly EndingListRow[];
  state: EndingViewState;
  onRetry: () => void;
  timeline: boolean;
  onTimelineChange: (timeline: boolean) => void;
  today: string;
  /** Marża przy wierszu = wynik firmy albo portfel Delivery Leada (jak na liście). */
  canSeeMargin: boolean;
  canRecordAgreement: boolean;
  canBulkAct: boolean;
  selectedIds: ReadonlySet<number>;
  onToggleSelected: (ids: number[]) => void;
  openContractId: number | null;
  onOpen: (id: number) => void;
  detailHref: (id: number) => string;
  onDetailLinkClick: () => void;
  onRecordAgreement: (row: EndingListRow) => void;
  /** Serwer zwrócił więcej odejść, niż lista pobiera naraz. */
  truncated: boolean;
}

function daysUntil(today: string, iso: string): number {
  const a = Date.parse(`${today}T00:00:00Z`);
  const b = Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);
  return Math.round((b - a) / 86_400_000);
}

const AGREEMENT_DOT = {
  open: "bg-warning",
  notice: "bg-success",
  mutual_agreement: "bg-success",
  not_applicable: "bg-muted-foreground/40",
} as const;

export function ContractsEndingView(props: ContractsEndingViewProps) {
  const { rows, state, timeline, onTimelineChange, canSeeMargin } = props;
  const sorted = sortByLastDay(rows);
  const summary = endingSummary(sorted);

  return (
    <div className="space-y-3" data-testid="contracts-ending-view">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {state === "ready" ? (
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-[13px]" data-testid="contracts-ending-summary">
            <span>
              <strong className="text-[15px] font-semibold tabular-nums text-foreground">{peopleLabel(summary.people)}</strong>{" "}
              <span className="text-muted-foreground">
                odchodzi{summary.latest ? ` do ${fmtDatePl(summary.latest)}` : ""}
              </span>
            </span>
            {canSeeMargin ? (
              <span title={summary.margin.unpriced ? `Bez ${summary.margin.unpriced} umów bez stawki albo w innej walucie` : undefined}>
                <strong className="text-[15px] font-semibold tabular-nums text-foreground">{formatPlnWhole(summary.margin.total)}</strong>{" "}
                <span className="text-muted-foreground">marży miesięcznie odejdzie</span>
              </span>
            ) : null}
            {summary.b2b > 0 ? (
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden className={cn("size-1.5 rounded-full", summary.openAgreements ? "bg-warning" : "bg-success")} />
                <strong className="text-[15px] font-semibold tabular-nums text-foreground">{summary.openAgreements}</strong>{" "}
                <span className="text-muted-foreground">z {summary.b2b} umów B2B bez zapisanego rozwiązania</span>
              </span>
            ) : null}
          </div>
        ) : (
          <span />
        )}
        <div
          role="group"
          aria-label="Widok kończących się"
          className="inline-flex rounded-lg border border-border bg-muted/50 p-0.5 text-[12.5px] font-medium"
        >
          {[
            { value: false, label: "Tabela" },
            { value: true, label: "Oś czasu" },
          ].map((option) => (
            <button
              key={option.label}
              type="button"
              aria-pressed={timeline === option.value}
              data-tour={option.value ? "contracts.ending.timeline" : undefined}
              onClick={() => onTimelineChange(option.value)}
              className={cn(
                "rounded-md px-2.5 py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                timeline === option.value ? "bg-card text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {state === "loading" ? (
        <div className="rounded-xl border border-border bg-card px-4 py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>
      ) : state === "error" || state === "forbidden" || state === "not_found" ? (
        <div className="rounded-xl border border-border bg-card">
          <QueryStateNotice state={state} className="border-0" onRetry={props.onRetry} />
        </div>
      ) : state === "empty" ? (
        <div className="rounded-xl border border-border bg-card px-4 py-10 text-center text-sm text-muted-foreground">
          Nikt nie odchodzi w najbliższych 30 dniach i nie ma zapisanych zakończeń — to normalne.
        </div>
      ) : timeline ? (
        <EndingTimeline {...props} rows={sorted} />
      ) : (
        <EndingTable {...props} rows={sorted} />
      )}

      {props.truncated ? (
        <p className="text-[12.5px] text-warning-muted-foreground">
          Widać pierwsze {rows.length} odejść — zawęź listę wyszukiwarką albo filtrami.
        </p>
      ) : null}
      <p className="text-[12px] text-muted-foreground">
        „Kończące się” to osoby z zapisanym zakończeniem współpracy albo umową kończącą się w 30 dni — ta sama reguła co
        liczba na pigułce.
      </p>
    </div>
  );
}

function PersonCell({ row, props }: { row: EndingListRow; props: Omit<ContractsEndingViewProps, "rows"> }) {
  return (
    <>
      <Link
        href={props.detailHref(row.id)}
        onClick={props.onDetailLinkClick}
        className="block text-[13px] font-semibold leading-5 text-foreground hover:text-primary"
      >
        {row.candidate_name ?? `Kontrakt #${row.id}`}
      </Link>
      <span className="flex min-w-0 items-center gap-1.5 text-[11.5px] leading-4 text-muted-foreground">
        <span className="truncate" title={row.client_name ?? undefined}>
          {row.client_name ?? "—"}
        </span>
        <ContractRowNote status={row.status === "ending" ? null : row.status} contractType={row.contract_type} />
      </span>
    </>
  );
}

function EndingTable({ rows, ...props }: ContractsEndingViewProps) {
  const { canSeeMargin, canBulkAct, selectedIds, today } = props;
  const ids = rows.map((row) => row.id);
  const allSelected = ids.length > 0 && ids.every((id) => selectedIds.has(id));
  const someSelected = ids.some((id) => selectedIds.has(id));
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-xs">
      <table className="w-full min-w-[920px] table-fixed text-[13px]" data-testid="contracts-ending-table">
        <colgroup>
          <col className={canSeeMargin ? "w-[23%]" : "w-[26%]"} />
          <col className="w-[13%]" />
          <col className="w-[15%]" />
          <col className="w-[14%]" />
          {canSeeMargin ? <col className="w-[11%]" /> : null}
          <col />
        </colgroup>
        <thead>
          <tr className="border-b border-border">
            <th className={cn(CALM_HEAD, "px-4 py-2.5 text-left")}>
              <span className="flex items-center gap-2">
                {canBulkAct ? (
                  <Checkbox
                    checked={allSelected ? true : someSelected ? "indeterminate" : false}
                    onCheckedChange={(value) => props.onToggleSelected(value ? ids.filter((id) => !selectedIds.has(id)) : ids.filter((id) => selectedIds.has(id)))}
                    aria-label="Zaznacz wszystkie"
                  />
                ) : null}
                Osoba i klient
              </span>
            </th>
            <th className={cn(CALM_HEAD, "px-3 py-2.5 text-left")}>Ostatni dzień</th>
            <th className={cn(CALM_HEAD, "px-3 py-2.5 text-left")}>Powód</th>
            <th className={cn(CALM_HEAD, "px-3 py-2.5 text-left")}>Umowa B2B</th>
            {canSeeMargin ? (
              <th className={cn(CALM_HEAD, "px-3 py-2.5 text-right")}>
                Marża<span className={CALM_UNIT}>zł/mies.</span>
              </th>
            ) : null}
            <th className={cn(CALM_HEAD, "px-4 py-2.5 text-left")}>Do zrobienia</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const last = lastWorkingDay(row);
            const days = last ? daysUntil(today, last) : null;
            const agreement = agreementState(row);
            const conflict = orderConflict(row);
            const margin = monthlyMargin(row);
            const reason = terminationReasonLabel(row.termination_reason);
            const open = props.openContractId === row.id;
            const selected = selectedIds.has(row.id);
            return (
              <tr
                key={row.id}
                {...rowActivationProps(String(row.id), () => props.onOpen(row.id))}
                data-tour="contracts.list.row"
                data-contract-member={row.id}
                aria-selected={open}
                className={cn(
                  CALM_ROW,
                  "h-[52px] cursor-pointer align-middle hover:bg-muted/40 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                  selected ? "bg-primary/10" : open && "bg-primary/5 shadow-[inset_3px_0_0_0_hsl(var(--primary))]",
                )}
              >
                <td className="px-4 py-1.5">
                  <div className="flex min-w-0 items-start gap-2">
                    {canBulkAct ? (
                      <Checkbox
                        checked={selected}
                        onCheckedChange={() => props.onToggleSelected([row.id])}
                        aria-label={`Zaznacz kontrakt ${row.id}`}
                        className="mt-0.5"
                      />
                    ) : null}
                    <div className="min-w-0">
                      <PersonCell row={row} props={props} />
                    </div>
                  </div>
                </td>
                <td className="px-3 py-1.5 tabular-nums">
                  {last ? (
                    <>
                      <span className="block font-semibold text-foreground">{fmtDatePl(last)}</span>
                      <span
                        className={cn(
                          "block text-[11.5px] font-medium",
                          days != null && days <= URGENT_DAYS ? "text-destructive" : "text-muted-foreground",
                        )}
                      >
                        {days != null ? relativeDays(days) : null}
                      </span>
                    </>
                  ) : (
                    <span className={CALM_EMPTY}>—</span>
                  )}
                </td>
                <td className="px-3 py-1.5 text-foreground" title={row.termination_lessons ?? undefined}>
                  {reason ?? <span className={CALM_EMPTY}>—</span>}
                </td>
                <td className="px-3 py-1.5">
                  <span className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-foreground">
                    <span aria-hidden className={cn("size-1.5 rounded-full", AGREEMENT_DOT[agreement])} />
                    {AGREEMENT_STATE_LABEL[agreement]}
                  </span>
                </td>
                {canSeeMargin ? (
                  <td className={cn(CALM_AMOUNT, "px-3 py-1.5 font-medium text-foreground")}>
                    {margin != null ? formatPlnWhole(margin).replace(" zł", "") : <span className={CALM_EMPTY}>—</span>}
                  </td>
                ) : null}
                <td className="px-4 py-1.5">
                  {conflict ? (
                    <span className="flex min-w-0 items-start gap-1.5 text-[12px] leading-4 text-foreground" data-testid="contract-ending-conflict">
                      <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden="true" />
                      <span className="line-clamp-2">{conflict}</span>
                    </span>
                  ) : agreement === "open" && props.canRecordAgreement ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => props.onRecordAgreement(row)}
                      title="Porozumienie albo wypowiedzenie podpisane poza NEXUSEM"
                    >
                      Zapisz rozwiązanie umowy
                    </Button>
                  ) : (
                    <span className={cn("text-[12.5px]", CALM_EMPTY)}>—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const TIMELINE_GRID = "grid grid-cols-[230px_minmax(0,1fr)_170px]";

function EndingTimeline({ rows, ...props }: ContractsEndingViewProps) {
  const { today, canSeeMargin } = props;
  const scale = timelineScale(today, rows.map(lastWorkingDay));
  const groups = groupByMonth(rows);
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-xs">
      <div className="min-w-[760px]" data-testid="contracts-ending-timeline">
        <div className={cn(TIMELINE_GRID, "border-b border-border")}>
          <div className={cn(CALM_HEAD, "px-4 py-2")}>Osoba</div>
          <div className="relative h-8" aria-hidden>
            {scale.months.map((month) => (
              <div
                key={month}
                className="absolute inset-y-0 border-l border-border/70 pl-2 pt-2 text-[11.5px] font-medium text-muted-foreground"
                style={{ left: `${scale.pos(month)}%` }}
              >
                {monthYearLabel(month)}
              </div>
            ))}
          </div>
          <div className={cn(CALM_HEAD, "px-4 py-2 text-right")}>{canSeeMargin ? "Marża / mies." : "Umowa B2B"}</div>
        </div>

        {groups.map((group) => (
          <div key={group.month || "bez-daty"}>
            <div className="border-b border-border/70 bg-muted/40 px-4 py-1.5 text-[12.5px] font-semibold text-foreground">
              {group.month ? monthYearLabel(`${group.month}-01`) : "Bez daty końca"}
              <span className="ml-2 font-normal text-muted-foreground">
                · {peopleLabel(group.rows.length)}
                {canSeeMargin
                  ? ` · ${formatPlnWhole(group.rows.reduce((sum, row) => sum + (monthlyMargin(row) ?? 0), 0))} marży / mies.`
                  : ""}
              </span>
            </div>
            {group.rows.map((row) => {
              const last = lastWorkingDay(row);
              const days = last ? daysUntil(today, last) : null;
              const conflict = orderConflict(row);
              const agreement = agreementState(row);
              const reason = terminationReasonLabel(row.termination_reason);
              const orderStart = row.client_order_start_date?.slice(0, 10) ?? null;
              const orderEnd = row.client_order_end_date?.slice(0, 10) ?? scale.to;
              const margin = monthlyMargin(row);
              const open = props.openContractId === row.id;
              return (
                <div
                  key={row.id}
                  {...rowActivationProps(String(row.id), () => props.onOpen(row.id))}
                  data-tour="contracts.list.row"
                  data-contract-member={row.id}
                  aria-selected={open}
                  className={cn(
                    TIMELINE_GRID,
                    "h-[46px] cursor-pointer items-center border-b border-border/60 hover:bg-muted/30 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                    open && "bg-primary/5 shadow-[inset_3px_0_0_0_hsl(var(--primary))]",
                  )}
                >
                  <div className="min-w-0 px-4">
                    <Link
                      href={props.detailHref(row.id)}
                      onClick={props.onDetailLinkClick}
                      className="block truncate text-[13px] font-semibold text-foreground hover:text-primary"
                      title={row.candidate_name ?? undefined}
                    >
                      {row.candidate_name ?? `Kontrakt #${row.id}`}
                    </Link>
                    <span className="block truncate text-[11.5px] text-muted-foreground" title={row.client_name ?? undefined}>
                      {row.client_name ?? "—"}
                      {reason ? ` · ${reason.toLowerCase()}` : ""}
                    </span>
                  </div>
                  <div className="relative h-full" aria-label={last ? `Ostatni dzień ${fmtDatePl(last)}` : "Bez daty końca"}>
                    {scale.months.map((month) => (
                      <div key={month} className="absolute inset-y-0 border-l border-border/40" style={{ left: `${scale.pos(month)}%` }} />
                    ))}
                    <div className="absolute inset-y-0 w-px bg-foreground/60" style={{ left: `${scale.pos(today)}%` }} />
                    {last ? (
                      <>
                        <div
                          className={cn(
                            "absolute top-1/2 h-2.5 -translate-y-1/2 rounded-r-full",
                            days != null && days <= URGENT_DAYS ? "bg-destructive/60" : "bg-warning/60",
                          )}
                          style={{ left: 0, width: `${scale.pos(last)}%` }}
                        />
                        <span
                          className="absolute top-1/2 -translate-y-1/2 whitespace-nowrap pl-1.5 text-[11.5px] font-semibold tabular-nums text-foreground"
                          style={{ left: `${scale.pos(last)}%` }}
                        >
                          {fmtDatePl(last).slice(0, 5)}
                        </span>
                      </>
                    ) : null}
                    {conflict && orderStart ? (
                      <div
                        title={conflict}
                        data-testid="contract-ending-order-bar"
                        className="absolute top-[31px] h-1.5 rounded-full border border-dashed border-primary/70 bg-primary/10"
                        style={{
                          left: `${scale.pos(orderStart)}%`,
                          width: `${Math.max(1, scale.pos(orderEnd) - scale.pos(orderStart))}%`,
                        }}
                      />
                    ) : null}
                  </div>
                  <div className="px-4 text-right">
                    {canSeeMargin ? (
                      <span className="block text-[13px] font-medium tabular-nums text-foreground">
                        {margin != null ? formatPlnWhole(margin) : <span className={CALM_EMPTY}>—</span>}
                      </span>
                    ) : null}
                    <span className={cn("block text-[11px]", agreement === "open" ? "text-warning-muted-foreground" : "text-muted-foreground")}>
                      {agreement === "not_applicable" ? "umowa bez rozwiązania B2B" : `umowa ${AGREEMENT_STATE_LABEL[agreement]}`}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-4 px-4 py-2 text-[11.5px] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-5 rounded-full bg-destructive/60" /> do {URGENT_DAYS} dni
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-5 rounded-full bg-warning/60" /> później
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-5 rounded-full border border-dashed border-primary/70 bg-primary/10" /> zamówienie klienta trwa po odejściu
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-3 w-px bg-foreground/60" /> dziś
          </span>
        </div>
      </div>
    </div>
  );
}
