"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Check, ExternalLink } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import {
  useApprovalDetail,
  useApprovalList,
  type ApprovalContext,
  type ApprovalRequestRow,
} from "@/lib/api/hr-approvals";
import { formatIsoDatePl, formatMomentPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";

import {
  afterDecision,
  approveLabel,
  canChangeAmount,
  isUrgent,
  moneyPl,
  payoutLine,
  stageLine,
} from "./approvals-format";
import { DecisionDialog, type DecisionMode } from "./DecisionDialog";
import { KindIcon } from "./KindIcon";
import { TopupsPanel } from "./TopupsPanel";

const LABEL = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

function InboxRow({
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

function ConsentDetail({
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

/**
 * „Akceptacje → Zgody” (makieta 20.10.2026): zgody, o których czytający może
 * teraz zdecydować — lista po lewej („Potrzebne do jutra”, „Pozostałe”),
 * szczegół z liczbami „NEXUS sprawdził” po prawej. Link z maila
 * (`?request=…&decide=approve|reject`) otwiera zgodę z oknem decyzji.
 */
/** Skrzynka zgód z dopłatami do decyzji na górze (etap 3, 0486). */
export function ConsentsInbox() {
  return (
    <div className="space-y-3">
      <TopupsPanel />
      <ConsentsInboxList />
    </div>
  );
}

function ConsentsInboxList() {
  const params = useSearchParams();
  const inbox = useApprovalList("inbox");
  const linked = Number(params.get("request"));
  const [selectedId, setSelectedId] = useState<number | null>(
    Number.isInteger(linked) && linked > 0 ? linked : null,
  );
  const [decision, setDecision] = useState<{
    row: ApprovalRequestRow;
    mode: DecisionMode;
  } | null>(null);
  const openedFromLink = useRef(false);
  const rows = inbox.data ?? [];
  const today = warsawToday();
  const urgent = rows.filter((row) => isUrgent(row, today));
  const rest = rows.filter((row) => !isUrgent(row, today));
  const current = rows.find((row) => row.id === selectedId) ?? rows[0];

  // Przycisk z maila: raz po wczytaniu, tylko gdy zgoda nadal czeka na tę osobę.
  useEffect(() => {
    if (openedFromLink.current || !inbox.isSuccess) return;
    openedFromLink.current = true;
    const wanted = params.get("decide");
    const row = (inbox.data ?? []).find((item) => item.id === linked);
    if (row && row.can_decide && (wanted === "approve" || wanted === "reject")) {
      setDecision({ row, mode: wanted });
    }
  }, [inbox.isSuccess, inbox.data, linked, params]);

  const state = resolveViewState({
    isLoading: inbox.isLoading,
    isError: inbox.isError,
    error: inbox.error,
    isSuccess: inbox.isSuccess,
    isEmpty: rows.length === 0,
  });
  if (state === "loading") {
    return <p className="py-4 text-sm text-muted-foreground">Wczytywanie zgód…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => inbox.refetch()} />;
  }
  if (state === "empty" || !current) {
    return (
      <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        Nic nie czeka na Twoją decyzję.
        {Number.isInteger(linked) && linked > 0
          ? " Zgoda z linku jest już rozpatrzona albo decyduje o niej ktoś inny."
          : null}
      </p>
    );
  }

  const group = (title: string, items: ApprovalRequestRow[]) =>
    items.length === 0 ? null : (
      <div>
        <h3 className={cn(LABEL, "px-3.5 py-2.5")}>{title}</h3>
        <ul aria-label={title}>
          {items.map((row) => (
            <InboxRow
              key={row.id}
              row={row}
              active={row.id === current.id}
              onSelect={() => setSelectedId(row.id)}
            />
          ))}
        </ul>
      </div>
    );

  return (
    <>
      <div
        data-help="hr.consents.inbox"
        className="flex flex-wrap overflow-hidden rounded-xl border border-border bg-card"
      >
        <div className="min-w-0 flex-[1_1_340px] border-b border-border/60 md:max-w-[460px] md:border-b-0 md:border-r">
          {group("Potrzebne do jutra", urgent)}
          {group(urgent.length > 0 ? "Pozostałe" : "Do decyzji", rest)}
          <p className="border-t border-border/60 px-3.5 py-2.5 text-xs text-muted-foreground">
            Wynagrodzenie z reguł umowy (placementy, ligi, reguły Płac) tu nie trafia — liczy się samo.
          </p>
        </div>
        <ConsentDetail
          key={current.id}
          row={current}
          onDecide={(mode) => setDecision({ row: current, mode })}
        />
      </div>
      <DecisionDialog
        row={decision?.row ?? null}
        mode={decision?.mode ?? null}
        onClose={() => setDecision(null)}
      />
    </>
  );
}
