"use client";

import type { RankingPanelState, RankingPanelWeights } from "@/lib/api";
import { cn } from "@/lib/utils";

import { ShareBar } from "./HowItWorksTab";
import { LivePreview } from "./LivePreview";
import { ScoringProfilesAdmin } from "./ScoringProfilesAdmin";
import { EDITABLE, LAYER_COLORS, LAYER_LABELS, SLIDER_HINTS, formatDate } from "./rankingCopy";
import { panelShares, sameWeights } from "./rankingMath";

export interface WeightsTabProps {
  state: RankingPanelState;
  local: RankingPanelWeights;
  onChange: (next: RankingPanelWeights) => void;
  canEdit: boolean;
  isAdmin: boolean;
  busy: boolean;
  actionError: string | null;
  onDiscard: () => void;
  onCheck: () => void;
}

export function draftProblem(local: RankingPanelWeights): string | null {
  if (local.semantic + local.skills + local.location <= 0) {
    return "Ustaw co najmniej jedną ważność większą od zera — inaczej wszyscy mieliby ten sam wynik.";
  }
  return null;
}

export function WeightsTab({
  state,
  local,
  onChange,
  canEdit,
  isAdmin,
  busy,
  actionError,
  onDiscard,
  onCheck,
}: WeightsTabProps) {
  const published = state.published.weights;
  const changed = !sameWeights(local, published);
  const shares = panelShares(local);
  const problem = draftProblem(local);
  const measuring =
    state.measurement?.status === "queued" || state.measurement?.status === "running";
  const set = (key: keyof RankingPanelWeights) => (value: number) =>
    onChange({ ...local, [key]: value });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card px-4 py-3">
        <span className="text-sm text-muted-foreground">
          Obowiązują we wszystkich rekrutacjach ·{" "}
          {state.published.source === "built_in"
            ? "wagi wbudowane (od 17.08.2026)"
            : `opublikowane ${formatDate(state.published.updated_at)}`}
        </span>
        <span className="flex-1" />
        {changed ? (
          <span className="rounded-full bg-warning-muted px-2.5 py-1 text-xs font-semibold text-warning-muted-foreground">
            Szkic — zespół go nie widzi
          </span>
        ) : (
          <span className="rounded-full bg-success-muted px-2.5 py-1 text-xs font-semibold text-success-muted-foreground">
            Zgodne z opublikowanymi
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-start gap-5">
        <section
          aria-labelledby="ranking-weights"
          className="flex min-w-0 flex-[1_1_26rem] flex-col gap-4 rounded-xl border border-border bg-card p-5"
        >
          <div className="space-y-1">
            <h2 id="ranking-weights" className="text-base font-semibold text-foreground">
              Co liczy się najbardziej
            </h2>
            <p className="text-sm text-muted-foreground">
              Ustawiasz ważność. Udział w ocenie przelicza się sam — nie trzeba dobijać do 100.
            </p>
          </div>
          <ShareBar shares={shares} />

          {EDITABLE.map((layer) => (
            <Slider
              key={layer}
              id={`ranking-${layer}`}
              label={LAYER_LABELS[layer]}
              hint={SLIDER_HINTS[layer]}
              colorClass={LAYER_COLORS[layer]}
              value={local[layer]}
              display={`${Math.round(shares[layer])}%`}
              min={0}
              max={100}
              onChange={set(layer)}
            />
          ))}

          <div className="space-y-2 border-t border-border pt-3.5">
            <LockedLayer label="Stawka" colorClass={LAYER_COLORS.salary} badge="plakietka, nie punkty" />
            <LockedLayer label="Dostępność" colorClass={LAYER_COLORS.availability} badge="wyłączona" />
            <p className="text-xs text-muted-foreground">
              Nie zmieniają kolejności — decyzje z 30.09 i 17.08 (szczegóły w „Jak to działa”).
            </p>
          </div>

          <div className="border-t border-border pt-3.5">
            <Slider
              id="ranking-threshold"
              label="Próg nocnych propozycji"
              hint="Osoby z „Dop.” od tej wartości trafiają rano do „Propozycji z bazy”."
              value={local.threshold}
              display={`${local.threshold}%`}
              min={state.limits.threshold_min}
              max={state.limits.threshold_max}
              onChange={set("threshold")}
            />
          </div>

          <div className="flex flex-wrap gap-2">
            <PresetButton onClick={() => onChange(published)}>Przywróć opublikowane</PresetButton>
            <PresetButton onClick={() => onChange({ ...local, skills: Math.max(local.skills, 30) })}>
              Spróbuj: więcej umiejętności
            </PresetButton>
            <PresetButton onClick={() => onChange({ ...local, location: Math.max(local.location, 20) })}>
              Spróbuj: więcej lokalizacji
            </PresetButton>
          </div>
          {problem && (
            <p role="alert" className="text-sm text-destructive">
              {problem}
            </p>
          )}
        </section>

        <LivePreview published={published} local={local} />
      </div>

      <div className="flex flex-wrap items-center justify-end gap-3 rounded-xl border border-border bg-card px-4 py-3.5">
        {canEdit ? (
          <>
            <span className="min-w-60 flex-1 text-sm text-muted-foreground">
              {measuring
                ? "Pomiar szkicu trwa — wynik zobaczysz w „Historia zmian”."
                : "Przed publikacją NEXUS sprawdzi szkic na 120 zamkniętych rekrutacjach (ok. 5 minut)."}
            </span>
            {actionError && (
              <p role="alert" className="basis-full text-right text-sm text-destructive">
                {actionError}
              </p>
            )}
            <button
              type="button"
              onClick={onDiscard}
              disabled={busy || (!changed && !state.draft)}
              className="min-h-11 rounded-lg border border-border bg-card px-3.5 text-sm text-foreground hover:bg-muted disabled:opacity-50"
            >
              Odrzuć szkic
            </button>
            <button
              type="button"
              onClick={onCheck}
              disabled={busy || measuring || !changed || problem !== null}
              className="min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              Sprawdź na historii
            </button>
          </>
        ) : (
          <span className="flex-1 text-sm text-muted-foreground">
            Możesz sprawdzić, jak zmieniłaby się lista. Zapisać i opublikować wagi może Head of
            Recruitment albo administrator.
          </span>
        )}
      </div>

      {isAdmin && (
        <details className="rounded-xl border border-border bg-card px-5 py-3">
          <summary className="cursor-pointer text-sm font-semibold text-foreground">
            Profile klienta i osoby (administrator)
          </summary>
          <div className="pt-3">
            <ScoringProfilesAdmin />
          </div>
        </details>
      )}
    </div>
  );
}

interface SliderProps {
  id: string;
  label: string;
  hint: string;
  value: number;
  display: string;
  min: number;
  max: number;
  colorClass?: string;
  onChange: (value: number) => void;
}

function Slider({ id, label, hint, value, display, min, max, colorClass, onChange }: SliderProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline gap-2">
        {colorClass && <span className={cn("h-2.5 w-2.5 shrink-0 rounded-sm", colorClass)} aria-hidden />}
        <label htmlFor={id} className="flex-1 text-sm font-semibold text-foreground">
          {label}
        </label>
        <span className="text-sm font-bold tabular-nums text-foreground">{display}</span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={5}
        value={value}
        aria-valuetext={display}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full accent-primary"
      />
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}

function LockedLayer({ label, colorClass, badge }: { label: string; colorClass: string; badge: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className={cn("h-2.5 w-2.5 shrink-0 rounded-sm", colorClass)} aria-hidden />
      <span className="flex-1 text-sm font-semibold text-muted-foreground">{label}</span>
      <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{badge}</span>
    </div>
  );
}

function PresetButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="min-h-10 rounded-lg border border-border bg-card px-3 text-sm text-foreground hover:bg-muted"
    >
      {children}
    </button>
  );
}
