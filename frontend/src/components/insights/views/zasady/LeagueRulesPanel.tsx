"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { isForbiddenError } from "@/lib/view-state";

/**
 * Punktacja Ligi Mistrzów, Wyścigu i progi Ścieżki rozwoju. Trasa
 * `/api/insights/scoring-config` istnieje od 09.2026 (GET każdy, PATCH admin),
 * ale do 05.11.2026 nie było ekranu, który by ją wołał.
 */

interface ScoringField {
  key: string;
  value: number;
  default: number;
  min: number;
  max: number;
  group: string;
  label: string;
  unit: string;
  is_default: boolean;
}

interface ScoringConfig {
  fields: ScoringField[];
  notes: { league_no_retroactivity: string; seniority_retroactive: string };
}

const GROUPS: { id: string; title: string; note?: "league" | "seniority" }[] = [
  { id: "league_points", title: "Punkty w Lidze Mistrzów", note: "league" },
  { id: "league_qualification", title: "Warunek udziału w Lidze" },
  { id: "monthly_race", title: "Wyścig Placementów" },
  { id: "seniority", title: "Ścieżka rozwoju", note: "seniority" },
];

// Etykiety z backendu pisane były pod kafel z rozwinięciem, tu grupa mówi już „Ścieżka rozwoju”.
const shortLabel = (label: string): string => {
  const short = label
    .replace(/^(Ścieżka rozwoju|Wyścig Placementów|Warunek udziału) — /, "")
    .replace(/ \(stage `[a-z_]+`\)/, "");
  return short.charAt(0).toUpperCase() + short.slice(1);
};

export function LeagueRulesPanel() {
  const queryClient = useQueryClient();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const query = useQuery({
    queryKey: ["insights", "scoring-config"],
    queryFn: async () =>
      (await api.get<ScoringConfig>("/api/insights/scoring-config")).data,
  });
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!query.data) return;
    setDraft(Object.fromEntries(query.data.fields.map((f) => [f.key, String(f.value)])));
  }, [query.data]);

  const changed = useMemo(
    () =>
      (query.data?.fields ?? []).filter(
        (f) => draft[f.key] !== undefined && Number(draft[f.key]) !== f.value,
      ),
    [draft, query.data],
  );

  const save = useMutation({
    mutationFn: async () =>
      (
        await api.patch("/api/insights/scoring-config", {
          values: Object.fromEntries(changed.map((f) => [f.key, Number(draft[f.key])])),
        })
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["insights", "scoring-config"] });
      void queryClient.invalidateQueries({ queryKey: ["insights", "rules-overview"] });
    },
    onError: (e) => setError(apiErrorMessage(e, "Nie udało się zapisać punktacji.")),
  });

  if (query.isError) {
    return (
      <QueryStateNotice
        state={isForbiddenError(query.error) ? "forbidden" : "error"}
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (!query.isSuccess) {
    return <div className="p-6 text-sm text-muted-foreground">Ładowanie…</div>;
  }
  const { fields, notes } = query.data;

  const onSave = async () => {
    setError(null);
    const seniority = changed.some((f) => f.group === "seniority");
    const ok = await askConfirm({
      title: "Zapisać nową punktację?",
      description: seniority ? notes.seniority_retroactive : notes.league_no_retroactivity,
      confirmLabel: "Zapisz",
    });
    if (ok) save.mutate();
  };

  return (
    <div className="space-y-4">
      {confirmDialog}
      <div className="grid gap-4 lg:grid-cols-2">
        {GROUPS.map((group) => {
          const rows = fields.filter((f) => f.group === group.id);
          return (
            <section key={group.id} className="rounded-xl border border-border bg-card p-4">
              <h3 className="text-sm font-semibold text-foreground">{group.title}</h3>
              {group.note ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  {group.note === "league" ? notes.league_no_retroactivity : notes.seniority_retroactive}
                </p>
              ) : null}
              <div className="mt-3 divide-y divide-border">
                {rows.map((f) => (
                  <label key={f.key} className="flex items-center justify-between gap-3 py-1.5 text-sm">
                    <span className="min-w-0 text-foreground">{shortLabel(f.label)}</span>
                    <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                      <Input
                        type="number"
                        min={f.min}
                        max={f.max}
                        value={draft[f.key] ?? ""}
                        onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                        className="h-8 w-20 text-right"
                      />
                      <span className="w-[4.5rem]">{f.unit}</span>
                    </span>
                  </label>
                ))}
              </div>
            </section>
          );
        })}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex items-center gap-3">
        <Button onClick={onSave} disabled={changed.length === 0 || save.isPending}>
          Zapisz punktację
        </Button>
        <span className="text-xs text-muted-foreground">
          {changed.length === 0 ? "Bez zmian" : `Zmieniasz: ${changed.length}`}
        </span>
      </div>
    </div>
  );
}
