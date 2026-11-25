"use client";

/**
 * Insights → „Przegrane” (decyzje Artura 25.11.2026): moduł na comiesięczne
 * spotkanie z Delivery Leadami. Fakty o przegranych liczy NEXUS, DL dopowiada
 * „Dlaczego?”, wnioski „ten klient” zostają zasadami klienta, a model AI dokłada
 * rady. Reguła: `docs/claude/finanse-insights/przegrane-przeglad-z-dl.md`.
 */

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { PeriodPicker } from "@/components/insights/PeriodPicker";
import { SectionError, LoadingSpinner } from "@/components/insights/sections/_shared";
import { useInsightsPeriod } from "@/components/insights/useInsightsPeriod";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import type { InsightsPeriodParams } from "@/lib/insights-api";
import {
  LOST_STAGES,
  lostReviewApi,
  lostReviewKeys,
  plNumber,
  type LostReviewClient,
  type LostReviewLesson,
  type LostReviewResponse,
} from "@/lib/lost-review";
import { cn } from "@/lib/utils";

import { LostReviewAiPanel } from "../lost-review/LostReviewAiPanel";
import {
  ClientsChart,
  CountBars,
  Panel,
  STAGE_TONE,
  StageBar,
  TrendChart,
} from "../lost-review/LostReviewCharts";
import { LostReviewJobCard } from "../lost-review/LostReviewJobCard";
import { Tile, TileRow, ViewHeader } from "./ViewKit";

const DEFAULT_PERIOD: InsightsPeriodParams = { period: "month", offset: 0 };

export function PrzegraneView() {
  const { period, setPeriod } = useInsightsPeriod(DEFAULT_PERIOD);
  const query = useQuery({
    queryKey: lostReviewKeys.review(period),
    queryFn: () => lostReviewApi.get(period),
  });

  return (
    <div className="space-y-6">
      <ViewHeader
        question="Przegrane — przegląd z Delivery Leadami"
        lede={
          query.data
            ? `${capitalize(query.data.period_label)}. Przegrana = rekrutację wzięła inna firma albo NEXUS zamknął ją po 28 dniach bez ruchu.`
            : "Gdzie i dlaczego przegrywamy rekrutacje, ogólnie i u każdego klienta, i co zmieniamy."
        }
        actions={<PeriodPicker value={period} onChange={setPeriod} defaultValue={DEFAULT_PERIOD} hideHistoryNote />}
      />
      {query.isPending ? <LoadingSpinner /> : null}
      {query.isError ? (
        <SectionError label="Przegrane" error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {query.isSuccess ? <Body data={query.data} period={period} /> : null}
    </div>
  );
}

function capitalize(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

function Body({ data, period }: { data: LostReviewResponse; period: InsightsPeriodParams }) {
  const searchParams = useSearchParams();
  const focusJob = Number(searchParams.get("job")) || null;
  const [dl, setDl] = useState<string>("all");
  const [onlyOpen, setOnlyOpen] = useState(false);
  const { counts, compare } = data;
  const lostTotal = counts.lost;

  const dls = useMemo(
    () => [...new Set(data.jobs.map((j) => j.dl_name ?? "bez DL"))].sort((a, b) => a.localeCompare(b, "pl")),
    [data.jobs],
  );
  const jobs = data.jobs.filter(
    (j) =>
      (dl === "all" || (j.dl_name ?? "bez DL") === dl) &&
      (!onlyOpen || (j.why.length === 0 && j.source !== "client") || j.source === "unknown"),
  );

  useEffect(() => {
    if (!focusJob) return;
    const el = document.getElementById(`lost-job-${focusJob}`);
    el?.scrollIntoView({ block: "center" });
  }, [focusJob, data]);

  return (
    <div className="space-y-6">
      <TileRow>
        <Tile
          label="Przegrane"
          value={String(lostTotal)}
          note={`${counts.competitor} konkurencja · ${counts.idle} NEXUS po 28 dniach`}
        />
        <Tile label="Wygrane" value={String(counts.won)} note="z zatrudnieniem od nas" />
        <Tile
          label="Hit ratio"
          value={data.hit_ratio === null ? "—" : `${plNumber(data.hit_ratio)}%`}
          reference="cel DL: 30%"
        />
        <Tile
          label="Wiemy, co klient myśli"
          value={`${data.known} z ${lostTotal}`}
          note="przegrane z oceną naszej osoby albo „Klient powiedział”"
        />
      </TileRow>

      <LostReviewAiPanel key={JSON.stringify(period)} period={period} findings={data.findings} hasLosses={lostTotal > 0} />

      <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
        <Panel title="Na którym etapie przegrywamy" lede="Najdalszy etap, do którego doszła nasza osoba.">
          <StageBar stages={data.stages} total={lostTotal} />
        </Panel>
        <Panel title="Wygrane a przegrane" lede="Mediany na rekrutację.">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="py-1 font-medium" />
                <th className="py-1 text-right font-medium">Wygrane</th>
                <th className="py-1 text-right font-medium">Przegrane</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              <CompareRow
                label="Pierwsze CV po"
                won={compare.won.first_cv_days === null ? "—" : `${plNumber(compare.won.first_cv_days)} dn.`}
                lost={compare.lost.first_cv_days === null ? "—" : `${plNumber(compare.lost.first_cv_days)} dn.`}
              />
              <CompareRow label="CV na rekrutację" won={plNumber(compare.won.cvs)} lost={plNumber(compare.lost.cvs)} />
              <CompareRow
                label="Z rozmową u klienta"
                won={compare.won.interview_share === null ? "—" : `${compare.won.interview_share}%`}
                lost={compare.lost.interview_share === null ? "—" : `${compare.lost.interview_share}%`}
              />
            </tbody>
          </table>
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Wygrane i przegrane w czasie" lede="Do sześciu miesięcy do końca okresu, od 12.10.2026.">
          <TrendChart months={data.trend} />
        </Panel>
        <Panel title="Klienci" lede="Najwięcej zamknięć w okresie.">
          <ClientsChart clients={data.clients} />
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel
          title="Co zdecydowało — według DL"
          lede={`Opisane ${data.why_filled} z ${lostTotal} przegranych · klient powiedział: ${data.source_counts.client} · nie wiemy: ${data.source_counts.unknown}`}
        >
          <CountBars
            items={data.why_counts}
            empty="Jeszcze nikt nie zaznaczył „Dlaczego?”. Zróbcie to na liście niżej albo przy zamknięciu."
            testId="lost-review-why"
          />
        </Panel>
        <Panel title="Co klient mówi o naszych osobach" lede="Odrzucenia „Odrzuca klient” z powodem, bez automatycznych przy zamknięciu.">
          <CountBars
            items={data.client_verdicts}
            empty="Klient nie ocenił nikogo z naszych w przegranych tego okresu."
            testId="lost-review-verdicts"
          />
        </Panel>
      </div>

      <ClientsTable clients={data.clients} />

      <section className="space-y-2" data-testid="lost-review-list">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h3 className="text-base font-semibold text-foreground">
              Do omówienia <span className="text-muted-foreground">· {jobs.length}</span>
            </h3>
            <p className="text-sm text-muted-foreground">
              Fakty liczy NEXUS. DL zaznacza „Dlaczego?” i wpisuje, co zmieniamy — zapis od razu.
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm" data-tour="insights.lost.only-open">
            <input
              type="checkbox"
              checked={onlyOpen}
              onChange={(e) => setOnlyOpen(e.target.checked)}
              className="accent-primary"
            />
            Tylko bez odpowiedzi
          </label>
        </div>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Delivery Lead">
          {["all", ...dls].map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={dl === d}
              onClick={() => setDl(d)}
              className={cn(
                "rounded-full border px-2.5 py-1 text-xs",
                dl === d ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:bg-muted",
              )}
            >
              {d === "all" ? "Wszyscy DL" : d}
            </button>
          ))}
        </div>
        {jobs.length === 0 ? (
          <p className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
            {lostTotal === 0 ? "W tym okresie nie ma przegranych rekrutacji." : "Nic nie pasuje do filtra."}
          </p>
        ) : (
          <div className="space-y-2">
            {jobs.map((j) => (
              <LostReviewJobCard
                key={j.job_id}
                job={j}
                highlighted={focusJob === j.job_id}
              />
            ))}
          </div>
        )}
      </section>

      <LessonsSection lessons={data.lessons} clients={data.clients} />
    </div>
  );
}

function CompareRow({ label, won, lost }: { label: string; won: string; lost: string }) {
  return (
    <tr className="border-t border-border">
      <td className="py-1.5 text-muted-foreground">{label}</td>
      <td className="py-1.5 text-right font-medium">{won}</td>
      <td className="py-1.5 text-right font-medium">{lost}</td>
    </tr>
  );
}

function effectText(lesson: LostReviewLesson): string | null {
  const e = lesson.effect;
  if (!e) return null;
  const fmt = (s: { won: number; lost: number; hit_ratio: number | null }) =>
    `${s.won}:${s.lost}${s.hit_ratio === null ? "" : ` (${plNumber(s.hit_ratio)}%)`}`;
  if (e.after.won + e.after.lost < 3) return `po zasadzie za mało zamknięć (${e.after.won + e.after.lost})`;
  return `przed ${fmt(e.before)} → po ${fmt(e.after)}`;
}

function ClientsTable({ clients }: { clients: LostReviewClient[] }) {
  const withLosses = clients.filter((c) => c.lost > 0);
  return (
    <section className="space-y-2">
      <h3 className="text-base font-semibold text-foreground">
        Klienci z przegranymi <span className="text-muted-foreground">· {withLosses.length}</span>
      </h3>
      {withLosses.length === 0 ? (
        <p className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
          Żaden klient nie ma przegranej w tym okresie.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <table className="w-full min-w-[60rem] text-sm" data-testid="lost-review-clients">
            <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Klient</th>
                <th className="px-3 py-2 text-right font-medium">Wygr.</th>
                <th className="px-3 py-2 text-right font-medium">Przegr.</th>
                <th className="px-3 py-2 font-medium">Gdzie przegrywamy</th>
                <th className="px-3 py-2 font-medium">Co klient mówi o naszych</th>
                <th className="px-3 py-2 font-medium">Zasady ze spotkań · czy pomogło</th>
              </tr>
            </thead>
            <tbody>
              {withLosses.map((c) => (
                <tr key={c.client_id} className="border-t border-border align-top">
                  <td className="px-3 py-2 font-medium">{c.name}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{c.won}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {c.lost}
                    {c.idle ? <span className="block text-xs text-muted-foreground">{c.idle} bez ruchu</span> : null}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex h-2 w-32 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                      {LOST_STAGES.map((s) =>
                        c.stages[s.key] ? (
                          <div key={s.key} className={STAGE_TONE[s.key]} style={{ width: `${(c.stages[s.key] / c.lost) * 100}%` }} />
                        ) : null,
                      )}
                    </div>
                    <div className="mt-1 text-xs">{c.pattern ?? "—"}</div>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {c.verdicts.length
                      ? c.verdicts.map((v) => `${v.label} ×${v.count}`).join(", ")
                      : "nic — klient nie ocenił nikogo"}
                    {c.why.length ? (
                      <span className="mt-0.5 block text-xs">DL: {c.why.map((v) => `${v.label} ×${v.count}`).join(", ")}</span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {c.lessons.length ? (
                      <ul className="space-y-1">
                        {c.lessons.map((l) => (
                          <li key={l.id}>
                            <span className="text-foreground">{l.text}</span>
                            {effectText(l) ? <span className="block text-muted-foreground">{effectText(l)}</span> : null}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span className="text-muted-foreground">brak zasad</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function LessonsSection({ lessons, clients }: { lessons: LostReviewLesson[]; clients: LostReviewClient[] }) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const names = new Map(clients.map((c) => [c.client_id, c.name]));
  const archive = useMutation({
    mutationFn: (id: number) => lostReviewApi.archiveLesson(id),
    onSuccess: () => {
      showSuccess("Zasada przestała obowiązywać.");
      void queryClient.invalidateQueries({ queryKey: lostReviewKeys.all });
    },
    onError: (e) => showError(apiErrorMessage(e, "Nie udało się zdjąć zasady.")),
  });
  return (
    <Panel
      title={`Wnioski ze spotkań · ${lessons.length}`}
      lede="Obowiązujące. Wniosek „ten klient” widać na stronie każdej rekrutacji klienta."
    >
      {lessons.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Wniosek wpisany przy rekrutacji pojawi się tutaj. Na następnym spotkaniu tabela klientów pokaże,
          czy pomógł.
        </p>
      ) : (
        <ul className="divide-y divide-border text-sm" data-testid="lost-review-lessons">
          {lessons.map((l) => (
            <li key={l.id} className="flex flex-wrap items-center gap-2 py-1.5">
              <span className="rounded bg-muted px-1.5 py-0.5 text-xs">
                {l.scope === "all" ? "wszyscy" : (l.client_name ?? names.get(l.client_id ?? -1) ?? "klient")}
              </span>
              <span className="min-w-0 flex-1">{l.text}</span>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={archive.isPending}
                onClick={() => archive.mutate(l.id)}
              >
                Zdejmij
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
