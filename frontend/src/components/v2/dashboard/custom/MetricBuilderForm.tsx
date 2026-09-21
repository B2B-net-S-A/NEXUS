"use client"

// Kreator własnej metryki: pięć kroków (źródło → co liczymy → filtry →
// podział i okres → wygląd). Dostępne źródła i zakresy bierze z serwerowego
// katalogu — front nie zgaduje uprawnień. Każda zmiana poprawia definicję tak,
// żeby zawsze dało się ją policzyć (np. zmiana źródła czyści filtry, których
// nowe źródło nie ma), bo serwer odrzuca kombinacje, których nie umie.

import { useQuery } from "@tanstack/react-query"
import { Lock } from "lucide-react"

import { ClientSinglePicker, type ClientRef } from "@/components/clients/ClientSinglePicker"
import { CompetenceCategoryMultiSelect } from "@/components/v2/filters/CompetenceCategoryMultiSelect"
import { api } from "@/lib/api"
import type { MetricCatalog, MetricCatalogSource } from "@/lib/api/dashboardMetrics"
import type {
  MetricAuthor,
  MetricDefinition,
  MetricGroupBy,
  MetricPeriod,
  TileChart,
  TileType,
} from "@/lib/api/userDashboard"
import { AUTHOR_LABELS } from "@/lib/dashboard-tiles/layout"
import { cn } from "@/lib/utils"

export const GROUP_LABELS: Record<MetricGroupBy, string> = {
  none: "Bez podziału (jedna liczba)",
  week: "Po tygodniach",
  month: "Po miesiącach",
  client: "Po klientach",
  recruiter: "Po osobach",
  stage: "Po etapach",
  competence_category: "Po kategoriach kompetencji",
}

const CLIENTS_KEY = "dashboard-metric-clients"

const SELECT_CLASS =
  "h-9 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground"

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <fieldset className="flex gap-3">
      <span
        aria-hidden
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground"
      >
        {n}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <legend className="text-sm font-semibold leading-6 text-foreground">{title}</legend>
        {children}
      </div>
    </fieldset>
  )
}

/** Dostosowuje definicję do źródła: miary, podziały i filtry, które zna. */
export function normalizeForSource(
  metric: MetricDefinition,
  source: MetricCatalogSource,
  tileType: TileType,
): MetricDefinition {
  const measure = source.measures.some((m) => m.key === metric.measure)
    ? metric.measure
    : source.measures[0]?.key ?? metric.measure
  const snapshot = source.measures.find((m) => m.key === measure)?.snapshot ?? false
  let groupBy: MetricGroupBy = metric.group_by ?? "none"
  if (!source.group_by.includes(groupBy)) groupBy = "none"
  if (snapshot && (groupBy === "week" || groupBy === "month")) groupBy = "none"
  if (tileType === "metric_funnel") groupBy = "stage"
  if (tileType === "metric_number" && groupBy !== "week" && groupBy !== "month") {
    groupBy = "none"
  }
  const filters = { ...(metric.filters ?? {}) }
  if (!source.filters.includes("client_ids")) delete filters.client_ids
  if (!source.filters.includes("competence_category_ids")) delete filters.competence_category_ids
  if (!source.filters.includes("job_ids")) delete filters.job_ids
  let stage = source.key === "pipeline_moves" ? (metric.stage ?? "cv_sent") : null
  if (groupBy === "stage") stage = null
  return {
    ...metric,
    source: source.key,
    measure,
    stage,
    group_by: groupBy,
    filters,
    compare_previous: snapshot ? false : metric.compare_previous,
  }
}

export function MetricBuilderForm({
  value,
  onChange,
  catalog,
  tileType,
  chart,
  onChartChange,
}: {
  value: MetricDefinition
  onChange: (next: MetricDefinition) => void
  catalog: MetricCatalog
  tileType: TileType
  chart?: TileChart | null
  onChartChange?: (chart: TileChart) => void
}) {
  const source =
    catalog.sources.find((s) => s.key === value.source) ?? catalog.sources[0]
  const measure = source.measures.find((m) => m.key === value.measure)
  const snapshot = measure?.snapshot ?? false
  const funnel = tileType === "metric_funnel"

  const clientsQuery = useQuery({
    queryKey: [CLIENTS_KEY],
    queryFn: async () => (await api.get<ClientRef[]>("/api/clients-lookup")).data,
    staleTime: 5 * 60_000,
  })
  const clientId = value.filters?.client_ids?.[0] ?? null
  const clientRef: ClientRef | null =
    clientId == null
      ? null
      : (clientsQuery.data?.find((c) => c.id === clientId) ?? ({ id: clientId, name: "" } as ClientRef))

  const set = (patch: Partial<MetricDefinition>) =>
    onChange(normalizeForSource({ ...value, ...patch }, source, tileType))
  const setFilters = (patch: Partial<NonNullable<MetricDefinition["filters"]>>) =>
    onChange({ ...value, filters: { ...(value.filters ?? {}), ...patch } })

  const groupOptions = source.group_by.filter((g) => {
    if (funnel) return g === "stage"
    if (g === "stage") return false
    if (snapshot && (g === "week" || g === "month")) return false
    if (tileType === "metric_number") return g === "none" || g === "week" || g === "month"
    return true
  }) as MetricGroupBy[]

  const sources = funnel
    ? catalog.sources.filter((s) => s.key === "pipeline_moves")
    : catalog.sources

  return (
    <div className="flex flex-col gap-5">
      <Step n={1} title="Z jakich danych">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Źródło danych">
          {sources.map((s) => {
            const active = s.key === source.key
            return (
              <button
                key={s.key}
                type="button"
                role="radio"
                aria-checked={active}
                disabled={!s.available}
                title={s.reason ?? undefined}
                onClick={() =>
                  onChange(normalizeForSource({ ...value, source: s.key }, s, tileType))
                }
                className={cn(
                  "flex flex-col items-start gap-0.5 rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                  active
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border bg-card text-foreground hover:bg-muted",
                  !s.available && "cursor-not-allowed opacity-55 hover:bg-card",
                )}
              >
                <span className="flex items-center gap-1.5 font-semibold">
                  {!s.available ? <Lock className="h-3.5 w-3.5" aria-hidden /> : null}
                  {s.label}
                </span>
                {!s.available && s.reason ? (
                  <span className="text-xs text-muted-foreground">{s.reason}</span>
                ) : null}
              </button>
            )
          })}
        </div>
      </Step>

      <Step n={2} title="Co liczymy">
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Miara
            <select
              className={SELECT_CLASS}
              value={value.measure}
              onChange={(e) => set({ measure: e.target.value })}
            >
              {source.measures.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          {source.key === "pipeline_moves" && !funnel ? (
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              Etap
              <select
                className={SELECT_CLASS}
                value={value.stage ?? "cv_sent"}
                onChange={(e) => set({ stage: e.target.value })}
              >
                {catalog.stages.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
      </Step>

      <Step n={3} title="Filtry">
        {source.supports_author ? (
          <div role="radiogroup" aria-label="Czyje dane" className="inline-flex w-fit gap-0.5 rounded-lg bg-muted p-1">
            {(["me", "team", "all"] as MetricAuthor[]).map((a) => {
              const allowed = catalog.authors.includes(a)
              const active = (value.filters?.author ?? "me") === a
              return (
                <button
                  key={a}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  disabled={!allowed}
                  title={allowed ? undefined : "Twoje uprawnienia na to nie pozwalają"}
                  onClick={() => setFilters({ author: a })}
                  className={cn(
                    "h-8 rounded-md px-3 text-sm font-medium",
                    active ? "bg-card text-foreground shadow-xs" : "text-muted-foreground",
                    !allowed && "cursor-not-allowed opacity-45",
                  )}
                >
                  {AUTHOR_LABELS[a]}
                </button>
              )
            })}
          </div>
        ) : null}
        <div className="grid gap-2 sm:grid-cols-2">
          {source.filters.includes("client_ids") ? (
            <div className="flex flex-col gap-1 text-xs text-muted-foreground">
              Klient
              <ClientSinglePicker
                value={clientRef}
                onChange={(c) => setFilters({ client_ids: c ? [c.id] : [] })}
                queryKey={CLIENTS_KEY}
                placeholder="Wszyscy klienci"
                allowClear
              />
            </div>
          ) : null}
          {source.filters.includes("competence_category_ids") ? (
            <div className="flex flex-col gap-1 text-xs text-muted-foreground">
              Kategoria kompetencji
              <CompetenceCategoryMultiSelect
                value={value.filters?.competence_category_ids ?? []}
                onChange={(ids) => setFilters({ competence_category_ids: ids })}
                triggerWidthClass="w-full"
              />
            </div>
          ) : null}
        </div>
        {!source.supports_author &&
        !source.filters.includes("client_ids") &&
        !source.filters.includes("competence_category_ids") ? (
          <p className="text-xs text-muted-foreground">To źródło nie ma filtrów.</p>
        ) : null}
      </Step>

      <Step n={4} title="Podział i okres">
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Podział
            <select
              className={SELECT_CLASS}
              value={value.group_by ?? "none"}
              disabled={groupOptions.length <= 1}
              onChange={(e) => set({ group_by: e.target.value as MetricGroupBy })}
            >
              {groupOptions.map((g) => (
                <option key={g} value={g}>
                  {GROUP_LABELS[g]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Okres
            <select
              className={SELECT_CLASS}
              value={value.period ?? "last_30_days"}
              disabled={snapshot}
              onChange={(e) => set({ period: e.target.value as MetricPeriod })}
            >
              {catalog.periods.map((p) => (
                <option key={p.key} value={p.key}>
                  {snapshot ? "stan na dziś" : p.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {!snapshot && source.key !== "finance" ? (
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              className="h-4 w-4 accent-[hsl(var(--primary))]"
              checked={Boolean(value.compare_previous)}
              onChange={(e) => set({ compare_previous: e.target.checked })}
            />
            Pokaż zmianę względem poprzedniego okresu
          </label>
        ) : null}
      </Step>

      {tileType === "metric_chart" && onChartChange ? (
        <Step n={5} title="Wygląd">
          <div role="radiogroup" aria-label="Wygląd wykresu" className="grid grid-cols-3 gap-2">
            {(
              [
                ["bars", "Słupki"],
                ["line", "Linia"],
                ["table", "Tabela"],
              ] as [TileChart, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="radio"
                aria-checked={(chart ?? "bars") === key}
                onClick={() => onChartChange(key)}
                className={cn(
                  "h-10 rounded-lg border text-sm font-medium",
                  (chart ?? "bars") === key
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border bg-card text-muted-foreground hover:bg-muted",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </Step>
      ) : null}
    </div>
  )
}
