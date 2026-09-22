"use client"

// Własny pulpit startowy (decyzja Artura 21.09.2026): każdy ustawia go sam.
//
// Dwa tryby zapisu, świadomie różne:
// - WIDOK: pojedyncze akcje z menu kafelka (usuń, duplikuj, ustawienia)
//   i dodanie z katalogu zapisują się od razu — to jedno kliknięcie, które
//   ktoś zrobił celowo;
// - EDYCJA: przeciąganie i zmiana rozmiaru pracują na SZKICU z cofaniem,
//   a zapis idzie jednym PUT dopiero po „Zapisz układ". „Anuluj" wyrzuca szkic.
//
// Zapis niesie `expected_version`: dwie karty z otwartą edycją nie nadpisują
// sobie układu po cichu — 409 przeładowuje pulpit i mówi to wprost.

import { useCallback, useEffect, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Check, LayoutGrid, Plus, Undo2 } from "lucide-react"

import { useToast } from "@/components/Toast"
import { ContactOversightPanel } from "@/components/candidate-contact/ContactOversightPanel"
import { PageHeader } from "@/components/ds/PageHeader"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { apiErrorMessage } from "@/lib/api-error"
import {
  USER_DASHBOARD_QUERY_KEY,
  isDashboardVersionConflict,
  useSaveUserDashboard,
  useUserDashboard,
  type DashboardTile,
  type TileConfig,
} from "@/lib/api/userDashboard"
import {
  TILE_DEFINITIONS,
  TILE_TEMPLATES,
  recommendedTemplates,
  type TileTemplate,
} from "@/lib/dashboard-tiles/catalog"
import {
  MAX_TILES,
  appendTemplates,
  duplicateTile,
  removeTile,
} from "@/lib/dashboard-tiles/layout"
import { useAuthStore } from "@/store/auth"

import { DashboardGrid } from "./DashboardGrid"
import { EmptyDashboard } from "./EmptyDashboard"
import { TileCatalogSheet } from "./TileCatalogSheet"
import { TileSettingsDialog } from "./TileSettingsDialog"

const CONTACT_OVERSIGHT_HASH = "#nadzor-kontaktu"
const UNDO_LIMIT = 30

type Dialog =
  | { mode: "add"; tile: DashboardTile }
  | { mode: "edit"; tile: DashboardTile }
  | null

const CUSTOM_METRIC_TEMPLATE: TileTemplate = {
  key: "custom_metric",
  type: "metric_chart",
  label: "Własna metryka",
  description: "",
  category: "universal",
  config: {
    chart: "bars",
    metric: {
      source: "pipeline_moves",
      measure: "first_reach",
      stage: "cv_sent",
      filters: { author: "me" },
      group_by: "week",
      period: "last_8_weeks",
      compare_previous: true,
    },
  },
}

export function CustomDashboard() {
  const user = useAuthStore((s) => s.user)
  const queryClient = useQueryClient()
  const { showError, showSuccess } = useToast()
  const query = useUserDashboard()
  const save = useSaveUserDashboard()

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<DashboardTile[]>([])
  const [history, setHistory] = useState<DashboardTile[][]>([])
  const [catalogOpen, setCatalogOpen] = useState(false)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [oversightFromAlert, setOversightFromAlert] = useState(false)

  const saved = query.data?.tiles ?? []
  const version = query.data?.version ?? 0
  const tiles = editing ? draft : saved

  // Alerty SLA kontaktów linkują do `/dashboard#nadzor-kontaktu`. Kafelek
  // na pulpicie ma tę kotwicę sam; bez niego pokazujemy panel tymczasowo,
  // żeby kliknięcie alertu nigdy nie kończyło się pustym ekranem.
  useEffect(() => {
    if (typeof window === "undefined") return
    if (window.location.hash === CONTACT_OVERSIGHT_HASH) setOversightFromAlert(true)
  }, [])
  const oversightAvailable = TILE_DEFINITIONS.contact_oversight.availability(user).ok
  const oversightOnDashboard = saved.some((t) => t.type === "contact_oversight")
  useEffect(() => {
    if (!oversightFromAlert || !query.isSuccess) return
    const el = document.getElementById("nadzor-kontaktu")
    el?.scrollIntoView({ behavior: "smooth", block: "start" })
  }, [oversightFromAlert, query.isSuccess])

  const persist = useCallback(
    (next: DashboardTile[], message?: string) => {
      save.mutate(
        { tiles: next, version },
        {
          onSuccess: () => {
            if (message) showSuccess(message)
          },
          onError: (error) => {
            if (isDashboardVersionConflict(error)) {
              showError("Pulpit został zmieniony w innej karcie — wczytuję aktualny układ.")
              setEditing(false)
              void queryClient.invalidateQueries({ queryKey: USER_DASHBOARD_QUERY_KEY })
              return
            }
            showError(apiErrorMessage(error, "Nie udało się zapisać pulpitu."))
          },
        },
      )
    },
    [save, version, showError, showSuccess, queryClient],
  )

  /** Zmiana układu: w edycji na szkic (z cofaniem), w widoku od razu zapis. */
  const commit = useCallback(
    (next: DashboardTile[], message?: string) => {
      if (editing) {
        setHistory((h) => [...h.slice(-UNDO_LIMIT + 1), draft])
        setDraft(next)
      } else {
        persist(next, message)
      }
    },
    [editing, draft, persist],
  )

  const startEditing = () => {
    setDraft(saved)
    setHistory([])
    setEditing(true)
  }
  const cancelEditing = () => {
    setEditing(false)
    setDraft([])
    setHistory([])
  }
  const saveEditing = () => {
    save.mutate(
      { tiles: draft, version },
      {
        onSuccess: () => {
          setEditing(false)
          showSuccess("Układ pulpitu zapisany.")
        },
        onError: (error) => {
          if (isDashboardVersionConflict(error)) {
            showError("Pulpit został zmieniony w innej karcie — wczytuję aktualny układ.")
            cancelEditing()
            void queryClient.invalidateQueries({ queryKey: USER_DASHBOARD_QUERY_KEY })
            return
          }
          showError(apiErrorMessage(error, "Nie udało się zapisać układu."))
        },
      },
    )
  }
  const undo = () => {
    if (history.length === 0) return
    setDraft(history[history.length - 1])
    setHistory(history.slice(0, -1))
  }

  const addTemplates = (templates: TileTemplate[]) => {
    if (tiles.length + templates.length > MAX_TILES) {
      showError(`Pulpit mieści najwyżej ${MAX_TILES} kafelków.`)
      return
    }
    commit(appendTemplates(tiles, templates), "Dodano do pulpitu.")
  }

  /** Metryki i notatka przechodzą przez okno ustawień, reszta trafia od razu. */
  const pickTemplate = (template: TileTemplate) => {
    setCatalogOpen(false)
    const needsSettings =
      template.type.startsWith("metric_") || template.type === "note"
    if (!needsSettings) {
      addTemplates([template])
      return
    }
    const [tile] = appendTemplates([], [template])
    setDialog({ mode: "add", tile })
  }

  const actions = {
    onSettings: (id: string) => {
      const tile = tiles.find((t) => t.id === id)
      if (tile) setDialog({ mode: "edit", tile })
    },
    onDuplicate: (id: string) => commit(duplicateTile(tiles, id), "Kafelek zduplikowany."),
    onRemove: (id: string) => commit(removeTile(tiles, id), "Kafelek usunięty z pulpitu."),
  }

  const submitDialog = (config: TileConfig) => {
    if (!dialog) return
    if (dialog.mode === "add") {
      const template: TileTemplate = {
        key: "dialog",
        type: dialog.tile.type,
        label: "",
        description: "",
        category: "universal",
        config,
        size: { w: dialog.tile.w, h: dialog.tile.h },
      }
      addTemplates([template])
    } else {
      commit(
        tiles.map((t) => (t.id === dialog.tile.id ? { ...t, config } : t)),
        "Ustawienia kafelka zapisane.",
      )
    }
    setDialog(null)
  }

  const recommended = recommendedTemplates(user)
  const dropped = query.data?.dropped_tiles ?? []

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-6">
      <PageHeader
        title="Mój pulpit"
        description={
          editing
            ? "Edytujesz układ — zmiany widzisz tylko Ty"
            : "Twój układ — widzisz go tylko Ty"
        }
        actions={
          editing ? null : (
            <div className="flex gap-2">
              {saved.length > 0 ? (
                <Button variant="outline" onClick={startEditing} className="hidden md:inline-flex">
                  <LayoutGrid className="h-4 w-4" />
                  Edytuj układ
                </Button>
              ) : null}
              <Button onClick={() => setCatalogOpen(true)}>
                <Plus className="h-4 w-4" />
                Dodaj kafelek
              </Button>
            </div>
          )
        }
      />

      {editing ? (
        <div
          role="region"
          aria-label="Tryb edycji pulpitu"
          className="sticky top-2 z-20 flex flex-wrap items-center gap-3 rounded-xl bg-foreground px-4 py-2.5 text-background shadow-lg"
        >
          <LayoutGrid className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
          <p className="min-w-0 flex-1 text-sm">
            <strong className="font-semibold">Tryb edycji.</strong>{" "}
            <span className="opacity-80">
              Złap za uchwyt, żeby przesunąć kafelek; złap za prawy dolny róg, żeby zmienić rozmiar.
            </span>
          </p>
          <Button
            variant="ghost"
            size="sm"
            onClick={undo}
            disabled={history.length === 0}
            className="text-background hover:bg-background/10"
          >
            <Undo2 className="h-4 w-4" />
            Cofnij
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setCatalogOpen(true)}>
            <Plus className="h-4 w-4" />
            Dodaj kafelek
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={cancelEditing}
            className="text-background hover:bg-background/10"
          >
            Anuluj
          </Button>
          <Button size="sm" onClick={saveEditing} disabled={save.isPending}>
            <Check className="h-4 w-4" />
            Zapisz układ
          </Button>
        </div>
      ) : null}

      {dropped.length > 0 ? (
        <p role="status" className="rounded-lg border border-border bg-muted/50 px-3 py-2 text-sm text-muted-foreground">
          {dropped.length === 1
            ? "Jeden kafelek nie jest już dostępny w katalogu i został pominięty."
            : `${dropped.length} kafelki nie są już dostępne w katalogu i zostały pominięte.`}{" "}
          Pominięte kafelki znikną z układu przy najbliższym zapisie.
        </p>
      ) : null}

      {oversightFromAlert && oversightAvailable && !oversightOnDashboard && query.isSuccess ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
            <span>Alert prowadzi do Nadzoru kontaktów — nie masz go na pulpicie.</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                const template = TILE_TEMPLATES.find((t) => t.key === "contact_oversight")
                if (template) addTemplates([template])
                setOversightFromAlert(false)
              }}
            >
              Dodaj na stałe
            </Button>
          </div>
          <ContactOversightPanel />
        </div>
      ) : null}

      {query.isPending ? (
        <div className="grid grid-cols-12 gap-4">
          <Skeleton className="col-span-12 h-24 md:col-span-3" />
          <Skeleton className="col-span-12 h-24 md:col-span-3" />
          <Skeleton className="col-span-12 h-24 md:col-span-6" />
          <Skeleton className="col-span-12 h-64" />
        </div>
      ) : query.isError ? (
        <WidgetErrorBlock
          title="Nie udało się wczytać pulpitu."
          error={query.error}
          onRetry={() => query.refetch()}
        />
      ) : tiles.length === 0 && !editing ? (
        <EmptyDashboard
          roleLabel={recommended.roleLabel}
          recommended={recommended.templates}
          onAdd={(t) => addTemplates([t])}
          onAddAll={() => addTemplates(recommended.templates)}
          onOpenCatalog={() => setCatalogOpen(true)}
          onCustomMetric={() => pickTemplate(CUSTOM_METRIC_TEMPLATE)}
          disabled={save.isPending}
        />
      ) : (
        <DashboardGrid
          tiles={tiles}
          editing={editing}
          actions={actions}
          onLayoutChange={(next) => {
            if (next === draft) return
            setHistory((h) => [...h.slice(-UNDO_LIMIT + 1), draft])
            setDraft(next)
          }}
        />
      )}

      <TileCatalogSheet
        open={catalogOpen}
        onOpenChange={setCatalogOpen}
        user={user}
        onPick={pickTemplate}
        onCustomMetric={() => pickTemplate(CUSTOM_METRIC_TEMPLATE)}
      />
      <TileSettingsDialog
        tile={dialog?.tile ?? null}
        mode={dialog?.mode ?? "add"}
        onCancel={() => setDialog(null)}
        onSubmit={submitDialog}
      />
    </div>
  )
}

