"use client";

/**
 * Sekcje przepływu w „Czeka na Ciebie” (04.10.2026).
 *
 * Do 04.10 panel znał tylko kolejki z ostatnich 14–30 dni (przegląd DL, Cpro,
 * prepy, follow-upy), więc u rekruterów, TCM i DL pokazywał 0 zadań, choć
 * w Ogłoszeniach czekało ponad tysiąc osób. Serwer (`services/board_flow.py`)
 * liczy teraz cały przepływ rekrutacji, w których osoba pracuje — tu tylko
 * prezentacja i linki do istniejących ekranów:
 *  - blokady 12 h, Screening bez arkusza/stawki, Zweryfikowani bez QC CV,
 *    Ogłoszenia per rekrutacja (rekruter, TCM, DL),
 *  - umowy B2B czekające na podpis i zamówienia z maila (DL),
 *  - „Czeka na klienta” (DL) — w grupie „U innych”,
 *  - blok Finansów (zmiany w zamówieniach, braki, nowe PDF-y, nieudane maile,
 *    zatrudnieni bez zamówienia),
 *  - „Najlepsze propozycje z bazy” (07.10.2026) — `BoardTopProposals`.
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Clock, Lock } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  waitingFor,
  type FinanceBlock,
  type FlowBlock,
  type FlowPairRow,
} from "@/lib/api/boardTasks";
import { ORDER_CHANGES_SUMMARY_KEY, financeApi } from "@/lib/api/finance";
import { formatTime } from "@/lib/interview-cycle";
import { countPl } from "@/lib/plural-pl";
import { ORDER_CHANGES_POLL_MS } from "@/lib/polling";

import { Section } from "./BoardTasksSection";
import { BoardTopProposals, topProposalsCount } from "./BoardTopProposals";

const MISSING_LABEL = { sheet: "arkusz", rate: "stawka" } as const;

type Toggle = {
  expanded: Record<string, boolean>;
  onToggle: (kind: string) => void;
  shown: <T>(kind: string, rows: T[]) => T[];
};

function jobLabel(row: { job_title: string; job_working_title?: string | null }): string {
  return row.job_working_title?.trim() || row.job_title;
}

function pairLink(row: FlowPairRow): string {
  return `/jobs/${row.job_id}?candidate=${row.candidate_id}`;
}

function PairMeta({ row }: { row: FlowPairRow }) {
  return (
    <p className="truncate text-xs text-muted-foreground">
      {jobLabel(row)}
      {row.client_name ? ` · ${row.client_name}` : ""}
    </p>
  );
}

function PairRowItem({ row, aside }: { row: FlowPairRow; aside: React.ReactNode }) {
  return (
    <li className="flex items-center gap-2 px-3 py-2">
      <div className="min-w-0 flex-1">
        <Link href={pairLink(row)} className="block truncate text-sm font-medium hover:underline">
          {row.candidate_name}
        </Link>
        <PairMeta row={row} />
      </div>
      <div className="flex shrink-0 items-center gap-1.5">{aside}</div>
    </li>
  );
}

function Since({ since }: { since: string }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 text-xs tabular-nums text-muted-foreground">
      <Clock className="h-3 w-3" aria-hidden />
      {waitingFor(since)}
    </span>
  );
}

/** Liczba rzeczy w „Twój ruch” z bloku przepływu i Finansów. */
export function flowWorkCount(
  flow: FlowBlock | null | undefined,
  finance: FinanceBlock | null | undefined,
): number {
  const f = flow
    ? flow.claimed.length +
      flow.screening.length +
      flow.verified.length +
      flow.postings_total +
      flow.unsigned_contracts.length +
      flow.order_mail_review +
      topProposalsCount(flow.top_proposals)
    : 0;
  const fin = finance
    ? finance.gaps_open +
      finance.pdfs_new +
      finance.order_mail_failed +
      finance.hired_without_order_total
    : 0;
  return f + fin;
}

export function hasFlowWork(
  flow: FlowBlock | null | undefined,
  finance: FinanceBlock | null | undefined,
): boolean {
  return flowWorkCount(flow, finance) > 0;
}

/** „Czeka na klienta” (DL) — liczy się do grupy „U innych”. */
export function hasFlowOthers(flow: FlowBlock | null | undefined): boolean {
  return (flow?.waiting_client.length ?? 0) > 0;
}

export function BoardFlowSections({
  flow,
  finance,
  expanded,
  onToggle,
  shown,
}: { flow: FlowBlock | null | undefined; finance: FinanceBlock | null | undefined } & Toggle) {
  return (
    <>
      {flow && flow.claimed.length > 0 && (
        <Section
          title="Twoje blokady (12 h)"
          hint="Osoby, które wziąłeś z Nowych — porozmawiaj albo oddaj, zanim blokada minie."
          count={flow.claimed.length}
          expanded={expanded["flow_claimed"] === true}
          onToggle={() => onToggle("flow_claimed")}
        >
          {shown("flow_claimed", flow.claimed).map((row) => (
            <PairRowItem
              key={`${row.job_id}-${row.candidate_id}`}
              row={row}
              aside={
                row.claimed_until ? (
                  <span className="inline-flex items-center gap-1 text-xs tabular-nums text-muted-foreground">
                    <Lock className="h-3 w-3" aria-hidden />
                    do {formatTime(row.claimed_until)}
                  </span>
                ) : null
              }
            />
          ))}
        </Section>
      )}

      {flow && flow.screening.length > 0 && (
        <Section
          title="Screening — brakuje danych"
          hint="Bez arkusza screeningu i stawki kandydata karta nie wejdzie na „Zweryfikowany”."
          count={flow.screening.length}
          expanded={expanded["flow_screening"] === true}
          onToggle={() => onToggle("flow_screening")}
        >
          {shown("flow_screening", flow.screening).map((row) => (
            <PairRowItem
              key={`${row.job_id}-${row.candidate_id}`}
              row={row}
              aside={(row.missing ?? []).map((m) => (
                <Badge key={m} size="sm" variant="warning">
                  {MISSING_LABEL[m]}
                </Badge>
              ))}
            />
          ))}
        </Section>
      )}

      {flow && flow.verified.length > 0 && (
        <Section
          title="Zweryfikowani — czekają na CV do QC"
          hint="Przygotuj CV firmowe i przesuń kartę do „QC CV”."
          count={flow.verified.length}
          expanded={expanded["flow_verified"] === true}
          onToggle={() => onToggle("flow_verified")}
        >
          {shown("flow_verified", flow.verified).map((row) => (
            <PairRowItem
              key={`${row.job_id}-${row.candidate_id}`}
              row={row}
              aside={<Since since={row.since} />}
            />
          ))}
        </Section>
      )}

      {flow && flow.postings.length > 0 && (
        <Section
          title="Ogłoszenia do przejrzenia"
          hint="Zgłoszenia z portali w Twoich rekrutacjach — przejrzyj i przenieś do Nowych albo odrzuć."
          count={flow.postings_total}
          rows={flow.postings.length}
          expanded={expanded["flow_postings"] === true}
          onToggle={() => onToggle("flow_postings")}
        >
          {shown("flow_postings", flow.postings).map((row) => (
            <li key={row.job_id} className="flex items-center gap-2 px-3 py-2">
              <div className="min-w-0 flex-1">
                <Link href={`/jobs/${row.job_id}`} className="block truncate text-sm font-medium hover:underline">
                  {jobLabel(row)} · {countPl(row.count, "osoba", "osoby", "osób")}
                </Link>
                <p className="truncate text-xs text-muted-foreground">
                  {row.client_name ? `${row.client_name} · ` : ""}najstarsze czeka {waitingFor(row.oldest_at)}
                </p>
              </div>
            </li>
          ))}
        </Section>
      )}

      {flow && (flow.top_proposals?.length ?? 0) > 0 && (
        <BoardTopProposals
          rows={flow.top_proposals}
          expanded={expanded["flow_top_proposals"] === true}
          onToggle={() => onToggle("flow_top_proposals")}
          shown={shown}
        />
      )}

      {flow && flow.unsigned_contracts.length > 0 && (
        <Section
          title="Umowy B2B czekają na podpis"
          hint="Wygenerowane ponad 2 dni temu i wciąż niepodpisane — sprawdź z Partnerem."
          count={flow.unsigned_contracts.length}
          expanded={expanded["flow_unsigned"] === true}
          onToggle={() => onToggle("flow_unsigned")}
        >
          {shown("flow_unsigned", flow.unsigned_contracts).map((row) => (
            <li key={row.id} className="flex items-center gap-2 px-3 py-2">
              <div className="min-w-0 flex-1">
                <Link
                  href={`/contracts/b2b-generator?q=${encodeURIComponent(row.contract_number)}`}
                  className="block truncate text-sm font-medium hover:underline"
                >
                  Umowa {row.contract_number}
                  {row.partner_name ? ` · ${row.partner_name}` : ""}
                </Link>
                {row.client_name ? (
                  <p className="truncate text-xs text-muted-foreground">{row.client_name}</p>
                ) : null}
              </div>
              <Since since={row.created_at} />
            </li>
          ))}
        </Section>
      )}

      {flow && flow.order_mail_review > 0 && (
        <CountSection
          title="Zamówienia z maila do weryfikacji"
          hint="Automat nie zapisał ich sam — sprawdź odczyt i zastosuj."
          count={flow.order_mail_review}
          lines={[
            {
              label: countPl(flow.order_mail_review, "dokument czeka", "dokumenty czekają", "dokumentów czeka"),
              href: "/contracts?view=order-mail",
            },
          ]}
        />
      )}

      {finance ? <FinanceSections finance={finance} expanded={expanded} onToggle={onToggle} shown={shown} /> : null}
    </>
  );
}

type CountLine = { label: string; href: string };

function CountSection({
  title,
  hint,
  count,
  lines,
}: {
  title: string;
  hint: string;
  count: number;
  lines: CountLine[];
}) {
  return (
    <Section title={title} hint={hint} count={count} rows={lines.length} expanded onToggle={() => undefined}>
      {lines.map((line) => (
        <li key={line.href + line.label} className="px-3 py-2">
          <Link href={line.href} className="block truncate text-sm font-medium hover:underline">
            {line.label}
          </Link>
        </li>
      ))}
    </Section>
  );
}

function FinanceSections({ finance, expanded, onToggle, shown }: { finance: FinanceBlock } & Toggle) {
  // Ta sama liczba co badge przy zakładce w menu Finansów (zmiany bieżącego
  // miesiąca, „do zrobienia”). Odhaczenie unieważnia klucz.
  const summary = useQuery({
    queryKey: ORDER_CHANGES_SUMMARY_KEY,
    queryFn: async () => (await financeApi.getOrderChangesSummary()).data,
    refetchInterval: ORDER_CHANGES_POLL_MS,
  });
  const todo = summary.data?.todo ?? 0;
  const lines: CountLine[] = [];
  if (todo > 0) {
    lines.push({
      label: `Zmiany w zamówieniach: ${countPl(todo, "pozycja", "pozycje", "pozycji")} do zrobienia`,
      href: "/finance?view=order-changes",
    });
  }
  if (finance.gaps_open > 0) {
    lines.push({
      label: `Braki zamówień: ${finance.gaps_open}`,
      href: "/finance?view=order-changes&sub=gaps",
    });
  }
  if (finance.pdfs_new > 0) {
    lines.push({
      label: `Nowe PDF-y zamówień: ${finance.pdfs_new}`,
      href: "/finance?view=order-pdfs",
    });
  }
  if (finance.order_mail_failed > 0) {
    lines.push({
      label: `Nieudane maile z zamówieniami: ${finance.order_mail_failed}`,
      href: "/contracts?view=order-mail",
    });
  }
  return (
    <>
      {lines.length > 0 && (
        <CountSection
          title="Finanse — do zrobienia"
          hint="Liczby z modułu Finanse i skrzynki zamówień."
          count={todo + finance.gaps_open + finance.pdfs_new + finance.order_mail_failed}
          lines={lines}
        />
      )}
      {finance.hired_without_order.length > 0 && (
        <Section
          title="Zatrudnieni bez zamówienia"
          hint="Kandydat jest na „Zatrudniony”, a zamówienie nie jest uzupełnione."
          count={finance.hired_without_order_total}
          rows={finance.hired_without_order.length}
          expanded={expanded["fin_hired"] === true}
          onToggle={() => onToggle("fin_hired")}
        >
          {shown("fin_hired", finance.hired_without_order).map((row) => (
            <PairRowItem
              key={`${row.job_id}-${row.candidate_id}`}
              row={row}
              aside={<Since since={row.since} />}
            />
          ))}
        </Section>
      )}
    </>
  );
}

/** „Czeka na klienta” — DL czeka na odpowiedź klienta po wysłaniu CV. */
export function BoardFlowOthers({ flow, expanded, onToggle, shown }: { flow: FlowBlock | null | undefined } & Toggle) {
  if (!flow || flow.waiting_client.length === 0) return null;
  return (
    <Section
      title="Czeka na klienta"
      hint={`CV wysłane ponad ${flow.waiting_client_days} dni temu — klient się nie odezwał.`}
      count={flow.waiting_client.length}
      expanded={expanded["flow_waiting_client"] === true}
      onToggle={() => onToggle("flow_waiting_client")}
    >
      {shown("flow_waiting_client", flow.waiting_client).map((row) => (
        <PairRowItem key={`${row.job_id}-${row.candidate_id}`} row={row} aside={<Since since={row.since} />} />
      ))}
    </Section>
  );
}
