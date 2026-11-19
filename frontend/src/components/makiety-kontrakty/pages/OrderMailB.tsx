"use client";
// B · Zamówienia z maila — „Tabela kolejki”. Każdy wpis to jeden wiersz:
// Wpłynęło · Klient · Zamówienie · Okres · Osoby · Do sprawdzenia (liczba
// i pierwszy powód) · akcje. Pierwszy wiersz rozwinięty pod spodem (plan
// zapisu i powody z podpowiedzią), kolejne rozwija kliknięcie. Historia
// automatycznych sprawdzeń to osobna zakładka „Historia sprawdzeń” z kolumną
// „Co się zmieniło” zamiast dziesiątek wierszy „5 / 0 / 5” pod kolejką.
// Nic nie zapisuje — „Zastosuj”, „Odrzuć” i „Pobierz…” bez akcji.
import { Fragment, useState, type MouseEvent } from "react";
import Link from "next/link";
import { Check, ChevronDown, ChevronRight, CircleCheck, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDateTimePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import type { OrderMailDocument, OrderMailOutcome } from "@/lib/api/orderMail";
import { personFromEmail, today } from "../shared/format";
import {
  applyBlockedReason,
  checkPoints,
  CheckList,
  identLabel,
  OrderMailHead,
  orderNumber,
  OUTCOME_TABS,
  outcomeTabItems,
  period,
  PlanTable,
  POINT_SHORT,
  QueueNote,
  RecheckTable,
  recheckLine,
  recheckSummary,
  SECTION_LABEL,
  TabsBar,
  useMkOrderMailCounts,
  useMkOrderMailQueue,
  useMkOrderMailSync,
  useMkRecheckRuns,
  type TabItem,
} from "./OrderMailA";

type TabKey = OrderMailOutcome | "history";

const stop = (e: MouseEvent) => e.stopPropagation();

/** „<osoba>” + „<stawka> zł/h”; kilka osób → pierwsza i „+ 2 osoby”. */
function PeopleCell({ doc }: { doc: OrderMailDocument }) {
  const rows = doc.proposal?.rows ?? [];
  const extracted = doc.extraction?.consultant_rows ?? [];
  const people = rows.length
    ? rows.map((r) => ({ name: r.row_name, rate: formatMoney(r.rate_client, doc.extraction?.currency, r.rate_unit) }))
    : extracted.map((r) => ({ name: r.consultant_name, rate: formatMoney(r.rate_client, doc.extraction?.currency, r.rate_unit) }));
  if (people.length === 0) {
    return (
      <>
        <span className={CALM_EMPTY}>—</span>
        <span className={CALM_SUBLINE}>nie odczytano osób</span>
      </>
    );
  }
  const [first, ...rest] = people;
  return (
    <>
      <span className="block font-medium text-foreground">{first.name}</span>
      <span className={CALM_SUBLINE}>
        {rest.length ? `+ ${rest.length} ${rest.length === 1 ? "osoba" : rest.length < 5 ? "osoby" : "osób"}` : first.rate}
      </span>
    </>
  );
}

/** Liczba uwag i pierwszy powód; przy zapisanych — numer zamówienia. */
function StateCell({ doc }: { doc: OrderMailDocument }) {
  if (doc.applied_order_id) {
    return (
      <>
        <span className="flex items-center gap-1.5 font-medium text-foreground">
          <CircleCheck className="size-3.5 shrink-0 text-success" aria-hidden />
          Zamówienie #{doc.applied_order_id}
        </span>
        <span className={CALM_SUBLINE}>{doc.applied_at ? `zapisane ${formatDateTimePl(doc.applied_at)}` : "zapisane"}</span>
      </>
    );
  }
  const points = checkPoints(doc);
  if (points.length === 0) return <span className={CALM_EMPTY}>—</span>;
  const [first, second] = points;
  return (
    <span title={points.map((p) => p.title).join("\n")} className="block min-w-0">
      <span className="flex items-center gap-1.5 font-medium text-warning-muted-foreground">
        <span className="inline-flex min-w-[18px] shrink-0 items-center justify-center rounded-full bg-warning-muted px-1 text-[11px] font-semibold tabular-nums">
          {points.length}
        </span>
        <span className="truncate">{POINT_SHORT[first.kind]}</span>
      </span>
      {second ? (
        <span className={cn(CALM_SUBLINE, "truncate pl-[24px]")}>też: {POINT_SHORT[second.kind].charAt(0).toLowerCase() + POINT_SHORT[second.kind].slice(1)}</span>
      ) : null}
    </span>
  );
}

function Actions({ doc, primary }: { doc: OrderMailDocument; primary: boolean }) {
  const canDismiss = doc.can_dismiss === true || doc.can_apply;
  if (doc.outcome === "needs_review") {
    const blocked = applyBlockedReason(doc);
    return (
      <span className="inline-flex items-center gap-0.5" onClick={stop}>
        <Button
          type="button"
          size="sm"
          variant={primary ? "primary" : "outline"}
          className="gap-1.5 px-2.5"
          disabled={blocked != null}
          title={blocked ?? undefined}
        >
          <Check className="size-3.5" aria-hidden />
          Zastosuj
        </Button>
        <Button type="button" size="sm" variant="quiet" className="gap-1.5 px-2.5" disabled={!canDismiss}>
          <X className="size-3.5" aria-hidden />
          Odrzuć
        </Button>
      </span>
    );
  }
  if (doc.outcome === "unrecognized_client" || doc.outcome === "failed") {
    return canDismiss ? (
      <span onClick={stop}>
        <Button type="button" size="sm" variant="quiet">
          <X className="size-3.5" aria-hidden />
          Odrzuć
        </Button>
      </span>
    ) : null;
  }
  return doc.client_id ? (
    <Link
      href={`/clients/${doc.client_id}?tab=zamowienia`}
      onClick={stop}
      className="text-[12.5px] font-medium text-primary hover:underline"
    >
      Zamówienia klienta
    </Link>
  ) : null;
}

/** Rozwinięcie wiersza: skąd wpis, plan zapisu i „Do sprawdzenia” z podpowiedziami. */
function Expanded({ doc }: { doc: OrderMailDocument }) {
  const points = checkPoints(doc);
  const recheck = recheckLine(doc);
  return (
    <div className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] gap-6">
      <div className="min-w-0">
        <h3 className={SECTION_LABEL}>Plan zapisu</h3>
        <p className="mt-1 text-[12.5px] leading-[18px] text-muted-foreground">
          Wpłynęło {formatDateTimePl(doc.received_at)} od {personFromEmail(doc.sender_email)}
          {doc.subject ? (
            <span className="block truncate" title={doc.subject}>
              „{doc.subject}”
            </span>
          ) : null}
          <span className="block">
            {doc.client_name ?? "Klient nierozpoznany"} · {identLabel(doc)}
          </span>
        </p>
        <div className="mt-2">
          <PlanTable doc={doc} hideSamePeriod />
        </div>
      </div>
      <div className="min-w-0">
        {points.length ? (
          <>
            <h3 className={SECTION_LABEL}>Do sprawdzenia · {points.length}</h3>
            <div className="mt-2">
              <CheckList points={points} />
            </div>
            {recheck ? <p className="mt-2.5 text-[12px] text-muted-foreground">{recheck}</p> : null}
          </>
        ) : doc.applied_order_id ? (
          <>
            <h3 className={SECTION_LABEL}>Wynik</h3>
            <p className="mt-2 text-[13px] text-foreground">
              Zapisane jako zamówienie #{doc.applied_order_id}
              {doc.applied_at ? <span className="text-muted-foreground"> · {formatDateTimePl(doc.applied_at)}</span> : null}
            </p>
          </>
        ) : null}
      </div>
    </div>
  );
}

function QueueTable({ items, review }: { items: OrderMailDocument[]; review: boolean }) {
  // `undefined` = jeszcze nikt nie klikał → rozwinięty pierwszy wiersz.
  const [expanded, setExpanded] = useState<number | null | undefined>(undefined);
  const openId = expanded === undefined ? (items[0]?.id ?? null) : expanded;
  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
      <table className="w-full table-fixed text-[13px]">
        <thead>
          <tr className="border-b border-border">
            <th className={cn(CALM_HEAD, "w-[86px] py-2 pl-4 pr-2 text-left")}>Wpłynęło</th>
            <th className={cn(CALM_HEAD, "w-[92px] px-2 py-2 text-left")}>Klient</th>
            <th className={cn(CALM_HEAD, "w-[92px] px-2 py-2 text-left")}>Zamówienie</th>
            <th className={cn(CALM_HEAD, "w-[172px] px-2 py-2 text-left")}>Okres</th>
            <th className={cn(CALM_HEAD, "w-[166px] px-2 py-2 text-left")}>Osoby</th>
            <th className={cn(CALM_HEAD, "px-2 py-2 text-left")}>{review ? "Do sprawdzenia" : "Wynik"}</th>
            <th className={cn(CALM_HEAD, "py-2 pl-2 pr-3 text-right", review ? "w-[184px]" : "w-[150px]")}>
              <span className="sr-only">Akcje</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((d) => {
            const open = d.id === openId;
            const [date, time] = formatDateTimePl(d.received_at).split(" ");
            // W gęstej kolumnie „17.11” — rok tylko, gdy to nie bieżący rok.
            const day = date && date.slice(6) === today().slice(0, 4) ? date.slice(0, 5) : date;
            const Chevron = open ? ChevronDown : ChevronRight;
            return (
              <Fragment key={d.id}>
                <tr
                  className={cn(
                    "cursor-pointer align-top transition-colors",
                    open ? "bg-muted/40" : cn(CALM_ROW, "hover:bg-muted/30"),
                  )}
                  onClick={() => setExpanded(open ? null : d.id)}
                  aria-expanded={open}
                >
                  <td className="py-2.5 pl-4 pr-2">
                    <span className="flex items-start gap-1.5">
                      <Chevron className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      <span>
                        <span className="block tabular-nums text-foreground">{day}</span>
                        <span className={CALM_SUBLINE}>{time}</span>
                      </span>
                    </span>
                  </td>
                  <td className="px-2 py-2.5">
                    <span className="block truncate font-medium text-foreground" title={d.client_name ?? undefined}>
                      {d.client_name ?? "Nierozpoznany"}
                    </span>
                  </td>
                  <td className="px-2 py-2.5 tabular-nums">
                    <span className="block truncate" title={orderNumber(d) ?? undefined}>
                      {orderNumber(d) ?? <span className={CALM_EMPTY}>—</span>}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-2 py-2.5 tabular-nums">
                    {d.extraction ? period(d.extraction.start_date, d.extraction.end_date) : <span className={CALM_EMPTY}>—</span>}
                  </td>
                  <td className="px-2 py-2.5">
                    <PeopleCell doc={d} />
                  </td>
                  <td className="min-w-0 px-2 py-2.5">
                    <StateCell doc={d} />
                  </td>
                  <td className="py-2 pl-2 pr-3 text-right">
                    <Actions doc={d} primary={open} />
                  </td>
                </tr>
                {open ? (
                  <tr className={CALM_ROW}>
                    <td colSpan={7} className="bg-muted/40 px-4 pb-4 pt-1">
                      <div className="rounded-lg border border-border/70 bg-card px-4 py-3">
                        <Expanded doc={d} />
                      </div>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function HistoryTab() {
  const q = useMkRecheckRuns();
  const data = q.data;
  const w = data?.window;
  if (q.isError) return <QueueNote error>Nie udało się pobrać historii sprawdzeń.</QueueNote>;
  if (!q.isSuccess) return <QueueNote>Ładowanie historii sprawdzeń…</QueueNote>;
  const runs = data?.items ?? [];
  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
      <p className="border-b border-border/60 px-4 py-2.5 text-[12.5px] leading-[18px] text-muted-foreground">
        {w?.enabled ? `Co godzinę w godzinach ${w.start_hour}:00–${w.end_hour}:00` : "Co godzinę"} system sam próbuje
        dokończyć wstrzymane zamówienia; wiersz powstaje tylko wtedy, gdy coś się zmieniło.
        {recheckSummary(data) ? (
          <>
            {" "}
            Ostatnie sprawdzenie: <span className="font-medium text-foreground">{recheckSummary(data)}</span>.
          </>
        ) : null}
      </p>
      {runs.length === 0 ? (
        <p className="px-4 py-6 text-[13px] text-muted-foreground">
          Tu trafiają tylko sprawdzenia, które coś zmieniły — w ostatnich 30 dniach nie było żadnego.
        </p>
      ) : (
        <RecheckTable runs={runs} limit={25} />
      )}
    </section>
  );
}

export function OrderMailB() {
  const [tab, setTab] = useState<TabKey>("needs_review");
  const counts = useMkOrderMailCounts();
  const sync = useMkOrderMailSync();
  const recheck = useMkRecheckRuns();
  const outcome: OrderMailOutcome = tab === "history" ? "needs_review" : tab;
  const queue = useMkOrderMailQueue(outcome);
  const items = queue.data?.items ?? [];
  const review = outcome === "needs_review" || outcome === "unrecognized_client" || outcome === "failed";
  const tabs: TabItem<TabKey>[] = [
    ...outcomeTabItems(counts),
    { key: "history", label: "Historia sprawdzeń", count: recheck.data?.items.length ?? null },
  ];
  const empty = OUTCOME_TABS.find((t) => t.outcome === outcome)?.empty;

  return (
    <div className="space-y-3">
      <OrderMailHead status={sync.data} failed={sync.isError} />
      <TabsBar items={tabs} value={tab} onChange={setTab} />
      {tab === "history" ? (
        <HistoryTab />
      ) : queue.isError ? (
        <QueueNote error>Nie udało się pobrać kolejki — odśwież stronę.</QueueNote>
      ) : !queue.isSuccess ? (
        <QueueNote>Ładowanie kolejki…</QueueNote>
      ) : items.length === 0 ? (
        <QueueNote>{empty}</QueueNote>
      ) : (
        <>
          <QueueTable key={outcome} items={items} review={review} />
          {(queue.data?.total ?? 0) > items.length ? (
            <p className="text-[12px] text-muted-foreground">
              Pokazano {items.length} najnowszych z {queue.data?.total}.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
