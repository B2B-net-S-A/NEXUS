"use client";

import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AppModal } from "@/components/ds";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  WORK_RHYTHM_KINDS,
  WORK_RHYTHM_KIND_LABELS as KIND_LABELS,
  workRhythmApi,
  workRhythmQueryKeys,
  type WorkRhythmRules,
} from "@/lib/work-rhythm-api";

/**
 * Edycja reguł „Rytmu dnia” (Head of Recruitment i admin, decyzja Artura
 * 28.10.2026). Serwer sprawdza zakresy i kolejność progów; tu tylko pola
 * i to samo sprawdzenie progów, żeby błąd był widać przed zapisem.
 */

type Draft = Record<string, string>;

const GUARD_KEYS = [
  "auto_cv_points",
  "stage_return_points",
  "screening_per_candidate_day",
  "repeats_per_hour",
  "views_per_hour",
  "bulk_per_minute",
  "contacts_per_day",
  "thin_hour_candidates",
] as const;

/** Ochrona przed nabijaniem (decyzja Artura 29.10.2026); limit 0 = bez limitu. */
const GUARD_FIELDS: { key: (typeof GUARD_KEYS)[number]; label: string; suffix?: string }[] = [
  { key: "auto_cv_points", label: "CV wygenerowane przez automat", suffix: "pkt" },
  { key: "stage_return_points", label: "Powrót karty na ten sam etap tego dnia", suffix: "pkt" },
  { key: "screening_per_candidate_day", label: "Screening tego samego kandydata liczy się", suffix: "× / d." },
  { key: "repeats_per_hour", label: "Inny zapis tej samej rzeczy liczy się", suffix: "× / h" },
  { key: "views_per_hour", label: "Podglądów liczonych w godzinie najwyżej" },
  { key: "bulk_per_minute", label: "Masowa akcja od (ten sam zapis w minutę)", suffix: "szt." },
  { key: "contacts_per_day", label: "Prób kontaktu liczonych dziennie najwyżej" },
  { key: "thin_hour_candidates", label: "Godzina z drobnych akcji wymaga kandydatów" },
];

function toDraft(rules: WorkRhythmRules): Draft {
  const draft: Draft = {};
  for (const kind of WORK_RHYTHM_KINDS) draft[`w_${kind}`] = String(rules.weights[kind]);
  rules.hour_levels.forEach((v, i) => (draft[`lvl_${i}`] = String(v)));
  for (const key of [
    "work_hour_min_points",
    "norm_work_hours",
    "norm_day_points",
    "level_high",
    "level_mid",
    "diag_intensity",
    "diag_results_pct",
    ...GUARD_KEYS,
  ] as const) {
    draft[key] = String(rules[key]);
  }
  return draft;
}

function num(value: string): number {
  return Number(value.replace(",", "."));
}

export function draftToRules(draft: Draft): WorkRhythmRules {
  const weights = Object.fromEntries(
    WORK_RHYTHM_KINDS.map((kind) => [kind, num(draft[`w_${kind}`])]),
  ) as WorkRhythmRules["weights"];
  return {
    weights,
    hour_levels: [num(draft.lvl_0), num(draft.lvl_1), num(draft.lvl_2)],
    work_hour_min_points: num(draft.work_hour_min_points),
    norm_work_hours: num(draft.norm_work_hours),
    norm_day_points: num(draft.norm_day_points),
    level_high: Math.round(num(draft.level_high)),
    level_mid: Math.round(num(draft.level_mid)),
    diag_intensity: Math.round(num(draft.diag_intensity)),
    diag_results_pct: Math.round(num(draft.diag_results_pct)),
    auto_cv_points: num(draft.auto_cv_points),
    stage_return_points: num(draft.stage_return_points),
    screening_per_candidate_day: Math.round(num(draft.screening_per_candidate_day)),
    repeats_per_hour: Math.round(num(draft.repeats_per_hour)),
    views_per_hour: Math.round(num(draft.views_per_hour)),
    bulk_per_minute: Math.round(num(draft.bulk_per_minute)),
    contacts_per_day: Math.round(num(draft.contacts_per_day)),
    thin_hour_candidates: Math.round(num(draft.thin_hour_candidates)),
  };
}

/** Pierwszy błąd do pokazania przed zapisem albo `null`. */
export function draftProblem(rules: WorkRhythmRules): string | null {
  const values = [
    ...Object.values(rules.weights),
    ...rules.hour_levels,
    rules.work_hour_min_points,
    rules.norm_work_hours,
    rules.norm_day_points,
    ...GUARD_KEYS.map((key) => rules[key]),
  ];
  if (values.some((v) => !Number.isFinite(v))) return "Wpisz liczby we wszystkich polach.";
  if (GUARD_KEYS.some((key) => rules[key] < 0)) return "Limity i punkty ochrony nie mogą być ujemne.";
  const [low, mid, high] = rules.hour_levels;
  if (!(low > 0 && low < mid && mid < high)) {
    return "Progi godziny muszą rosnąć: robocza < intensywna < bardzo intensywna.";
  }
  if (rules.level_mid >= rules.level_high) return "Próg „średnia” musi być niższy niż „wysoka”.";
  return null;
}

function Field({
  id,
  label,
  value,
  onChange,
  suffix,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  suffix?: string;
}) {
  return (
    <label htmlFor={id} className="flex items-center justify-between gap-3 text-sm">
      <span className="min-w-0 text-foreground">{label}</span>
      <span className="flex shrink-0 items-center gap-1.5">
        <Input
          id={id}
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-8 w-20 text-right tabular-nums"
        />
        {suffix ? <span className="w-8 text-xs text-muted-foreground">{suffix}</span> : null}
      </span>
    </label>
  );
}

export function RhythmRulesDialog({
  open,
  onOpenChange,
  rules,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  rules: WorkRhythmRules;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = React.useState<Draft>(() => toDraft(rules));
  React.useEffect(() => {
    if (open) setDraft(toDraft(rules));
  }, [open, rules]);
  const set = (key: string) => (v: string) => setDraft((d) => ({ ...d, [key]: v }));
  const parsed = draftToRules(draft);
  const problem = draftProblem(parsed);

  const save = useMutation({
    mutationFn: () => workRhythmApi.saveRules(parsed),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: workRhythmQueryKeys.all });
      onOpenChange(false);
    },
  });

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Reguły rytmu dnia"
      description="Zmiana działa od razu dla całego zespołu, także wstecz dla widocznych dni."
      size="lg"
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <span className="text-sm text-destructive">
            {problem ?? (save.isError ? apiErrorMessage(save.error, "Nie udało się zapisać reguł.") : "")}
          </span>
          <span className="flex gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Anuluj
            </Button>
            <Button onClick={() => save.mutate()} disabled={Boolean(problem) || save.isPending}>
              {save.isPending ? "Zapisuję…" : "Zapisz reguły"}
            </Button>
          </span>
        </div>
      }
    >
      <div className="grid gap-6 md:grid-cols-2">
        <section className="space-y-2" aria-label="Punkty za akcję">
          <p className="text-sm font-semibold text-foreground">Punkty pracy za akcję</p>
          {WORK_RHYTHM_KINDS.map((kind) => (
            <Field key={kind} id={`rytm-w-${kind}`} label={KIND_LABELS[kind]} value={draft[`w_${kind}`]} onChange={set(`w_${kind}`)} suffix="pkt" />
          ))}
        </section>
        <section className="space-y-2" aria-label="Progi i normy">
          <p className="text-sm font-semibold text-foreground">Poziom godziny — od ilu punktów</p>
          <Field id="rytm-lvl-0" label="Robocza" value={draft.lvl_0} onChange={set("lvl_0")} suffix="pkt" />
          <Field id="rytm-lvl-1" label="Intensywna" value={draft.lvl_1} onChange={set("lvl_1")} suffix="pkt" />
          <Field id="rytm-lvl-2" label="Bardzo intensywna" value={draft.lvl_2} onChange={set("lvl_2")} suffix="pkt" />
          <p className="pt-2 text-sm font-semibold text-foreground">Norma dnia</p>
          <Field id="rytm-work-min" label="Godzina pracy od" value={draft.work_hour_min_points} onChange={set("work_hour_min_points")} suffix="pkt" />
          <Field id="rytm-norm-hours" label="Godzin pracy" value={draft.norm_work_hours} onChange={set("norm_work_hours")} suffix="h" />
          <Field id="rytm-norm-points" label="Punktów dnia" value={draft.norm_day_points} onChange={set("norm_day_points")} suffix="pkt" />
          <p className="pt-2 text-sm font-semibold text-foreground">Poziomy i podpowiedź</p>
          <Field id="rytm-high" label="Wysoka intensywność od" value={draft.level_high} onChange={set("level_high")} />
          <Field id="rytm-mid" label="Średnia intensywność od" value={draft.level_mid} onChange={set("level_mid")} />
          <Field id="rytm-diag-i" label="„Dużo pracy” od intensywności" value={draft.diag_intensity} onChange={set("diag_intensity")} />
          <Field id="rytm-diag-r" label="„Dobre wyniki” od mediany CV" value={draft.diag_results_pct} onChange={set("diag_results_pct")} suffix="%" />
        </section>
        <section className="space-y-2 md:col-span-2" aria-label="Ochrona przed nabijaniem">
          <p className="text-sm font-semibold text-foreground">Ochrona przed nabijaniem</p>
          <p className="text-xs text-muted-foreground">Limit 0 = bez limitu. Akcje ponad limit zostają w rozkładzie dnia z powodem, ale nie dają punktów.</p>
          <div className="grid gap-x-6 gap-y-2 md:grid-cols-2">
            {GUARD_FIELDS.map((f) => (
              <Field key={f.key} id={`rytm-g-${f.key}`} label={f.label} value={draft[f.key]} onChange={set(f.key)} suffix={f.suffix} />
            ))}
          </div>
        </section>
      </div>
    </AppModal>
  );
}
