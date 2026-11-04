"use client";

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import Link from "next/link";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
} from "lucide-react";
import {
  aiSettingsApi,
  type AIFeatureConfigDto,
  type AIFeatureUsageDto,
} from "@/lib/api";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { AutoMatchOverview } from "@/components/settings/AutoMatchOverview";
import { JarvisGapsOverview } from "@/components/settings/JarvisGapsOverview";
import { resolveViewState } from "@/lib/view-state";

// NEXUS nie ma limitów AI (decyzja z 17.09.2026): nie ma głównego wyłącznika,
// przełączników per funkcja ani miesięcznych sufitów. Ten ekran jest raportem
// zużycia i kosztu. Jedyną ochroną budżetu jest alarm wydatków niżej.

function formatNumber(n: number): string {
  return new Intl.NumberFormat("pl-PL").format(n);
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function formatUsd(value: number | null | undefined): string | null {
  if (value == null) return null;
  return `${Number(value).toFixed(2)} USD`;
}

interface FeatureCardProps {
  config: AIFeatureConfigDto;
  usage: AIFeatureUsageDto;
}

/** Szczegóły funkcji pod rozwiniętym wierszem — treść dawnej karty funkcji. */
function FeatureDetails({ config, usage }: FeatureCardProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div
        className="text-xs text-muted-foreground space-y-1"
        data-testid="feature-tokens"
      >
        <p>
          Okres {formatDate(usage.period_start)}–{formatDate(usage.period_end)}
        </p>
        {(usage.provider_calls ?? 0) > 0 ? (
          <>
            <p>
              Zmierzone odpowiedzi: {formatNumber(usage.provider_calls!)}.
              Tokeny: {formatNumber(usage.input_tokens)} wejścia ·{" "}
              {formatNumber(usage.output_tokens)} wyjścia.
            </p>
            <p>
              Cache: {formatNumber(usage.cache_read_tokens ?? 0)} odczytu ·{" "}
              {formatNumber(usage.cache_creation_tokens ?? 0)} zapisu.
            </p>
            <p>
              Koszt zmierzonych odpowiedzi:{" "}
              {formatUsd(usage.estimated_cost_usd)
                ? `${formatUsd(usage.estimated_cost_usd)} (szacunek)`
                : "brak wyceny"}
              .
            </p>
          </>
        ) : (
          <p>Brak zmierzonych odpowiedzi dostawcy w tym okresie.</p>
        )}
        {usage.legacy_usage_present && (
          <p>
            Historyczne tokeny wymagają uzgodnienia z dostawcą i nie są
            wliczone w pomiar.
          </p>
        )}
        {(usage.operations_without_response ?? 0) > 0 && (
          <p>
            Operacje bez zapisanej odpowiedzi:{" "}
            {formatNumber(usage.operations_without_response!)} (w toku,
            przerwane lub bez pomiaru).
          </p>
        )}
        {(usage.unpriced_calls ?? 0) > 0 && (
          <p>
            Odpowiedzi bez pełnej wyceny: {formatNumber(usage.unpriced_calls!)}.
            Szacunek kosztu jest niepełny.
          </p>
        )}
      </div>

      <div>
        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">
          Dane wysyłane do AI
        </h4>
        <ul className="space-y-1">
          {config.data_sent_to_ai.map((item) => (
            <li
              key={item}
              className="flex items-start gap-2 text-sm text-muted-foreground"
            >
              <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 text-primary shrink-0" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function FeatureRow({
  config,
  usage,
  share,
  open,
  onToggle,
}: FeatureCardProps & { share: number; open: boolean; onToggle: () => void }) {
  const cost = formatUsd(usage.estimated_cost_usd);
  return (
    <>
      <tr className="border-t border-border align-top">
        <td className="px-3 py-2.5">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={open}
            className="flex items-center gap-1.5 text-left font-medium text-foreground hover:text-primary"
          >
            {open ? (
              <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            ) : (
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            )}
            {config.label}
          </button>
        </td>
        <td className="px-3 py-2.5">
          {config.model && (
            <code
              className="whitespace-nowrap text-[11px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground font-mono"
              title="Efektywny model LLM (rejestr backendu)"
              data-testid="feature-model"
            >
              {config.model}
            </code>
          )}
        </td>
        <td className="px-3 py-2.5 text-right tabular-nums">{formatNumber(usage.used)}</td>
        <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{cost ?? "—"}</td>
        <td className="px-3 py-2.5">
          <div className="h-1.5 w-28 rounded bg-muted" aria-hidden>
            <div className="h-1.5 rounded bg-primary" style={{ width: `${Math.round(share * 100)}%` }} />
          </div>
        </td>
      </tr>
      {open ? (
        <tr className="bg-muted/30">
          <td colSpan={5} className="px-3 py-3">
            <FeatureDetails config={config} usage={usage} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

type AiTab = "costs" | "auto-match" | "jarvis-gaps";

const AI_TABS = [
  { value: "costs", label: "Koszty" },
  { value: "auto-match", label: "Automatyczne dopasowania" },
  { value: "jarvis-gaps", label: "Czego Jarvis nie umie" },
];

export default function AISettingsPage() {
  const testAlert = useMutation({ mutationFn: () => aiSettingsApi.testAlert() });
  const [tab, setTab] = useState<AiTab>("costs");
  const [openFeatures, setOpenFeatures] = useState<Set<string>>(new Set());

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["ai-settings"],
    queryFn: () => aiSettingsApi.get().then((r) => r.data),
  });

  if (isLoading) {
    return (
      <div className="container max-w-4xl mx-auto md:py-8 md:px-4">
        <div className="flex items-center justify-center min-h-[400px]">
          <Loader2 className="w-8 h-8 text-muted-foreground animate-spin" />
        </div>
      </div>
    );
  }

  // UAT A-B04: 403 to odmowa — nie generyczne „Nie udało się załadować".
  if (
    error &&
    resolveViewState({ isLoading: false, isError: true, error }) === "forbidden"
  ) {
    return (
      <div className="container max-w-4xl mx-auto md:py-8 md:px-4">
        <QueryStateNotice
          state="forbidden"
          description="Raport zużycia AI jest dostępny wyłącznie dla administratora."
        />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="container max-w-4xl mx-auto md:py-8 md:px-4">
        <QueryStateNotice
          state="error"
          description="Nie udało się załadować raportu zużycia AI."
          onRetry={() => refetch()}
        />
      </div>
    );
  }

  const usageByFeature = new Map(data.usage.map((u) => [u.feature, u]));
  const totalCost = data.usage.reduce(
    (sum, u) => sum + (u.estimated_cost_usd ?? 0),
    0,
  );
  // Najdroższe na górze; bez wyceny na końcu, w kolejności z rejestru.
  const rows = data.features
    .map((config) => ({ config, usage: usageByFeature.get(config.feature) }))
    .filter((row): row is { config: AIFeatureConfigDto; usage: AIFeatureUsageDto } => !!row.usage)
    .sort((a, b) => (b.usage.estimated_cost_usd ?? -1) - (a.usage.estimated_cost_usd ?? -1));

  return (
    <div className="container max-w-4xl mx-auto md:py-8 md:px-4">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground mt-2">Koszty AI</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Wszystkie funkcje AI działają bez limitów. Poniżej zużycie i szacunkowy
          koszt w bieżącym miesiącu.
        </p>
        <p className="text-sm text-foreground mt-3" data-testid="ai-total-cost">
          Szacunkowy koszt w tym miesiącu:{" "}
          <span className="font-semibold tabular-nums">
            {totalCost.toFixed(2)} USD
          </span>
        </p>
      </div>

      <div className="mb-4">
        <TabbedNav
          tabs={AI_TABS}
          value={tab}
          onValueChange={(value) => setTab(value as AiTab)}
          ariaLabel="AI"
        />
      </div>

      {tab === "auto-match" ? <AutoMatchOverview /> : null}
      {tab === "jarvis-gaps" ? <JarvisGapsOverview /> : null}

      {tab === "costs" ? (
        <div className="space-y-4">
          <div
            className="rounded-xl border border-border bg-card p-4 text-sm"
            role="status"
          >
            <p className="font-medium text-foreground">
              Alarmy zużycia AI: powiadomienia dla administratorów w NEXUS
            </p>
            <p className="mt-1 text-muted-foreground">
              {data.spend_alerts?.slack_configured
                ? "Kopia na Slack jest skonfigurowana."
                : "Slack nie jest skonfigurowany. Ostrzeżenia są dostępne w powiadomieniach NEXUS."}
            </p>
            {(data.spend_alerts?.pending_deliveries ?? 0) > 0 && (
              <p className="mt-1 text-muted-foreground">
                Oczekujące dostawy: {data.spend_alerts!.pending_deliveries}. Nieudane
                próby są ponawiane.
              </p>
            )}
            <button
              type="button"
              disabled={testAlert.isPending}
              onClick={() => testAlert.mutate()}
              className="mt-3 rounded-md border border-border px-3 py-2 font-medium text-foreground hover:bg-accent disabled:opacity-50"
            >
              Wyślij alert testowy do mnie
            </button>
            {testAlert.isSuccess && (
              <p className="mt-2 text-muted-foreground">
                {testAlert.data.data.delivered
                  ? "Alert dostarczony — pojawia się jako dymek na ekranie (i mail, gdy włączony)."
                  : "Alert oczekuje na dostawę."}
              </p>
            )}
            {testAlert.isError && (
              <p className="mt-2 text-destructive">
                Nie udało się dostarczyć alertu. Ponów próbę za chwilę.
              </p>
            )}
            <p className="mt-1 text-muted-foreground">
              Alarm uwzględnia liczbę operacji oraz zmierzone tokeny i szacunkowy
              koszt z ostatnich 24 godzin. Informuje, niczego nie blokuje.
            </p>
          </div>

          {/* Tabela po koszcie zamiast kart jedna pod drugą (20.10.2026): na
              produkcji ponad 20 kart dawało 10 804 px bez porównania kosztów. */}
          <div className="relative overflow-x-auto rounded-xl border border-border bg-card">
            <table className="w-full text-sm">
              <caption className="sr-only">Funkcje AI według kosztu w tym miesiącu</caption>
              <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">Funkcja</th>
                  <th className="px-3 py-2 font-medium">Model</th>
                  <th className="px-3 py-2 text-right font-medium">Wywołania</th>
                  <th className="px-3 py-2 text-right font-medium">Koszt</th>
                  <th className="px-3 py-2 font-medium">Udział</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ config, usage }) => (
                  <FeatureRow
                    key={config.feature}
                    config={config}
                    usage={usage}
                    share={totalCost > 0 ? (usage.estimated_cost_usd ?? 0) / totalCost : 0}
                    open={openFeatures.has(config.feature)}
                    onToggle={() =>
                      setOpenFeatures((prev) => {
                        const next = new Set(prev);
                        if (next.has(config.feature)) next.delete(config.feature);
                        else next.add(config.feature);
                        return next;
                      })
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}
