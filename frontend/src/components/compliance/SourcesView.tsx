"use client";

import { Play } from "lucide-react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useComplianceRuns, useStartCollect } from "@/lib/api/compliance";
import { apiErrorMessage } from "@/lib/api-error";
import { resolveViewState } from "@/lib/view-state";

import {
  CLASS_LABEL,
  RUN_KIND_LABEL,
  RUN_STATUS,
  formatMoment,
  runSummaryLine,
  type Tone,
} from "./compliance-model";
import { LegalSourcesCard } from "./LegalSourcesCard";

/**
 * Źródła Zbieracza (`docs/claude/przepisy/radar-przepisow-dwa-boty.md`).
 * Opis, bez liczb — liczby biegów są niżej, z `GET /runs`.
 */
const SOURCES: readonly { name: string; how: string; klass: "official" | "lex" | "practice"; tone: Tone }[] = [
  {
    name: "Dziennik Ustaw i Monitor Polski",
    how: "Zbieracz podaje numer aktu, a bramka NEXUSA sama sprawdza go w API Sejmu (ELI). Akt, którego API nie zna, odpada.",
    klass: "official",
    tone: "success",
  },
  {
    name: "Ustawy w Sejmie i Senacie",
    how: "Numer druku sprawdzany w API Sejmu: etap Sejm → Senat → Prezydent → Dz.U.",
    klass: "official",
    tone: "success",
  },
  {
    name: "Projekty rządowe (RCL)",
    how: "legislacja.gov.pl — Zbieracz czyta projekty z linkiem i datą.",
    klass: "official",
    tone: "success",
  },
  {
    name: "ZUS, MF i KSeF, PIP, UODO, NSA",
    how: "Komunikaty, wyjaśnienia i orzeczenia ze stron urzędów (*.gov.pl), każda pozycja z linkiem i datą.",
    klass: "official",
    tone: "success",
  },
  {
    name: "Prawo UE (EUR-Lex)",
    how: "Akty i projekty UE, które dotyczą firmy (np. AI Act, dyrektywa płacowa).",
    klass: "official",
    tone: "success",
  },
  {
    name: "LEX",
    how: "Konto księgowej z Vault Grok Bota. Do NEXUSA trafia tylko tytuł, link i krótki cytat — bez komentarzy.",
    klass: "lex",
    tone: "info",
  },
  {
    name: "Gofin",
    how: "Konto księgowej z Vault Grok Bota. Do NEXUSA trafia tylko tytuł, link i krótki cytat — komentarz wydawnictwa, nie fakt urzędowy.",
    klass: "practice",
    tone: "neutral",
  },
  {
    name: "Eureka, doradcy, serwis X",
    how: "Praktyka rynkowa: sygnał do sprawdzenia, nigdy fakt urzędowy.",
    klass: "practice",
    tone: "neutral",
  },
];

interface SourcesViewProps {
  isAdmin: boolean;
}

export function SourcesView({ isAdmin }: SourcesViewProps) {
  return (
    <div className="grid min-w-0 gap-3.5 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
      <LegalSourcesCard />
      <BotsToday isAdmin={isAdmin} />
      <section className="min-w-0 self-start rounded-lg border border-border bg-card">
        <h2 className="border-b border-border/70 px-3.5 py-2 text-[13px] font-semibold">Źródła (czyta Zbieracz)</h2>
        <ul className="divide-y divide-border/60">
          {SOURCES.map((source) => (
            <li key={source.name} className="grid gap-0.5 px-3.5 py-2">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[13px] font-medium">{source.name}</span>
                <StatusDot tone={source.tone}>{CLASS_LABEL[source.klass]}</StatusDot>
              </div>
              <span className="text-xs text-muted-foreground">{source.how}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function BotsToday({ isAdmin }: { isAdmin: boolean }) {
  const runs = useComplianceRuns();
  const start = useStartCollect();
  const { showToast } = useToast();
  const list = runs.data?.runs ?? [];
  const state = resolveViewState({
    isLoading: runs.isLoading,
    isError: runs.isError,
    error: runs.error,
    isSuccess: runs.isSuccess,
    isEmpty: list.length === 0,
  });
  const collectConfigured = runs.data?.configured.collect ?? false;

  const startCollect = async () => {
    try {
      const run = await start.mutateAsync();
      showToast(`Zbieracz wystartował (bieg #${run.id}).`);
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się uruchomić Zbieracza."), "error");
    }
  };

  return (
    <section className="min-w-0 self-start rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/70 px-3.5 py-2">
        <h2 className="text-[13px] font-semibold">Boty dziś</h2>
        {isAdmin && runs.isSuccess ? (
          <Button
            size="sm"
            variant="outline"
            onClick={startCollect}
            loading={start.isPending}
            disabled={!collectConfigured}
            title={collectConfigured ? undefined : "Zbieracz nie ma jeszcze adresu webhooka"}
          >
            <Play className="mr-1 h-3.5 w-3.5" aria-hidden />
            Uruchom Zbieracza
          </Button>
        ) : null}
      </div>
      <p className="border-b border-border/60 px-3.5 py-2 text-xs text-muted-foreground">
        Zbieracz czyta źródła i odsyła surowe pozycje. Bramka NEXUSA sprawdza numery w API Sejmu i usuwa powtórki.
        Analityk łączy pozycje w zmiany. Przy każdej karcie widać, czy API Sejmu potwierdziło numer aktu lub druku. „U nas” liczy NEXUS na własnych danych —
        dane firmy nie wychodzą do bota.
      </p>
      {state === "loading" ? (
        <p className="px-3.5 py-4 text-sm text-muted-foreground">Wczytywanie biegów…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => runs.refetch()} className="m-3" />
      ) : runs.data && !runs.data.enabled ? (
        <p className="px-3.5 py-4 text-sm text-muted-foreground">
          Radar jest wyłączony — biegi pojawią się po włączeniu.
          {isAdmin && !collectConfigured ? " Zbieracz nie ma jeszcze adresu webhooka." : ""}
        </p>
      ) : state === "empty" ? (
        <p className="px-3.5 py-4 text-sm text-muted-foreground">Jeszcze nie było biegu.</p>
      ) : (
        <ol className="divide-y divide-border/60">
          {list.map((run) => {
            const status = RUN_STATUS[run.status] ?? { label: run.status, tone: "neutral" as const };
            const partial = run.kind === "collect" && run.status === "received"
              && (run.summary.lex_skipped === true || run.summary.gofin_skipped === true);
            const line = runSummaryLine(run);
            return (
              <li key={run.id} className="grid gap-1 px-3.5 py-2">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-[13px] font-medium">
                    {RUN_KIND_LABEL[run.kind] ?? run.kind} · #{run.id}
                  </span>
                  <StatusDot tone={partial ? "warning" : status.tone}>
                    {partial ? "przyjęty z pominięciem źródła" : status.label}
                  </StatusDot>
                </div>
                <span className="text-xs text-muted-foreground">
                  start {formatMoment(run.started_at)}
                  {run.received_at ? ` · przyjęty ${formatMoment(run.received_at)}` : ""}
                </span>
                {line ? <span className="text-xs">{line}</span> : null}
                {run.error ? <span className="text-xs text-destructive">{run.error}</span> : null}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
