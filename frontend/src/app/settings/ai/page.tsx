"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  ArrowLeft,
  Sparkles,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Power,
  TrendingUp,
} from "lucide-react";
import {
  aiSettingsApi,
  type AIFeatureKey,
  type AIFeatureConfigDto,
  type AIFeatureUsageDto,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatNumber(n: number): string {
  return new Intl.NumberFormat("pl-PL").format(n);
}

function formatDate(iso: string): string {
  // ``period_start`` and ``period_end`` come from the backend as ISO date
  // (YYYY-MM-DD). We display them in the Polish DD/MM/YYYY format used
  // elsewhere in the app.
  const d = new Date(iso);
  return d.toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function usageColor(used: number, limit: number): string {
  if (limit === 0) return "bg-emerald-500";
  const pct = (used / limit) * 100;
  if (pct >= 100) return "bg-rose-500";
  if (pct >= 80) return "bg-amber-500";
  return "bg-emerald-500";
}

// ── Sub-components ───────────────────────────────────────────────────────────

interface MasterToggleProps {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  disabled: boolean;
}

function MasterToggle({ enabled, onChange, disabled }: MasterToggleProps) {
  return (
    <div className="flex items-center justify-between p-6 bg-card border border-border rounded-xl">
      <div className="flex items-start gap-3">
        <Power
          className={cn(
            "w-5 h-5 mt-0.5",
            enabled ? "text-emerald-500" : "text-muted-foreground",
          )}
        />
        <div>
          <h2 className="text-lg font-semibold text-foreground">
            Funkcje AI w NEXUS
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            {enabled
              ? "AI jest włączone – funkcje poniżej działają zgodnie z indywidualnymi ustawieniami."
              : "Wszystkie funkcje AI są wyłączone globalnie. Włącz aby przywrócić działanie."}
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={() => onChange(!enabled)}
        disabled={disabled}
        className={cn(
          "relative inline-flex h-7 w-12 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          "disabled:cursor-not-allowed disabled:opacity-50",
          enabled ? "bg-emerald-500" : "bg-muted",
        )}
        aria-checked={enabled}
        role="switch"
      >
        <span
          className={cn(
            "pointer-events-none inline-block h-5 w-5 translate-x-0 transform rounded-full bg-white shadow-lg ring-0 transition-transform",
            enabled ? "translate-x-5" : "translate-x-0.5",
          )}
        />
      </button>
    </div>
  );
}

interface FeatureCardProps {
  config: AIFeatureConfigDto;
  usage: AIFeatureUsageDto;
  masterEnabled: boolean;
  onToggle: (feature: AIFeatureKey, enabled: boolean) => void;
  onLimitChange: (feature: AIFeatureKey, limit: number) => void;
  pendingFeature: AIFeatureKey | null;
}

function FeatureCard({
  config,
  usage,
  masterEnabled,
  onToggle,
  onLimitChange,
  pendingFeature,
}: FeatureCardProps) {
  const [limitDraft, setLimitDraft] = useState<string>(
    String(config.monthly_limit),
  );
  const [editingLimit, setEditingLimit] = useState(false);

  useEffect(() => {
    setLimitDraft(String(config.monthly_limit));
  }, [config.monthly_limit]);

  const isPending = pendingFeature === config.feature;
  const effectivelyEnabled = masterEnabled && config.enabled;
  const exhausted =
    config.monthly_limit > 0 && usage.used >= config.monthly_limit;

  const pct =
    config.monthly_limit === 0
      ? 0
      : Math.min(100, (usage.used / config.monthly_limit) * 100);

  const handleLimitSave = () => {
    const parsed = Number.parseInt(limitDraft, 10);
    if (Number.isNaN(parsed) || parsed < 0) {
      setLimitDraft(String(config.monthly_limit));
      setEditingLimit(false);
      return;
    }
    onLimitChange(config.feature, parsed);
    setEditingLimit(false);
  };

  return (
    <div
      className={cn(
        "p-6 bg-card border rounded-xl transition-opacity",
        effectivelyEnabled ? "border-border" : "border-border opacity-60",
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <Sparkles className="w-4 h-4 text-primary" />
            <h3 className="text-base font-semibold text-foreground">
              {config.label}
            </h3>
            {exhausted && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-rose-500/10 text-rose-500">
                <AlertCircle className="w-3 h-3" />
                Limit wyczerpany
              </span>
            )}
          </div>

          <div className="flex items-center gap-2 text-sm text-muted-foreground mt-3">
            <TrendingUp className="w-4 h-4" />
            <span>
              <span className="font-medium text-foreground">
                {formatNumber(usage.used)}
              </span>
              {" / "}
              {config.monthly_limit === 0 ? (
                <span>bez limitu</span>
              ) : (
                <span>{formatNumber(config.monthly_limit)} wywołań</span>
              )}
            </span>
            <span className="text-muted-foreground/60">·</span>
            <span className="text-xs">
              odnowienie {formatDate(usage.period_end)}
            </span>
          </div>

          {config.monthly_limit > 0 && (
            <div className="mt-2 h-1.5 bg-muted rounded-full overflow-hidden">
              <div
                className={cn(
                  "h-full transition-all",
                  usageColor(usage.used, config.monthly_limit),
                )}
                style={{ width: `${pct}%` }}
              />
            </div>
          )}

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
                  <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 text-emerald-500 shrink-0" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="mt-4 flex items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">
              Limit miesięczny:
            </span>
            {editingLimit ? (
              <>
                <input
                  type="number"
                  min={0}
                  value={limitDraft}
                  onChange={(e) => setLimitDraft(e.target.value)}
                  className="w-24 px-2 py-1 text-sm bg-background border border-input rounded-md focus:outline-none focus:ring-2 focus:ring-ring"
                  autoFocus
                />
                <button
                  type="button"
                  onClick={handleLimitSave}
                  className="text-xs px-2 py-1 rounded-md bg-primary text-primary-foreground hover:bg-primary/90"
                >
                  Zapisz
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setLimitDraft(String(config.monthly_limit));
                    setEditingLimit(false);
                  }}
                  className="text-xs text-muted-foreground hover:text-foreground"
                >
                  Anuluj
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => setEditingLimit(true)}
                className="text-sm text-foreground hover:text-primary transition-colors"
              >
                {config.monthly_limit === 0
                  ? "ustaw limit"
                  : formatNumber(config.monthly_limit)}
              </button>
            )}
            <span className="text-xs text-muted-foreground/60">
              (0 = bez limitu)
            </span>
          </div>
        </div>

        <div className="flex flex-col items-end gap-2 shrink-0">
          <button
            type="button"
            onClick={() => onToggle(config.feature, !config.enabled)}
            disabled={isPending || !masterEnabled}
            className={cn(
              "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              "disabled:cursor-not-allowed disabled:opacity-50",
              config.enabled && masterEnabled ? "bg-primary" : "bg-muted",
            )}
            aria-checked={config.enabled}
            role="switch"
          >
            <span
              className={cn(
                "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow-lg ring-0 transition-transform",
                config.enabled ? "translate-x-5" : "translate-x-0.5",
              )}
            />
          </button>
          {isPending && (
            <Loader2 className="w-3 h-3 text-muted-foreground animate-spin" />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function AISettingsPage() {
  const queryClient = useQueryClient();
  const [pendingFeature, setPendingFeature] = useState<AIFeatureKey | null>(
    null,
  );
  const [masterPending, setMasterPending] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["ai-settings"],
    queryFn: () => aiSettingsApi.get().then((r) => r.data),
  });

  const masterMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      aiSettingsApi.setMaster(enabled).then((r) => r.data),
    onMutate: () => {
      setMasterPending(true);
      setErrorMsg(null);
    },
    onSuccess: (fresh) => {
      queryClient.setQueryData(["ai-settings"], fresh);
    },
    onError: (err: unknown) => {
      setErrorMsg(
        err instanceof Error ? err.message : "Nie udało się zapisać zmiany",
      );
    },
    onSettled: () => setMasterPending(false),
  });

  const featureMutation = useMutation({
    mutationFn: ({
      feature,
      payload,
    }: {
      feature: AIFeatureKey;
      payload: { enabled?: boolean; monthly_limit?: number };
    }) => aiSettingsApi.updateFeature(feature, payload).then((r) => r.data),
    onMutate: ({ feature }) => {
      setPendingFeature(feature);
      setErrorMsg(null);
    },
    onSuccess: (fresh) => {
      queryClient.setQueryData(["ai-settings"], fresh);
    },
    onError: (err: unknown) => {
      setErrorMsg(
        err instanceof Error ? err.message : "Nie udało się zapisać zmiany",
      );
    },
    onSettled: () => setPendingFeature(null),
  });

  if (isLoading) {
    return (
      <div className="container max-w-4xl mx-auto py-8 px-4">
        <div className="flex items-center justify-center min-h-[400px]">
          <Loader2 className="w-8 h-8 text-muted-foreground animate-spin" />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="container max-w-4xl mx-auto py-8 px-4">
        <div className="p-6 bg-rose-500/10 border border-rose-500/20 rounded-xl">
          <div className="flex items-center gap-2 text-rose-500">
            <AlertCircle className="w-5 h-5" />
            <span>Nie udało się załadować ustawień AI.</span>
          </div>
          <p className="text-sm text-muted-foreground mt-2">
            Sprawdź czy masz uprawnienia administratora.
          </p>
        </div>
      </div>
    );
  }

  // Pair config with usage by feature key for stable rendering order.
  const usageByFeature = new Map(data.usage.map((u) => [u.feature, u]));

  return (
    <div className="container max-w-4xl mx-auto py-8 px-4">
      <div className="mb-6">
        <Link
          href="/settings"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Ustawienia
        </Link>
        <h1 className="text-2xl font-bold text-foreground mt-2">
          Funkcje AI
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Zarządzaj globalnym wyłącznikiem oraz miesięcznymi limitami dla
          poszczególnych funkcji opartych o AI.
        </p>
      </div>

      {errorMsg && (
        <div className="mb-4 p-3 bg-rose-500/10 border border-rose-500/20 rounded-lg flex items-center gap-2 text-sm text-rose-500">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      <MasterToggle
        enabled={data.master_enabled}
        onChange={(enabled) => masterMutation.mutate(enabled)}
        disabled={masterPending}
      />

      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mt-8 mb-3">
        Funkcje
      </h2>

      <div className="space-y-3">
        {data.features.map((cfg) => {
          const usage = usageByFeature.get(cfg.feature);
          if (!usage) return null;
          return (
            <FeatureCard
              key={cfg.feature}
              config={cfg}
              usage={usage}
              masterEnabled={data.master_enabled}
              onToggle={(feature, enabled) =>
                featureMutation.mutate({ feature, payload: { enabled } })
              }
              onLimitChange={(feature, monthly_limit) =>
                featureMutation.mutate({
                  feature,
                  payload: { monthly_limit },
                })
              }
              pendingFeature={pendingFeature}
            />
          );
        })}
      </div>
    </div>
  );
}
