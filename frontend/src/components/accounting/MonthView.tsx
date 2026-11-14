"use client";

import Link from "next/link";

import { InlineStats, QueryStateNotice, StatusDot, type StatusDotTone } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  useClosePeriod,
  useClosing,
  useCreateYear,
  useReopenPeriod,
  useTrialBalance,
  type ClosingDeadline,
  type ClosingState,
} from "@/lib/api/accounting";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard, useAccounting } from "./AccountingShell";
import { datePl, findPeriod, gr, monthTitle } from "./ledger-model";

const STATUS_TONE: Record<string, StatusDotTone> = { open: "success", closed: "neutral" };
const CHECK_TONE: Record<ClosingState, StatusDotTone> = {
  ok: "success",
  todo: "warning",
  problem: "danger",
  later: "neutral",
};
const DAY_MS = 24 * 60 * 60 * 1000;

function dayNumber(iso: string): number {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return Date.UTC(y, m - 1, d) / DAY_MS;
}

/** „za 5 dni”, „jutro”, „dziś”, „minął” + przesunięcie z dnia wolnego. */
export function deadlineNote(deadline: ClosingDeadline, today: string): string {
  const left = dayNumber(deadline.due) - dayNumber(today);
  const when = left > 1 ? `za ${left} dni` : left === 1 ? "jutro" : left === 0 ? "dziś" : "minął";
  const moved =
    deadline.due !== deadline.nominal ? `, przesunięty z ${datePl(deadline.nominal).slice(0, 5)} (dzień wolny)` : "";
  return `${when}${moved}`;
}

export function MonthView() {
  const { config, period, setPeriod } = useAccounting();
  const { showToast } = useToast();
  const { askConfirm, askReason, confirmDialog } = useConfirmV2();
  const { year, period: current } = findPeriod(config, period);
  const checklist = useClosing(period.year, period.month, year != null);
  const trial = useTrialBalance(year ? period.year : null, period.month, period.month, "synthetic");
  const createYear = useCreateYear();
  const close = useClosePeriod();
  const reopen = useReopenPeriod();
  const title = monthTitle(period.year, period.month);

  if (!year) {
    return (
      <div className="space-y-3">
        <div className="rounded-lg border border-dashed border-border px-6 py-10 text-center">
          <p className="text-sm font-medium">Nie ma roku obrotowego {period.year}</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
            Rok zakłada osoba z listy „Księgowi”. Nowy rok ma 12 otwartych okresów i tryb „Symfonia FK — NEXUS
            przygotowuje paczki”; tryb zmienia administrator.
          </p>
          {config.me.approver ? (
            <Button
              size="sm"
              className="mt-3"
              loading={createYear.isPending}
              onClick={() =>
                createYear.mutate(
                  { year: period.year },
                  {
                    onSuccess: () => showToast(`Założono rok obrotowy ${period.year}.`),
                    onError: (error) => showToast(apiErrorMessage(error, "Nie udało się założyć roku."), "error"),
                  },
                )
              }
            >
              Załóż rok {period.year}
            </Button>
          ) : null}
        </div>
        {config.years.length ? (
          <p className="text-[13px] text-muted-foreground">
            Założone lata:{" "}
            {config.years.map((item) => (
              <button
                key={item.id}
                type="button"
                className="mr-2 text-primary hover:underline"
                onClick={() => setPeriod({ year: item.year, month: period.month })}
              >
                {item.year}
              </button>
            ))}
          </p>
        ) : null}
      </div>
    );
  }

  const drafts = current?.drafts ?? 0;
  const approved = current?.approved ?? 0;
  const closed = current?.status === "closed";
  const query = `?year=${period.year}&month=${period.month}`;

  const closeMonth = async () => {
    if (!current) return;
    const ok = await askConfirm({
      title: `Zamknąć ${title.toLowerCase()}?`,
      description:
        "Zamknięty okres nie przyjmuje dokumentów ani zatwierdzeń. Ponownie otworzyć go może tylko administrator, z powodem w śladzie.",
      confirmLabel: "Zamknij okres",
    });
    if (!ok) return;
    close.mutate(current.id, {
      onSuccess: () => showToast(`Zamknięto ${title.toLowerCase()}.`),
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zamknąć okresu."), "error"),
    });
  };

  const reopenMonth = async () => {
    if (!current) return;
    const reason = await askReason({
      title: `Otworzyć ponownie ${title.toLowerCase()}?`,
      description: "Powód zostaje w śladzie okresu.",
      confirmLabel: "Otwórz okres",
      field: { label: "Powód", placeholder: "np. korekta faktury z tego miesiąca", minLength: 3, maxLength: 500 },
    });
    if (!reason) return;
    reopen.mutate(
      { periodId: current.id, reason },
      {
        onSuccess: () => showToast(`Otwarto ponownie ${title.toLowerCase()}.`),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się otworzyć okresu."), "error"),
      },
    );
  };

  return (
    <div className="space-y-3.5">
      <InlineStats
        stats={[
          { id: "docs", label: "Dokumenty w miesiącu", value: drafts + approved },
          { id: "drafts", label: "W buforze", value: drafts },
          {
            id: "balance",
            label: "Obroty miesiąca Wn = Ma",
            value: trial.isSuccess ? (
              <span className={cn(trial.data.balanced ? "text-success" : "text-destructive")}>
                {gr(trial.data.totals.wn)} {trial.data.balanced ? "✓" : "≠"}
              </span>
            ) : (
              "—"
            ),
          },
          { id: "journal", label: `Pozycje dziennika ${year.year}`, value: year.journal_entries },
        ]}
      />

      <div className="grid gap-3.5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <SectionCard title={`Lista zamknięcia — ${title.toLowerCase()}`} aside="co zostało przed zamknięciem okresu">
          {checklist.isError ? (
            <QueryStateNotice state="error" onRetry={() => checklist.refetch()} className="m-3" />
          ) : !checklist.isSuccess ? (
            <p className="px-3.5 py-3 text-[13px] text-muted-foreground">Wczytywanie listy…</p>
          ) : (
            <ul className="divide-y divide-border/70">
              {checklist.data.items.map((item) => (
                <li key={item.key} className="flex items-start justify-between gap-3 px-3.5 py-2">
                  <div className="min-w-0">
                    <StatusDot tone={CHECK_TONE[item.state]}>
                      <span className="text-[13px] font-medium">{item.label}</span>
                    </StatusDot>
                    <span className={cn(CALM_SUBLINE, "pl-3.5")}>{item.detail}</span>
                  </div>
                  {item.href && item.state !== "ok" ? (
                    <Link href={item.href} className="shrink-0 text-[13px] text-primary hover:underline">
                      Przejdź
                    </Link>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </SectionCard>

        <div className="space-y-3.5">
          <SectionCard title="Zamknięcie okresu" aside={title}>
            <div className="space-y-2.5 px-3.5 py-3 text-[13px]">
              <StatusDot
                tone={STATUS_TONE[current?.status ?? "open"]}
                note={
                  closed
                    ? current?.closed_at
                      ? `zamknięty ${current.closed_at.slice(0, 10).split("-").reverse().join(".")}`
                      : undefined
                    : current?.reopen_reason
                      ? `otwarty ponownie: ${current.reopen_reason}`
                      : undefined
                }
              >
                {closed ? "Okres zamknięty" : "Okres otwarty"}
              </StatusDot>
              <ul className="space-y-1.5">
                <li>
                  <StatusDot tone={drafts ? "warning" : "success"} note={drafts ? "zatwierdź albo usuń" : undefined}>
                    {drafts ? `W buforze: ${drafts}` : "Bufor pusty"}
                  </StatusDot>
                </li>
                <li>
                  <StatusDot tone={trial.data?.balanced === false ? "danger" : "success"}>
                    {trial.data?.balanced === false ? "Obroty Wn ≠ Ma" : "Obroty Wn = Ma"}
                  </StatusDot>
                </li>
              </ul>
              <div className="flex flex-wrap gap-2 pt-1">
                {drafts ? (
                  <Button size="sm" variant="outline" asChild>
                    <Link href={`/accounting/documents${query}&status=draft`}>Pokaż bufor</Link>
                  </Button>
                ) : null}
                {!closed && config.me.approver ? (
                  <Button
                    size="sm"
                    disabled={drafts > 0}
                    title={drafts > 0 ? "Najpierw zatwierdź albo usuń dokumenty z bufora" : undefined}
                    loading={close.isPending}
                    onClick={() => void closeMonth()}
                  >
                    Zamknij okres
                  </Button>
                ) : null}
                {closed && config.me.admin ? (
                  <Button size="sm" variant="outline" loading={reopen.isPending} onClick={() => void reopenMonth()}>
                    Otwórz ponownie
                  </Button>
                ) : null}
              </div>
              {!config.me.approver ? (
                <p className="text-[12px] text-muted-foreground">
                  Zatwierdza i zamyka osoba z listy „Księgowi” albo administrator.
                </p>
              ) : null}
            </div>
          </SectionCard>
          {checklist.isSuccess ? (
            <SectionCard title="Terminy za miesiąc" aside="ZUS, PPK, PIT-4, VAT">
              <ul className="divide-y divide-border/70">
                {checklist.data.deadlines.map((deadline) => (
                  <li key={deadline.key} className="px-3.5 py-2 text-[13px]" title={deadline.basis}>
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="min-w-0 font-medium">{deadline.label}</span>
                      <span className="shrink-0 tabular-nums">{datePl(deadline.due)}</span>
                    </span>
                    <span className={CALM_SUBLINE}>{deadlineNote(deadline, config.today)}</span>
                  </li>
                ))}
              </ul>
              <p className="border-t border-border/70 px-3.5 py-2 text-[12px] text-muted-foreground">
                Kwoty dojdą z listą płac (K3c z pliku Enovy, potem K7) i rozliczeniem VAT (K5).
              </p>
            </SectionCard>
          ) : null}
        </div>
      </div>
      {confirmDialog}
    </div>
  );
}
