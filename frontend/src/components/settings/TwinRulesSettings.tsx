"use client";

/**
 * Ustawienia → Rekrutacja → Zasady bliźniaków (decyzje Artura 29.10.2026,
 * makieta https://claude.ai/artifact/QTD7Sk3jBqL386Jq5LYs6m).
 *
 * Jedno ustawienie dla całej firmy: kiedy dwie otwarte rekrutacje są
 * bliźniakami. Każda zasada ma tryb „Wymagane” (para bez niej nie trafia na
 * listę „Możliwe bliźniaki”; łączyć ręcznie wolno, okno ostrzega),
 * „Ostrzeżenie” albo „Wyłączone”. Obok liczba par, które ją dziś spełniają —
 * podgląd liczy serwer na tych samych parach co lista HoR, przed zapisem.
 * Zmieniają Head of Recruitment i admin; reszta widzi zasady bez edycji.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  jobTwinsApi,
  type TwinRuleKey,
  type TwinRuleMode,
  type TwinRules,
  useSaveTwinRules,
  useTwinRules,
} from "@/lib/job-twins-api";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
import { isForbiddenError } from "@/lib/view-state";

const MODE_LABEL: Record<TwinRuleMode, string> = {
  required: "Wymagane",
  warning: "Ostrzeżenie",
  off: "Wyłączone",
};

type ModeKey = Exclude<TwinRuleKey, "similarity">;

interface RuleRow {
  key: ModeKey;
  what: string;
  note: string;
}

const RULES: readonly RuleRow[] = [
  {
    key: "critical",
    what: "Krytyczne jednej rekrutacji są w wymaganiach drugiej",
    note: "Rekrutacja bez krytycznych przechodzi. Porównanie po rdzeniach słów („analiza systemowa” ≈ „Analityk Systemowy” w tytule).",
  },
  { key: "must", what: "Wspólne wymagania (must-have)", note: "Liczone na krótszej liście wymagań." },
  {
    key: "location",
    what: "Wspólne miasto · zdalne pasują zawsze",
    note: "Miasta czytamy z wolnego tekstu lokalizacji; rekrutacja bez miasta daje ostrzeżenie.",
  },
  {
    key: "work_mode",
    what: "Ten sam tryb pracy (zdalnie / te same dni z biura)",
    note: "Inny tryb nie wyklucza bliźniaka — w screeningu dostaje osobną stawkę.",
  },
  { key: "budget", what: "Budżety różnią się najwyżej o…", note: "Brak budżetu w jednej z rekrutacji = przechodzi." },
  { key: "client", what: "Ten sam klient", note: "Wyłączone: bliźniaki także między klientami (decyzja z 28.10)." },
  { key: "category", what: "Ta sama kategoria kompetencji", note: "" },
  {
    key: "different_dl",
    what: "Różni Delivery Leadzi — tylko lista „Możliwe bliźniaki”",
    note: "Delivery Lead swoje rekrutacje łączy sam z kafla „Otwarte podobne”.",
  },
];

const fieldClass =
  "h-8 w-16 rounded-md border border-border bg-card px-2 text-sm tabular-nums text-foreground disabled:opacity-60";

function ModePicker({
  value,
  onChange,
  disabled,
  label,
}: {
  value: TwinRuleMode;
  onChange: (mode: TwinRuleMode) => void;
  disabled: boolean;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={`Jak działa: ${label}`} className="inline-flex overflow-hidden rounded-md border border-border">
      {(Object.keys(MODE_LABEL) as TwinRuleMode[]).map((mode) => (
        <button
          key={mode}
          type="button"
          role="radio"
          aria-checked={value === mode}
          disabled={disabled}
          onClick={() => onChange(mode)}
          className={cn(
            "whitespace-nowrap border-r border-border px-2 py-1 text-xs last:border-r-0 disabled:cursor-not-allowed",
            value === mode && mode === "required" && "bg-primary text-primary-foreground",
            value === mode && mode === "warning" && "bg-warning-muted font-semibold text-warning-muted-foreground",
            value === mode && mode === "off" && "bg-muted font-semibold text-muted-foreground",
            value !== mode && "bg-card text-foreground hover:bg-muted/60",
          )}
        >
          {MODE_LABEL[mode]}
        </button>
      ))}
    </div>
  );
}

function NumberField({
  id,
  value,
  min,
  max,
  disabled,
  onChange,
  suffix,
}: {
  id: string;
  value: number;
  min: number;
  max: number;
  disabled: boolean;
  onChange: (value: number) => void;
  suffix?: string;
}) {
  return (
    <span className="inline-flex items-center gap-1">
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        value={value}
        disabled={disabled}
        onChange={(e) => {
          const next = Number(e.target.value);
          if (Number.isFinite(next)) onChange(Math.min(max, Math.max(min, Math.round(next))));
        }}
        className={fieldClass}
      />
      {suffix ? <span className="text-xs text-muted-foreground">{suffix}</span> : null}
    </span>
  );
}

export function TwinRulesSettings() {
  const query = useTwinRules();
  const save = useSaveTwinRules();
  const { showSuccess, showError } = useToast();
  const [draft, setDraft] = useState<TwinRules | null>(null);
  useEffect(() => {
    if (query.data && draft == null) setDraft(query.data.rules);
  }, [query.data, draft]);
  const canEdit = query.data?.can_edit === true;
  const debounced = useDebouncedValue(draft, 400);
  const preview = useQuery({
    queryKey: ["job-twin-rules-preview", debounced],
    queryFn: ({ signal }) => jobTwinsApi.previewRules(debounced as TwinRules, signal),
    enabled: canEdit && debounced != null,
    staleTime: 30_000,
    retry: false,
  });
  const dirty = useMemo(
    () => draft != null && query.data != null && JSON.stringify(draft) !== JSON.stringify(query.data.rules),
    [draft, query.data],
  );

  if (query.isLoading || (query.data && draft == null)) {
    return <p className="text-sm text-muted-foreground">Wczytuję zasady bliźniaków…</p>;
  }
  if (query.isError || !query.data || !draft) {
    return (
      <QueryStateNotice
        state={isForbiddenError(query.error) ? "forbidden" : "error"}
        description={
          isForbiddenError(query.error)
            ? "Zasady bliźniaków widzą Delivery Lead, Head of Recruitment i admin."
            : "Nie udało się wczytać zasad bliźniaków."
        }
        onRetry={() => void query.refetch()}
      />
    );
  }

  const set = <K extends keyof TwinRules>(key: K, value: TwinRules[K]) => setDraft({ ...draft, [key]: value });
  const setMode = (key: ModeKey, mode: TwinRuleMode) =>
    setDraft({ ...draft, [key]: { ...draft[key], mode } } as TwinRules);
  const p = preview.data;
  const total = p?.pairs_in_scope ?? null;

  const onSave = async () => {
    try {
      const saved = await save.mutateAsync(draft);
      setDraft(saved.rules);
      showSuccess("Zapisano zasady bliźniaków. Działają od razu u wszystkich.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać zasad bliźniaków."));
    }
  };

  return (
    <div className="space-y-4" data-testid="twin-rules-settings">
      {canEdit ? (
        <div
          className="rounded-lg border border-success/30 bg-success-muted px-3 py-2 text-sm text-success-muted-foreground"
          role="status"
          data-testid="twin-rules-summary"
        >
          {p ? (
            <>
              <b>Przy tych zasadach:</b> {p.suggestions} możliwych bliźniaków różnych DL-i (teraz {p.suggestions_saved}) ·{" "}
              {p.pass_required} z {p.pairs_in_scope} par od {draft.min_similarity}% spełnia zasady wymagane · {p.with_warnings}{" "}
              z ostrzeżeniem
            </>
          ) : preview.isError ? (
            "Nie udało się policzyć podglądu — zasady i tak możesz zapisać."
          ) : (
            "Liczę, ile par spełnia te zasady…"
          )}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Zasady zmieniają Head of Recruitment i admin. Widzisz je bez edycji.</p>
      )}

      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-3 py-2 font-semibold">Zasada</th>
              <th className="px-3 py-2 font-semibold">Ustawienie</th>
              <th className="px-3 py-2 font-semibold">Jak działa</th>
            </tr>
          </thead>
          <tbody className="align-top">
            <tr className="border-b border-border">
              <td className="px-3 py-2.5">
                <label htmlFor="twin-rule-similarity" className="font-semibold">
                  Podobieństwo opisu rekrutacji
                </label>
                <p className="text-xs text-muted-foreground">Wektor opisu. Ten próg decyduje, które pary są w ogóle brane pod uwagę.</p>
                {total != null ? <p className="mt-1 text-xs font-semibold tabular-nums">{total} par od progu</p> : null}
              </td>
              <td className="px-3 py-2.5">
                <NumberField
                  id="twin-rule-similarity"
                  value={draft.min_similarity}
                  min={70}
                  max={95}
                  disabled={!canEdit}
                  onChange={(v) => set("min_similarity", v)}
                  suffix="% i więcej"
                />
              </td>
              <td className="px-3 py-2.5 text-xs text-muted-foreground">zawsze</td>
            </tr>
            {RULES.map((row) => {
              const rule = draft[row.key];
              const passes = p?.per_rule[row.key];
              return (
                <tr key={row.key} className="border-b border-border last:border-b-0" data-testid={`twin-rule-${row.key}`}>
                  <td className="px-3 py-2.5">
                    <span className="font-semibold">{query.data.labels[row.key]}</span>
                    {row.note ? <p className="text-xs text-muted-foreground">{row.note}</p> : null}
                    {rule.mode !== "off" && passes != null && total != null ? (
                      <p className="mt-1 text-xs font-semibold tabular-nums">
                        spełnia {passes} z {total}
                      </p>
                    ) : null}
                  </td>
                  <td className="max-w-[240px] px-3 py-2.5 text-xs">
                    <span>{row.what}</span>
                    {row.key === "must" ? (
                      <div className="mt-1">
                        co najmniej{" "}
                        <NumberField
                          id="twin-rule-must-share"
                          value={draft.must.min_share}
                          min={10}
                          max={100}
                          disabled={!canEdit}
                          onChange={(v) => set("must", { ...draft.must, min_share: v })}
                          suffix="%"
                        />
                      </div>
                    ) : null}
                    {row.key === "budget" ? (
                      <div className="mt-1">
                        <NumberField
                          id="twin-rule-budget-diff"
                          value={draft.budget.max_diff}
                          min={0}
                          max={100}
                          disabled={!canEdit}
                          onChange={(v) => set("budget", { ...draft.budget, max_diff: v })}
                          suffix="zł/h"
                        />
                      </div>
                    ) : null}
                    {row.key === "critical" ? (
                      <label className="mt-1 flex items-center gap-1.5">
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-[hsl(var(--primary))]"
                          checked={draft.critical.include_title}
                          disabled={!canEdit}
                          onChange={(e) => set("critical", { ...draft.critical, include_title: e.target.checked })}
                        />
                        szukaj też w tytule drugiej rekrutacji
                      </label>
                    ) : null}
                  </td>
                  <td className="px-3 py-2.5">
                    <ModePicker
                      value={rule.mode}
                      disabled={!canEdit}
                      label={query.data.labels[row.key]}
                      onChange={(mode) => setMode(row.key, mode)}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <label className="flex items-center gap-2">
          Najwięcej bliźniaków na rekrutację
          <NumberField id="twin-rule-max" value={draft.max_twins} min={1} max={3} disabled={!canEdit} onChange={(v) => set("max_twins", v)} />
        </label>
        <label className="flex items-center gap-2">
          Kafel „Otwarte podobne”
          <NumberField
            id="twin-rule-open-limit"
            value={draft.open_similar_limit}
            min={4}
            max={15}
            disabled={!canEdit}
            onChange={(v) => set("open_similar_limit", v)}
            suffix="pozycji"
          />
        </label>
        <label className="flex items-center gap-2">
          Podpowiedź par pytań
          <select
            className="h-8 rounded-md border border-border bg-card px-2 text-sm"
            value={draft.pair_hint}
            disabled={!canEdit}
            onChange={(e) => set("pair_hint", e.target.value as TwinRules["pair_hint"])}
          >
            <option value="careful">ostrożna</option>
            <option value="default">jak dotąd</option>
            <option value="bold">śmiała</option>
          </select>
        </label>
      </div>

      {canEdit && p && p.examples.length > 0 ? (
        <section className="space-y-1.5" aria-label="Co zmieni się po zapisie">
          <h2 className="text-sm font-semibold">Co zmieni się po zapisie</h2>
          <ul className="divide-y divide-border rounded-lg border border-border bg-card">
            {p.examples.map((ex) => (
              <li key={`${ex.job.id}-${ex.other.id}`} className="px-3 py-2 text-sm">
                <span
                  className={cn(
                    "mr-2 rounded px-1.5 py-0.5 text-xs font-semibold",
                    ex.status === "drop" && "bg-destructive/10 text-destructive",
                    ex.status === "add" && "bg-success-muted text-success-muted-foreground",
                    ex.status === "warn" && "bg-warning-muted text-warning-muted-foreground",
                  )}
                >
                  {ex.status === "drop" ? "wypada" : ex.status === "add" ? "dochodzi" : "z ostrzeżeniem"}
                </span>
                {ex.job.title} ↔ {ex.other.title} <span className="text-muted-foreground">· {ex.similarity}%</span>
                {ex.reason ? <span className="block text-xs text-muted-foreground">{ex.reason}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {canEdit ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => setDraft(query.data.defaults)}>
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            Przywróć zasady startowe
          </Button>
          <span className="flex-1" />
          <Button variant="ghost" disabled={!dirty} onClick={() => setDraft(query.data.rules)}>
            Anuluj
          </Button>
          <Button disabled={!dirty || save.isPending} onClick={() => void onSave()} data-testid="twin-rules-save">
            {save.isPending ? "Zapisuję…" : "Zapisz dla całej firmy"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
