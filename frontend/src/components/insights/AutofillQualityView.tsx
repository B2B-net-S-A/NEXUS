"use client";

/**
 * „Jakość podpowiedzi systemu” (makiety B2 i B3, 23.10.2026). Liczby z ostatnich
 * dni (`GET /api/autofill-quality/summary`) i raporty poniedziałkowe
 * z propozycjami poprawek (`GET …/reports`). „Robimy / Nie” klika admin albo
 * Head of Recruitment. Odrzucenia przez brak danych i sprawy osoby są osobno —
 * nie obciążają wyszukiwania.
 */

import Link from "next/link";
import { useState } from "react";
import { useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  type AutofillBucket,
  type AutofillProposal,
  type AutofillQualityReport,
  type AutofillQualitySummary,
  useAutofillQualityReports,
  useAutofillQualitySummary,
  useDecideAutofillProposal,
} from "@/lib/api/autofillQuality";
import { countPl } from "@/lib/plural-pl";
import { cn, formatDate } from "@/lib/utils";
import { getUserRoles, useAuthStore } from "@/store/auth";

type Days = "7" | "30" | "90";

const BUCKET_BAR: Record<AutofillBucket, string> = {
  search: "bg-destructive",
  data: "bg-warning",
  person: "bg-muted-foreground",
  other: "bg-muted-foreground/60",
};

const BUCKET_HINT: Record<AutofillBucket, string> = {
  search: "to poprawiamy w wyszukiwaniu",
  data: "to uzupełniamy w bazie",
  person: "nie liczymy jako błąd",
  other: "z opisem rekrutera",
};

const KIND_LABEL: Record<AutofillProposal["kind"], string> = {
  search: "błąd wyszukiwania",
  data: "brak danych",
  person: "sprawa osoby",
};

const KIND_TONE: Record<AutofillProposal["kind"], string> = {
  search: "bg-destructive-muted text-destructive-muted-foreground",
  data: "bg-warning-muted text-warning-muted-foreground",
  person: "bg-muted text-muted-foreground",
};

function pct(value: number | null | undefined): string {
  return value == null ? "—" : `${String(value).replace(".", ",")}%`;
}

function Tile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2.5">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      <p className="text-xs text-muted-foreground">{sub}</p>
    </div>
  );
}

export function SummaryTiles({ data }: { data: AutofillQualitySummary }) {
  const { system, manual } = data.verified;
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" data-testid="autofill-quality-tiles">
      <Tile label="Dodane przez system" value={String(data.added)} sub="osoby w „Nowych”" />
      <Tile
        label="Z decyzją"
        value={pct(data.decided_pct)}
        sub={`${countPl(data.waiting_now, "osoba czeka", "osoby czekają", "osób czeka")} > 2 dni`}
      />
      <Tile label="„Dzwonię”" value={pct(data.called_pct)} sub="z osób z decyzją" />
      <Tile
        label="Doszli do „Zweryfikowany”"
        value={pct(system.verified_pct)}
        sub={`dodani ręcznie: ${pct(manual.verified_pct)}`}
      />
      <Tile
        label="Błąd wyszukiwania"
        value={pct(data.search_error_pct)}
        sub={`z ${countPl(data.rejected, "odrzucenia", "odrzuceń", "odrzuceń")}`}
      />
    </div>
  );
}

export function BucketBars({ data }: { data: AutofillQualitySummary }) {
  const max = Math.max(1, ...data.buckets.flatMap((b) => b.reasons.map((r) => r.count)));
  return (
    <section aria-label="Powody odrzuceń osób od systemu" className="space-y-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">Powody odrzuceń osób od systemu</h2>
      {data.rejected === 0 ? (
        <p className="text-sm text-muted-foreground">W tym okresie nikt nie odrzucił osoby od systemu.</p>
      ) : (
        data.buckets
          .filter((b) => b.total > 0)
          .map((bucket) => (
            <div key={bucket.bucket} className="space-y-1">
              <div className="flex items-baseline gap-2">
                <span className="text-sm font-semibold">{bucket.label}</span>
                <span className="text-xs text-muted-foreground">{BUCKET_HINT[bucket.bucket]}</span>
                <span className="ml-auto text-sm font-semibold tabular-nums">{bucket.total}</span>
              </div>
              <ul className="space-y-1">
                {bucket.reasons.map((reason) => (
                  <li key={reason.reason} className="flex items-center gap-2 text-sm">
                    <span className="w-56 shrink-0 truncate">{reason.label}</span>
                    <span className="h-2 flex-1 rounded bg-muted" aria-hidden="true">
                      <span
                        className={cn("block h-2 rounded", BUCKET_BAR[bucket.bucket])}
                        style={{ width: `${(100 * reason.count) / max}%` }}
                      />
                    </span>
                    <span className="w-10 text-right tabular-nums text-muted-foreground">{reason.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))
      )}
    </section>
  );
}

function WorstJobs({ data }: { data: AutofillQualitySummary }) {
  return (
    <section aria-label="Najsłabiej trafione rekrutacje" className="rounded-lg border border-border bg-card p-4">
      <h2 className="pb-2 text-sm font-semibold">Najsłabiej trafione rekrutacje</h2>
      {data.worst_jobs.length === 0 ? (
        <p className="text-sm text-muted-foreground">Za mało odrzuceń na rekrutację (od 3), żeby coś wskazać.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="py-1 font-medium">Rekrutacja</th>
                <th className="py-1 text-right font-medium">Błąd wyszukiwania</th>
                <th className="py-1 pl-3 font-medium">Główny powód</th>
              </tr>
            </thead>
            <tbody>
              {data.worst_jobs.map((job) => (
                <tr key={job.job_id} className="border-t border-border">
                  <td className="py-1.5">
                    <Link href={`/jobs/${job.job_id}`} className="hover:underline">
                      {job.job_title}
                    </Link>
                  </td>
                  <td className="py-1.5 text-right tabular-nums">
                    {pct(job.search_pct)} <span className="text-muted-foreground">({job.search_errors} z {job.feedback})</span>
                  </td>
                  <td className="py-1.5 pl-3">{job.top_reason_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function weekLabel(report: AutofillQualityReport): string {
  const start = new Date(`${report.week_start}T00:00:00`);
  const end = new Date(start.getTime() + 6 * 86_400_000);
  return `${formatDate(start.toISOString())}–${formatDate(end.toISOString())}`;
}

export function ReportProposals({
  report,
  canDecide,
}: {
  report: AutofillQualityReport;
  canDecide: boolean;
}) {
  const decide = useDecideAutofillProposal();
  const { showError } = useToast();
  return (
    <section aria-label="Raport poniedziałkowy" className="space-y-2 rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold">Raport {weekLabel(report)} · co poprawić</h2>
        <span className="text-xs text-muted-foreground">
          {report.from_model ? "propozycje z AI na liczbach kodu" : "propozycje z reguł"}
        </span>
      </div>
      {report.proposals.length === 0 ? (
        <p className="text-sm text-muted-foreground">W tym tygodniu nie było odrzuceń — nic do poprawy.</p>
      ) : (
        <ol className="space-y-2">
          {report.proposals.map((proposal, index) => (
            <li
              key={`${report.id}-${index}`}
              className="flex flex-wrap items-start gap-3 rounded-md border border-border p-3"
              data-testid="autofill-proposal"
            >
              <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", KIND_TONE[proposal.kind])}>
                {KIND_LABEL[proposal.kind]}
              </span>
              <div className="min-w-[14rem] flex-1 space-y-1 text-sm">
                <p className="font-semibold">{proposal.title}</p>
                {proposal.evidence ? <p className="text-muted-foreground">{proposal.evidence}</p> : null}
                {proposal.fix ? (
                  <p>
                    <span className="text-muted-foreground">Propozycja:</span> {proposal.fix}
                  </p>
                ) : null}
              </div>
              {canDecide ? (
                <div className="flex shrink-0 gap-1" role="group" aria-label={`Decyzja: ${proposal.title}`}>
                  {(["yes", "no"] as const).map((value) => (
                    <Button
                      key={value}
                      size="sm"
                      variant={proposal.decision === value ? "primary" : "outline"}
                      aria-pressed={proposal.decision === value}
                      disabled={decide.isPending}
                      onClick={() =>
                        decide.mutate(
                          {
                            reportId: report.id,
                            index,
                            decision: proposal.decision === value ? null : value,
                          },
                          { onError: (e) => showError(apiErrorMessage(e, "Nie udało się zapisać decyzji.")) },
                        )
                      }
                    >
                      {value === "yes" ? "Robimy" : "Nie"}
                    </Button>
                  ))}
                </div>
              ) : proposal.decision ? (
                <span className="text-xs font-semibold text-muted-foreground">
                  {proposal.decision === "yes" ? "Robimy" : "Nie robimy"}
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function AutofillQualityView() {
  const searchParams = useSearchParams();
  const [days, setDays] = useState<Days>("7");
  const summary = useAutofillQualitySummary(Number(days));
  const reports = useAutofillQualityReports();
  const user = useAuthStore((s) => s.user);
  const roles = getUserRoles(user);
  const canDecide = roles.includes("admin") || roles.includes("head_of_recruitment");
  const wanted = Number(searchParams.get("report"));
  const report =
    reports.data?.find((r) => r.id === wanted) ?? (reports.isSuccess ? reports.data[0] : undefined);

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <Link href="/insights" className="text-sm text-primary hover:underline">
            ‹ Insights
          </Link>
          <h1 className="text-2xl font-bold tracking-tight">Jakość podpowiedzi systemu</h1>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Osoby, które system sam dodał do „Nowych”, i dlaczego rekruterzy je odrzucają. Braki danych
            i sprawy osoby są liczone osobno — nie obciążają wyszukiwania.
          </p>
        </div>
        <SegmentedRadio<Days>
          label="Okres"
          value={days}
          onChange={setDays}
          options={[
            { value: "7", label: "7 dni" },
            { value: "30", label: "30 dni" },
            { value: "90", label: "90 dni" },
          ]}
        />
      </div>

      {summary.isError ? (
        <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {apiErrorMessage(summary.error, "Nie udało się policzyć jakości podpowiedzi — odśwież stronę.")}
        </p>
      ) : summary.isSuccess ? (
        <>
          <SummaryTiles data={summary.data} />
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
            <BucketBars data={summary.data} />
            <WorstJobs data={summary.data} />
          </div>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">Liczę…</p>
      )}

      {reports.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(reports.error, "Nie udało się wczytać raportów.")}
        </p>
      ) : report ? (
        <ReportProposals report={report} canDecide={canDecide} />
      ) : reports.isSuccess ? (
        <p className="text-sm text-muted-foreground">
          Pierwszy raport przyjdzie w poniedziałek po tygodniu pracy silnika.
        </p>
      ) : null}
    </div>
  );
}
