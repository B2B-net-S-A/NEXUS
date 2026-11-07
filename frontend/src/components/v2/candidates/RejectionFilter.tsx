"use client";

import { cn } from "@/lib/utils";
import type { CandidateFilters, RejectionWho } from "@/lib/url-filters";
import { PillGroup, toggleInList } from "@/components/v2/candidates/filters/FilterPillGroup";
import {
  REJECTION_MONTHS_OPTIONS,
  REJECTION_WHO_LABELS,
  NO_REASON_KEY,
  TRAFFIT_KEY_PREFIX,
  cycleFacetKey,
  rejectionKeyLabel,
  type RejectionFacets,
} from "@/lib/candidate-last-rejection";

/**
 * „Powód odrzucenia” (06.11.2026, wariant C z makiet
 * https://claude.ai/artifact/HfjaZy1PzPFEaLNMayNNfx): pigułka w rzędzie
 * filtrów i pasek „Ostatnie odrzucenie w tym wyniku” nad tabelą. Oba czytają
 * ten sam rozkład z API (`rejection_facets`), liczony bez samego filtra
 * odrzucenia — liczby mówią, ile osób z bieżącego wyniku ma dany powód.
 */

type RejectionPatch = Partial<
  Pick<CandidateFilters, "rejectionKeys" | "rejectionBy" | "rejectionWithinMonths" | "rejectionExclude">
>;

interface RejectionFilterProps {
  filters: CandidateFilters;
  onPatch: (patch: RejectionPatch) => void;
  /** `undefined` = jeszcze się liczy, `null` = nie udało się policzyć. */
  facets: RejectionFacets | null | undefined;
}

const WHO_OPTIONS = (Object.keys(REJECTION_WHO_LABELS) as RejectionWho[]).map((value) => ({
  value,
  label: REJECTION_WHO_LABELS[value],
}));

function Segmented<V extends string | number>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: ReadonlyArray<{ value: V; label: string }>;
  value: V;
  onChange: (value: V) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex overflow-hidden rounded-md border border-border">
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            "px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
            o.value === value ? "bg-primary text-primary-foreground" : "bg-card text-foreground hover:bg-accent",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function ReasonOption({
  label,
  count,
  checked,
  onToggle,
}: {
  label: string;
  count: number | null;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 rounded px-1 py-0.5 text-sm hover:bg-accent">
      <span className="flex min-w-0 items-center gap-2">
        <input type="checkbox" checked={checked} onChange={onToggle} className="h-3.5 w-3.5 accent-primary" />
        <span className="truncate">{label}</span>
      </span>
      {count !== null ? (
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{count}</span>
      ) : null}
    </label>
  );
}

/** Zawartość pigułki „Powód odrzucenia”. */
export function RejectionFilterFields({ filters, onPatch, facets }: RejectionFilterProps) {
  const counts = new Map((facets?.items ?? []).map((it) => [it.key, it]));
  // Wybrany klucz zostaje na liście, nawet gdy w tym wyniku nikt go nie ma.
  const keys = [
    ...(facets?.items ?? []).map((it) => it.key),
    ...filters.rejectionKeys.filter((k) => !counts.has(k)),
  ];
  // „Bez powodu” na końcu — to brak danych, nie powód.
  const nexus = keys
    .filter((k) => !k.startsWith(TRAFFIT_KEY_PREFIX))
    .sort((a, b) => Number(a === NO_REASON_KEY) - Number(b === NO_REASON_KEY));
  const traffit = keys.filter((k) => k.startsWith(TRAFFIT_KEY_PREFIX));
  const toggleKey = (key: string) => onPatch({ rejectionKeys: toggleInList(filters.rejectionKeys, key) });
  const whoCounts = new Map((facets?.who ?? []).map((w) => [w.key, w.count]));

  const option = (key: string) => (
    <ReasonOption
      key={key}
      label={counts.get(key)?.label ?? rejectionKeyLabel(key)}
      count={counts.get(key)?.count ?? (facets ? 0 : null)}
      checked={filters.rejectionKeys.includes(key)}
      onToggle={() => toggleKey(key)}
    />
  );

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Najnowsze odrzucenie albo rezygnacja osoby — także gdy potem weszła w nowy proces.
      </p>
      <div className="flex flex-wrap gap-2">
        <Segmented
          label="Pokaż czy ukryj"
          options={[
            { value: "show", label: "Pokaż tylko" },
            { value: "hide", label: "Ukryj" },
          ]}
          value={filters.rejectionExclude ? "hide" : "show"}
          onChange={(v) => onPatch({ rejectionExclude: v === "hide" })}
        />
        <Segmented
          label="Kiedy"
          options={REJECTION_MONTHS_OPTIONS}
          value={filters.rejectionWithinMonths}
          onChange={(v) => onPatch({ rejectionWithinMonths: v })}
        />
      </div>
      <PillGroup
        label="Kto zakończył"
        options={WHO_OPTIONS.map((o) => ({
          ...o,
          label: whoCounts.has(o.value) ? `${o.label} · ${whoCounts.get(o.value)}` : o.label,
        }))}
        value={filters.rejectionBy}
        onToggle={(v) => onPatch({ rejectionBy: toggleInList(filters.rejectionBy, v) })}
      />
      <div className="space-y-1">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          Powód (NEXUS, od 12.10.2026)
        </p>
        {facets === undefined ? (
          <p className="text-xs text-muted-foreground">Liczę powody w tym wyniku…</p>
        ) : facets === null ? (
          <p className="text-xs text-destructive">Nie udało się policzyć powodów. Odśwież listę.</p>
        ) : nexus.length === 0 ? (
          <p className="text-xs text-muted-foreground">Nikt w tym wyniku nie ma powodu ze słownika.</p>
        ) : (
          <div>{nexus.map(option)}</div>
        )}
      </div>
      {traffit.length > 0 ? (
        <div className="space-y-1">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Traffit (kategoria zamiast powodu)
          </p>
          <div>{traffit.map(option)}</div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Pasek nad tabelą: rozkład ostatnich odrzuceń w bieżącym wyniku. Tylko od
 * 1800 px (decyzja Artura 07.11.2026): przy 1280 × 720 osobny rząd spychał
 * pierwszy wiersz listy na 0,66 okna. Poniżej ten sam rozkład jest
 * w pigułce „Odrzucenie”.
 */
export function RejectionFacetBar({ filters, onPatch, facets }: RejectionFilterProps) {
  if (!facets || facets.items.length === 0) return null;
  return (
    <div
      role="group"
      aria-label="Ostatnie odrzucenie w tym wyniku"
      className="hidden items-center min-[1800px]:flex gap-1.5 overflow-x-auto rounded-lg border border-dashed border-primary/30 bg-primary/5 px-2.5 py-1.5"
    >
      <span className="shrink-0 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        Ostatnie odrzucenie
      </span>
      <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
        bez odrzucenia {facets.without_rejection}
      </span>
      {facets.items.map((it) => {
        const on = filters.rejectionKeys.includes(it.key);
        const hidden = on && filters.rejectionExclude;
        return (
          <button
            key={it.key}
            type="button"
            aria-pressed={on}
            title={
              hidden
                ? "Ukryte — kliknij, żeby zdjąć"
                : on
                  ? "Pokazane tylko te osoby — kliknij, żeby je ukryć"
                  : "Kliknij, żeby pokazać tylko te osoby"
            }
            onClick={() => onPatch(cycleFacetKey(filters, it.key))}
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
              hidden
                ? "border-destructive text-destructive line-through"
                : on
                  ? "border-primary bg-primary/10 font-medium text-primary"
                  : "border-border bg-card text-foreground hover:bg-accent",
            )}
          >
            {it.label}
            <span className="tabular-nums text-muted-foreground">{it.count}</span>
          </button>
        );
      })}
    </div>
  );
}
