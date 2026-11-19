"use client";
// B · Opieka — dzisiejsza karta konsultanta oczyszczona do wąskiej kolumny:
// bez nagłówka z imieniem i klientem (stoją w karcie umowy po lewej), pierwsza
// linia to kropka „Uwaga” i powody krótką listą, cztery liczby w jednym rzędzie
// (`ds/InlineStats` zamiast czterech kafli), „Następny krok” z jednym
// przyciskiem, plan kontaktów zwinięty, sprawy i projekt obok siebie,
// „Historia” z pigułkami filtrów (te same reguły co dziś: `card-format`).
// Zapis nic nie robi (makieta).
import Link from "next/link";
import { useState } from "react";
import { ChevronRight, MoreHorizontal, Plus } from "lucide-react";
import { InlineStats } from "@/components/ds/InlineStats";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  HISTORY_FILTERS,
  cardKpis,
  closedCasesLine,
  eventDetailSeparator,
  historyCounts,
  historyEvents,
  openCases,
  type HistoryFilter,
} from "@/components/care/card/card-format";
import { healthLabel } from "@/components/care/health-format";
import type { HealthLevel, NextStepKind, TimelineEvent } from "@/lib/api/care";
import { cn } from "@/lib/utils";
import { useMkCareCard, useMkContract } from "../shared/data";
import { fmtDate, fmtDayMonth, today } from "../shared/format";
import { asCard, CaseRows, KnownProjectText, KPI_TEXT, PlanList, planRows, useMkCareTimeline } from "./OpiekaA";
import type { TabProps } from "./types";

const HEALTH_DOT_BG: Record<HealthLevel, string> = {
  ok: "bg-success",
  watch: "bg-warning",
  risk: "bg-destructive",
};

const STEP_BUTTON: Record<NextStepKind, string> = {
  conversation: "Zapisz rozmowę",
  feedback: "Rozmowa z menedżerem",
  front_office: "Przekaż do front office",
  raise_cadence: "Zmień rytm",
};

function Box({ className, children }: { className?: string; children: React.ReactNode }) {
  return <section className={cn("rounded-xl border border-border bg-card shadow-xs", className)}>{children}</section>;
}

function BoxTitle({ title, meta, action }: { title: string; meta?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="mb-2 flex min-h-7 items-center justify-between gap-2">
      <h3 className="flex items-baseline gap-2 text-[13px] font-semibold text-foreground">
        {title}
        {meta ? <span className="text-[12px] font-normal text-muted-foreground">{meta}</span> : null}
      </h3>
      {action}
    </div>
  );
}

function EventRows({ label, events }: { label: string; events: TimelineEvent[] }) {
  if (events.length === 0) return null;
  return (
    <div>
      <p className="pt-1 text-[10.5px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">{label}</p>
      <ol className="divide-y divide-border/60" aria-label={label}>
        {events.map((event, i) => (
          <li
            key={`${event.kind}-${event.on}-${i}`}
            className={cn("grid grid-cols-[84px_minmax(0,1fr)] gap-3 py-1.5 text-[13px] leading-5", event.future && "text-muted-foreground")}
          >
            <span className="tabular-nums text-muted-foreground">{fmtDate(event.on)}</span>
            <span className="min-w-0 break-words">
              {event.link ? (
                <Link href={event.link} className={cn("hover:underline", !event.future && "text-foreground")}>
                  {event.title}
                </Link>
              ) : (
                <span className={event.future ? undefined : "text-foreground"}>{event.title}</span>
              )}
              {event.detail ? (
                <span className="text-muted-foreground">
                  {eventDetailSeparator(event.detail)}
                  {event.detail}
                </span>
              ) : null}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function History({ contractId }: { contractId: number }) {
  const query = useMkCareTimeline(contractId);
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const events = query.data?.events ?? [];
  const counts = historyCounts(events);
  const { past, ahead } = historyEvents(events, filter);

  return (
    <Box className="p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[13px] font-semibold text-foreground">Historia</h3>
        <div role="group" aria-label="Filtr historii" className="flex flex-wrap gap-1">
          {HISTORY_FILTERS.map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={filter === item.value}
              onClick={() => setFilter(item.value)}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-[12px] transition-colors",
                filter === item.value
                  ? "border-primary bg-primary/10 font-medium text-foreground"
                  : "border-border text-muted-foreground hover:bg-muted",
              )}
            >
              {item.label}
              {query.isSuccess ? <span className="ml-1 tabular-nums text-muted-foreground">{counts[item.value]}</span> : null}
            </button>
          ))}
        </div>
      </div>
      {query.isLoading ? (
        <p className="text-[13px] text-muted-foreground">Wczytywanie historii…</p>
      ) : query.isError ? (
        <p className="text-[13px] text-destructive">Nie udało się pobrać historii opieki.</p>
      ) : ahead.length + past.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{filter === "all" ? "Nie ma jeszcze zdarzeń." : "Nic w tym filtrze."}</p>
      ) : (
        <div className="space-y-2">
          {/* Plan i końce dat stoją osobno — zaległy punkt planu to wciąż „do zrobienia”, nie zdarzenie z przeszłości. */}
          <EventRows label="Przed nami" events={ahead} />
          <EventRows label="Wcześniej" events={past} />
        </div>
      )}
    </Box>
  );
}

export function OpiekaB({ contractId }: TabProps) {
  const cardQuery = useMkCareCard(contractId);
  const card = asCard(cardQuery.data);
  const c = useMkContract(contractId).data;
  const [planOpen, setPlanOpen] = useState(false);

  if (cardQuery.isLoading) return <p className="text-sm text-muted-foreground">Wczytywanie opieki…</p>;
  if (cardQuery.isError || !card) {
    return <p className="text-sm text-destructive">Nie udało się pobrać karty opieki tego kontraktu.</p>;
  }

  const kpis = cardKpis(card, today());
  const rows = planRows(card);
  const open = rows.filter((r) => r.status === "open");
  const overdue = rows.filter((r) => r.overdueDays).length;
  const next = open[0] ?? null;
  const step = card.next_step;
  const cases = openCases(card.cases);
  const closedLine = closedCasesLine(card.cases);
  const reasons = card.health?.reasons ?? [];
  const planSummary = [
    open.length ? `${open.length} otwarte` : "bez otwartych",
    overdue ? `${overdue} po terminie` : null,
    next ? `najbliższy ${fmtDayMonth(next.due)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="space-y-3">
      <Box className="p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            {card.health ? (
              <span className="inline-flex shrink-0 items-center gap-1.5 text-[13.5px] font-semibold leading-5 text-foreground">
                <span aria-hidden className={cn("size-2 rounded-full", HEALTH_DOT_BG[card.health.level])} />
                {healthLabel(card.health)}
              </span>
            ) : null}
            {reasons.length ? (
              <ul className="min-w-0 space-y-0.5 text-[13px] leading-5 text-foreground" aria-label="Dlaczego">
                {reasons.map((r) => (
                  <li key={r} className="flex gap-1.5">
                    <span aria-hidden className="text-muted-foreground">–</span>
                    {r}
                  </li>
                ))}
              </ul>
            ) : card.health ? null : (
              <p className="text-[13px] text-muted-foreground">Ocenę relacji widzą opiekun, DL, HoR i admin.</p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1 text-[12.5px] text-muted-foreground">
            <span className="text-right leading-4">
              <span className="block">
                opiekun <span className="text-foreground">{card.owner.name ?? "—"}</span>
              </span>
              <span className="block">rytm {card.cadence?.label ?? "nie ustalono"}</span>
            </span>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button type="button" variant="ghost" size="icon-sm" aria-label="Więcej akcji opieki">
                  <MoreHorizontal className="size-4" aria-hidden />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem>Zmień opiekuna…</DropdownMenuItem>
                <DropdownMenuItem>Rytm kontaktu…</DropdownMenuItem>
                {next ? <DropdownMenuItem>Pomiń punkt planu ({fmtDayMonth(next.due)})…</DropdownMenuItem> : null}
                <DropdownMenuSeparator />
                {card.candidate_id ? (
                  <DropdownMenuItem asChild>
                    <Link href={`/candidates/${card.candidate_id}`}>Profil kandydata</Link>
                  </DropdownMenuItem>
                ) : null}
                <DropdownMenuItem asChild>
                  <Link href={`/clients/${card.client_id}?tab=ludzie`}>Ludzie i technologie klienta</Link>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        {/* Cztery liczby w jednym rzędzie: siatka zamiast zawijanego `flex`, dopisek pod podpisem. */}
        <InlineStats
          className="mt-3 grid grid-cols-[1.3fr_1fr_1fr_1fr] gap-x-4 border-t border-border/70 pt-3"
          stats={kpis.map((k) => ({
            id: k.label,
            label: (
              <>
                {k.label}
                {k.note ? <span className="block">{k.note}</span> : null}
              </>
            ),
            value: <span className={KPI_TEXT[k.tone]}>{k.value}</span>,
          }))}
        />
      </Box>

      {step ? (
        <section
          aria-label="Następny krok"
          className="flex items-center justify-between gap-3 rounded-xl border border-primary/30 bg-primary/5 px-4 py-3"
        >
          <div className="min-w-0">
            <p className="text-[10.5px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">Następny krok</p>
            <p className="text-[13.5px] font-semibold leading-5 text-foreground">{step.label}</p>
            {step.detail ? <p className="text-[12px] text-muted-foreground">{step.detail}</p> : null}
          </div>
          {step.kind ? (
            <Button type="button" size="sm">
              {STEP_BUTTON[step.kind]}
            </Button>
          ) : null}
        </section>
      ) : null}

      <Collapsible open={planOpen} onOpenChange={setPlanOpen} className="rounded-xl border border-border bg-card shadow-xs">
        <CollapsibleTrigger className="flex w-full items-center gap-1.5 rounded-xl px-4 py-2.5 text-left hover:bg-muted/40">
          <ChevronRight
            aria-hidden
            className={cn("size-4 text-muted-foreground transition-transform", planOpen && "rotate-90")}
          />
          <span className="text-[13px] font-semibold text-foreground">Plan kontaktów</span>
          <span className={cn("text-[12px]", overdue ? "text-destructive" : "text-muted-foreground")}>{planSummary}</span>
        </CollapsibleTrigger>
        <CollapsibleContent className="border-t border-border/70 px-4 py-1.5">
          <PlanList rows={rows} startOn={card.start_on} />
        </CollapsibleContent>
      </Collapsible>

      <div className="grid grid-cols-2 items-start gap-3">
        <Box className="p-4">
          <BoxTitle
            title="Sprawy"
            meta={cases.length ? `${cases.length} otwarte` : null}
            action={
              <Button type="button" variant="ghost" size="sm" className="-mr-2 h-7">
                <Plus className="size-3.5" aria-hidden />
                Nowa sprawa
              </Button>
            }
          />
          {cases.length ? (
            <CaseRows cases={card.cases} />
          ) : (
            <p className="text-[13px] text-muted-foreground">Brak otwartych spraw.</p>
          )}
          {closedLine ? <p className="mt-1 text-[12px] text-muted-foreground">{closedLine}</p> : null}
        </Box>
        <Box className="p-4">
          <BoxTitle title="Co wiemy o projekcie" />
          <KnownProjectText card={card} lineManager={c?.line_manager ?? null} />
        </Box>
      </div>

      <History contractId={contractId} />
    </div>
  );
}
