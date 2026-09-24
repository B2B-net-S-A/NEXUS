"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import Link from "next/link";
import {
  Sparkles,
  CheckCircle2,
  Loader2,
  TrendingUp,
} from "lucide-react";
import {
  aiSettingsApi,
  type AIFeatureConfigDto,
  type AIFeatureUsageDto,
} from "@/lib/api";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { AutoMatchOverview } from "@/components/settings/AutoMatchOverview";
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

function FeatureCard({ config, usage }: FeatureCardProps) {
  return (
    <div className="p-6 bg-card border border-border rounded-xl">
      <div className="flex items-center gap-2 mb-1 flex-wrap">
        <Sparkles className="w-4 h-4 text-primary" />
        <h3 className="text-base font-semibold text-foreground">
          {config.label}
        </h3>
        {config.model && (
          <code
            className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground font-mono"
            title="Efektywny model LLM (rejestr backendu)"
            data-testid="feature-model"
          >
            {config.model}
          </code>
        )}
      </div>

      <div className="flex items-center gap-2 text-sm text-muted-foreground mt-3 flex-wrap">
        <TrendingUp className="w-4 h-4" />
        <span>
          <span className="font-medium text-foreground tabular-nums">
            {formatNumber(usage.used)}
          </span>{" "}
          wywołań w tym miesiącu
        </span>
        <span className="text-muted-foreground/60">·</span>
        <span className="text-xs">
          okres {formatDate(usage.period_start)}–{formatDate(usage.period_end)}
        </span>
      </div>

      <div
        className="text-xs text-muted-foreground mt-2 space-y-1"
        data-testid="feature-tokens"
      >
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

      <div className="mt-4">
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

export default function AISettingsPage() {
  const testAlert = useMutation({ mutationFn: () => aiSettingsApi.testAlert() });

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

  return (
    <div className="container max-w-4xl mx-auto md:py-8 md:px-4">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground mt-2">Funkcje AI</h1>
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
              ? "Alert dostarczony. Sprawdź powiadomienia pod ikoną dzwonka."
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

      <AutoMatchOverview />

      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mt-8 mb-3">
        Funkcje
      </h2>

      <div className="space-y-3">
        {data.features.map((cfg) => {
          const usage = usageByFeature.get(cfg.feature);
          if (!usage) return null;
          return <FeatureCard key={cfg.feature} config={cfg} usage={usage} />;
        })}
      </div>
    </div>
  );
}
