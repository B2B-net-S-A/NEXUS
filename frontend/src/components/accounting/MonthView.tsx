"use client";

import Link from "next/link";

import { InlineStats, QueryStateNotice, StatusDot, type StatusDotTone } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  useClosePeriod,
  useCreateYear,
  useDocuments,
  useReopenPeriod,
  useTrialBalance,
  type DocType,
} from "@/lib/api/accounting";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard, useAccounting } from "./AccountingShell";
import { findPeriod, gr, monthTitle } from "./ledger-model";

interface SourceRow {
  types: DocType[];
  name: string;
  origin: string;
  stage: string | null;
}

/**
 * Źródła dokumentów miesiąca. Etap = kiedy NEXUS zacznie robić te dokumenty
 * sam (plan K1–K9); do tego czasu księguje je Symfonia, a w NEXUSIE są tylko
 * PK i BO zakładane ręcznie.
 */
const SOURCES: readonly SourceRow[] = [
  { types: ["PK", "BO"], name: "Polecenia księgowania i bilans otwarcia", origin: "ręcznie, na ekranie Dokumenty", stage: null },
  { types: ["FVZ"], name: "Faktury kosztowe", origin: "kolejka kosztów i dekret E2 → Źródła", stage: null },
  { types: ["FVS"], name: "Faktury sprzedaży", origin: "KSeF (eBI24 i NEXUS) → Źródła", stage: null },
  { types: ["RMK", "PK"], name: "Polisy, podatki, PK cykliczne", origin: "automaty co miesiąc", stage: "K3" },
  { types: ["WB"], name: "Wyciągi bankowe", origin: "import CAMT.053 / MT940", stage: "K4" },
  { types: ["VAT"], name: "Rozliczenie VAT", origin: "rejestry VAT i JPK_V7M", stage: "K5" },
  { types: ["AM"], name: "Amortyzacja", origin: "ewidencja środków trwałych", stage: "K6" },
  { types: ["LP"], name: "Lista płac", origin: "Płace: UoP i zlecenia", stage: "K7" },
];

const STATUS_TONE: Record<string, StatusDotTone> = { open: "success", closed: "neutral" };

export function MonthView() {
  const { config, period, setPeriod } = useAccounting();
  const { showToast } = useToast();
  const { askConfirm, askReason, confirmDialog } = useConfirmV2();
  const { year, period: current } = findPeriod(config, period);
  const docs = useDocuments(
    { year: period.year, month: period.month, docType: null, status: null, q: "", offset: 0 },
    year != null,
  );
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

  const counts = docs.data?.counts ?? {};
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
        <SectionCard title={`Źródła dokumentów — ${title.toLowerCase()}`} aside="co robi NEXUS, a co jeszcze Symfonia">
          {docs.isError ? (
            <QueryStateNotice state="error" onRetry={() => docs.refetch()} className="m-3" />
          ) : (
            <table className="w-full table-fixed text-sm">
              <thead>
                <tr className="border-b border-border/70">
                  <th className={cn(CALM_HEAD, "px-3.5 py-2 text-left")}>Źródło</th>
                  <th className={cn(CALM_HEAD, "w-[14%] px-2 py-2 text-right")}>Dok.</th>
                  <th className={cn(CALM_HEAD, "w-[30%] px-3.5 py-2 text-left")}>Stan</th>
                </tr>
              </thead>
              <tbody>
                {SOURCES.map((source) => {
                  const count = source.stage
                    ? source.types.filter((type) => type !== "PK").reduce((sum, type) => sum + (counts[type] ?? 0), 0)
                    : source.types.reduce((sum, type) => sum + (counts[type] ?? 0), 0);
                  return (
                    <tr key={source.name} className={cn(CALM_ROW, "align-top last:border-0")}>
                      <td className="min-w-0 px-3.5 py-2">
                        <span className="block font-medium">{source.name}</span>
                        <span className={CALM_SUBLINE}>{source.origin}</span>
                      </td>
                      <td className={cn(CALM_AMOUNT, "px-2 py-2")}>{docs.isSuccess ? count : "—"}</td>
                      <td className="px-3.5 py-2">
                        {source.stage ? (
                          <StatusDot tone="neutral" note="do tego czasu księguje Symfonia">
                            Etap {source.stage}
                          </StatusDot>
                        ) : (
                          <StatusDot tone="success">Działa</StatusDot>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </SectionCard>

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
      </div>
      {confirmDialog}
    </div>
  );
}
