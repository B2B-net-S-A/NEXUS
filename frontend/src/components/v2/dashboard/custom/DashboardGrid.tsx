"use client"

// Siatka pulpitu: 12 kolumn z przeciąganiem i zmianą rozmiaru na komputerze,
// jedna kolumna na telefonie (małe liczby po dwie w rzędzie). Edycja układu
// jest wyłącznie na szerokim ekranie — na telefonie przeciąganie kafelków
// myliłoby się z przewijaniem strony.

import "react-grid-layout/css/styles.css"

import { useEffect, useMemo } from "react"
import { GridLayout, useContainerWidth, verticalCompactor } from "react-grid-layout"

import type { DashboardTile } from "@/lib/api/userDashboard"
import { TILE_DEFINITIONS } from "@/lib/dashboard-tiles/catalog"
import {
  GRID_COLUMNS,
  GRID_GAP,
  ROW_HEIGHT,
  applyGridPositions,
  isCompactOnMobile,
  readingOrder,
} from "@/lib/dashboard-tiles/layout"
import { cn } from "@/lib/utils"

import { DRAG_HANDLE_CLASS, TileFrame, type TileActions } from "./TileFrame"

export const MOBILE_BREAKPOINT = 768

/** Tryb siatki liczony z szerokości KONTENERA — jedno źródło prawdy dla „Edytuj układ". */
export type DashboardGridMode = "grid" | "list"

const FIXED_HEIGHT_ON_MOBILE = new Set(["metric_chart", "metric_funnel"])

function MobileList({
  tiles,
  actions,
}: {
  tiles: DashboardTile[]
  actions: TileActions
}) {
  return (
    <div className="grid grid-cols-2 gap-3" data-testid="dashboard-mobile-list">
      {readingOrder(tiles).map((tile) => {
        const compact = isCompactOnMobile(tile)
        // Wykres i lejek potrzebują stałej wysokości (recharts mierzy rodzica);
        // reszta rośnie z treścią — stała wysokość dawała zbędne paski
        // przewijania w wąskiej kolumnie.
        const fixed = FIXED_HEIGHT_ON_MOBILE.has(tile.type)
        return (
          <div
            key={tile.id}
            className={cn(compact ? "col-span-1" : "col-span-2")}
            style={fixed ? { height: Math.max(tile.h, 3) * ROW_HEIGHT } : undefined}
          >
            <TileFrame tile={tile} editing={false} actions={actions} />
          </div>
        )
      })}
    </div>
  )
}

export function DashboardGrid({
  tiles,
  editing,
  actions,
  onLayoutChange,
  onModeChange,
}: {
  tiles: DashboardTile[]
  editing: boolean
  actions: TileActions
  onLayoutChange: (tiles: DashboardTile[]) => void
  /**
   * Siatka przechodzi w listę przy KONTENERZE < 768 px (okno do ~924 px przy
   * zwiniętym pasku, ~1104 px przy przypiętym). Rodzic chowa wtedy „Edytuj
   * układ" — w liście edycja nic by nie robiła (audyt 23.09.2026, P1-01).
   */
  onModeChange?: (mode: DashboardGridMode) => void
}) {
  const { width, containerRef, mounted } = useContainerWidth({ measureBeforeMount: true })
  const layout = useMemo(
    () =>
      tiles.map((t) => {
        const def = TILE_DEFINITIONS[t.type]
        return {
          i: t.id,
          x: t.x,
          y: t.y,
          w: t.w,
          h: t.h,
          minW: Math.min(def.minSize.w, GRID_COLUMNS),
          minH: def.minSize.h,
          maxH: 12,
        }
      }),
    [tiles],
  )
  const mobile = mounted && width < MOBILE_BREAKPOINT
  useEffect(() => {
    if (mounted) onModeChange?.(mobile ? "list" : "grid")
  }, [mounted, mobile, onModeChange])

  return (
    <div ref={containerRef} className="w-full">
      {!mounted ? null : mobile ? (
        <MobileList tiles={tiles} actions={actions} />
      ) : (
        <GridLayout
          width={width}
          layout={layout}
          gridConfig={{
            cols: GRID_COLUMNS,
            rowHeight: ROW_HEIGHT,
            margin: [GRID_GAP, GRID_GAP],
            containerPadding: [0, 0],
          }}
          dragConfig={{ enabled: editing, handle: `.${DRAG_HANDLE_CLASS}` }}
          resizeConfig={{ enabled: editing, handles: ["se"] }}
          compactor={verticalCompactor}
          onLayoutChange={(next) => {
            if (!editing) return
            onLayoutChange(applyGridPositions(tiles, [...next]))
          }}
          className={cn(
            editing && "dashboard-grid-editing",
            // Uchwyt zmiany rozmiaru na dotyku (iPad poziomo): 32 px zamiast 20.
            "pointer-coarse:[&_.react-resizable-handle]:h-8! pointer-coarse:[&_.react-resizable-handle]:w-8!",
          )}
        >
          {tiles.map((tile) => (
            <div key={tile.id} data-testid={`dashboard-tile-${tile.type}`}>
              <TileFrame tile={tile} editing={editing} actions={actions} />
            </div>
          ))}
        </GridLayout>
      )}
    </div>
  )
}
