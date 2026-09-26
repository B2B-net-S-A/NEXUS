"use client"

// Okno ustawień kafelka — to samo dla dodawania i edycji.
//
// Kafelek metryki dostaje kreator (pięć kroków) i podgląd liczony na żywo,
// notatka — tekst i linki, pozostałe — sam tytuł. Podgląd pyta serwer tą samą
// trasą co kafelek na pulpicie, więc „Brak dostępu" widać, zanim kafelek
// trafi na pulpit.

import { useDeferredValue, useEffect, useState } from "react"
import { Plus, Trash2 } from "lucide-react"

import { AppModal } from "@/components/ds/AppModal"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useMetricCatalog } from "@/lib/api/dashboardMetrics"
import type { DashboardTile, NoteLink, TileConfig } from "@/lib/api/userDashboard"
import { TILE_DEFINITIONS, tileTitle } from "@/lib/dashboard-tiles/catalog"
import { describeMetric } from "@/lib/dashboard-tiles/describe"
import { safeInternalPath } from "@/lib/safe-href"

import { MetricBuilderForm } from "./MetricBuilderForm"
import { MetricTileBody } from "./MetricTileBody"

const METRIC_TYPES = new Set(["metric_number", "metric_chart", "metric_funnel"])

// Lustro walidacji `NoteLink` na serwerze (runda 8, R8-N10-5: bez `/\host`).
function isSafeLink(url: string): boolean {
  return url.startsWith("https://") || safeInternalPath(url) !== null
}

export function TileSettingsDialog({
  tile,
  mode,
  onCancel,
  onSubmit,
}: {
  tile: DashboardTile | null
  mode: "add" | "edit"
  onCancel: () => void
  onSubmit: (config: TileConfig) => void
}) {
  const [config, setConfig] = useState<TileConfig>(tile?.config ?? {})
  useEffect(() => {
    setConfig(tile?.config ?? {})
  }, [tile])

  const isMetric = tile ? METRIC_TYPES.has(tile.type) : false
  const catalog = useMetricCatalog(Boolean(tile) && isMetric)
  const previewMetric = useDeferredValue(config.metric ?? null)

  if (!tile) return null
  const def = TILE_DEFINITIONS[tile.type]
  const links = config.links ?? []
  const badLink = links.some((l) => l.url.trim() !== "" && !isSafeLink(l.url.trim()))
  const cleanLinks = links
    .map((l) => ({ label: l.label.trim(), url: l.url.trim() }))
    .filter((l) => l.label && l.url)

  const submit = () =>
    onSubmit({
      ...config,
      title: config.title?.trim() || null,
      ...(tile.type === "note" ? { links: cleanLinks } : {}),
    })

  const setLink = (index: number, patch: Partial<NoteLink>) =>
    setConfig((c) => ({
      ...c,
      links: (c.links ?? []).map((l, i) => (i === index ? { ...l, ...patch } : l)),
    }))

  return (
    <AppModal
      open
      onOpenChange={(open) => (!open ? onCancel() : undefined)}
      size={isMetric ? "xl" : "md"}
      title={mode === "add" ? `Dodaj: ${def.label}` : `Ustawienia: ${tileTitle(tile)}`}
      description={
        isMetric
          ? "Ustaw, co kafelek ma liczyć. Podgląd po prawej liczy się na żywo."
          : def.description
      }
      footer={
        <>
          <Button variant="outline" onClick={onCancel}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={badLink || (isMetric && !config.metric)}>
            {mode === "add" ? "Dodaj do pulpitu" : "Zapisz"}
          </Button>
        </>
      }
    >
      <div className={isMetric ? "grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]" : "flex flex-col gap-4"}>
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Tytuł kafelka
            <Input
              value={config.title ?? ""}
              placeholder={def.label}
              maxLength={80}
              onChange={(e) => setConfig((c) => ({ ...c, title: e.target.value }))}
            />
          </label>

          {isMetric ? (
            catalog.isPending ? (
              <Skeleton className="h-64 w-full" />
            ) : catalog.isError ? (
              <p role="alert" className="text-sm text-destructive">
                Nie udało się wczytać listy źródeł danych. Zamknij okno i spróbuj ponownie.
              </p>
            ) : config.metric ? (
              <MetricBuilderForm
                value={config.metric}
                onChange={(metric) => setConfig((c) => ({ ...c, metric }))}
                catalog={catalog.data}
                tileType={tile.type}
                chart={config.chart}
                onChartChange={(chart) => setConfig((c) => ({ ...c, chart }))}
              />
            ) : null
          ) : null}

          {tile.type === "note" ? (
            <>
              <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
                Tekst
                <Textarea
                  rows={4}
                  maxLength={2000}
                  value={config.text ?? ""}
                  onChange={(e) => setConfig((c) => ({ ...c, text: e.target.value }))}
                />
              </label>
              <div className="flex flex-col gap-2">
                <span className="text-sm font-medium text-foreground">Linki</span>
                {links.map((link, i) => (
                  <div key={i} className="grid grid-cols-[1fr_1.4fr_auto] gap-2">
                    <Input
                      aria-label={`Nazwa linku ${i + 1}`}
                      placeholder="Nazwa"
                      value={link.label}
                      maxLength={80}
                      onChange={(e) => setLink(i, { label: e.target.value })}
                    />
                    <Input
                      aria-label={`Adres linku ${i + 1}`}
                      placeholder="https://… albo /candidates"
                      value={link.url}
                      maxLength={500}
                      onChange={(e) => setLink(i, { url: e.target.value })}
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Usuń link ${i + 1}`}
                      onClick={() =>
                        setConfig((c) => ({
                          ...c,
                          links: (c.links ?? []).filter((_, j) => j !== i),
                        }))
                      }
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
                {badLink ? (
                  <p role="alert" className="text-xs text-destructive">
                    Link musi zaczynać się od https:// albo / (strona NEXUS).
                  </p>
                ) : null}
                {links.length < 10 ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="self-start"
                    onClick={() =>
                      setConfig((c) => ({ ...c, links: [...(c.links ?? []), { label: "", url: "" }] }))
                    }
                  >
                    <Plus className="h-4 w-4" />
                    Dodaj link
                  </Button>
                ) : null}
              </div>
            </>
          ) : null}
        </div>

        {isMetric && previewMetric ? (
          <div className="flex flex-col gap-3 rounded-xl bg-muted/50 p-4">
            <div className="rounded-lg border border-border bg-card px-3 py-2 text-sm leading-relaxed text-foreground">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Kafelek liczy
              </span>
              {describeMetric(previewMetric)}
            </div>
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Podgląd
            </span>
            <div className="h-56 rounded-xl border border-border bg-card p-4">
              <MetricTileBody
                metric={previewMetric}
                type={tile.type}
                chart={config.chart}
                poll={false}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              Kafelek pokazuje tylko dane, do których masz dostęp. Rozmiar zmienisz
              na pulpicie, przeciągając róg kafelka.
            </p>
          </div>
        ) : null}
      </div>
    </AppModal>
  )
}
