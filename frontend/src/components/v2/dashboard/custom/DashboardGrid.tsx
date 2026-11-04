"use client"

// Siatka pulpitu: 12 kolumn z przeciąganiem i zmianą rozmiaru na komputerze,
// jedna kolumna na telefonie (małe liczby po dwie w rzędzie). Edycja układu
// jest wyłącznie na szerokim ekranie — na telefonie przeciąganie kafelków
// myliłoby się z przewijaniem strony.

import "react-grid-layout/css/styles.css"

import { useCallback, useEffect, useMemo, useState } from "react"
import { GridLayout, useContainerWidth, verticalCompactor } from "react-grid-layout"
import { absoluteStrategy } from "react-grid-layout/core"

import type { DashboardTile } from "@/lib/api/userDashboard"
import { TILE_DEFINITIONS } from "@/lib/dashboard-tiles/catalog"
import {
  GRID_COLUMNS,
  GRID_GAP,
  MAX_FIT_ROWS,
  ROW_HEIGHT,
  applyGridPositions,
  isCompactOnMobile,
  readingOrder,
  rowsForHeight,
} from "@/lib/dashboard-tiles/layout"
import { cn } from "@/lib/utils"

import { DRAG_HANDLE_CLASS, TileFrame, type TileActions } from "./TileFrame"

export const MOBILE_BREAKPOINT = 768

/** Tryb siatki liczony z szerokości KONTENERA — jedno źródło prawdy dla „Dostosuj pulpit". */
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
  // Zmierzona wysokość kafelków z `fitContent` — tylko do wyświetlania;
  // zapisany `h` zostaje (serwer przyjmuje najwyżej 12 rzędów).
  const [fitHeights, setFitHeights] = useState<Record<string, number>>({})
  const reportFitHeight = useCallback((id: string, px: number) => {
    setFitHeights((prev) => (prev[id] === px ? prev : { ...prev, [id]: px }))
  }, [])
  const fitHandlers = useMemo(
    () =>
      Object.fromEntries(
        tiles
          .filter((t) => TILE_DEFINITIONS[t.type].fitContent)
          .map((t) => [t.id, (px: number) => reportFitHeight(t.id, px)]),
      ),
    [tiles, reportFitHeight],
  )
  const hasFit = Object.keys(fitHandlers).length > 0
  const layout = useMemo(
    () =>
      tiles.map((t) => {
        const def = TILE_DEFINITIONS[t.type]
        const fitPx = def.fitContent ? fitHeights[t.id] : undefined
        return {
          i: t.id,
          x: t.x,
          y: t.y,
          w: t.w,
          h: fitPx === undefined ? t.h : rowsForHeight(fitPx),
          minW: Math.min(def.minSize.w, GRID_COLUMNS),
          minH: def.fitContent ? 1 : def.minSize.h,
          maxH: def.fitContent ? MAX_FIT_ROWS : 12,
          // Wysokość wynika z treści — w edycji zmienia się tylko szerokość.
          ...(def.fitContent ? { resizeHandles: ["e" as const] } : {}),
        }
      }),
    [tiles, fitHeights],
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
          // `transform` na kafelku przesuwał przyklejony nagłówek tabeli
          // o pozycję kafelka (Chrome, 30.10.2026) — także w trybie edycji.
          positionStrategy={hasFit ? absoluteStrategy : undefined}
          onLayoutChange={(next) => {
            if (!editing) return
            const saved = new Map(tiles.map((t) => [t.id, t.h]))
            const positions = next.map((item) =>
              fitHandlers[item.i] ? { ...item, h: saved.get(item.i) ?? item.h } : item,
            )
            onLayoutChange(applyGridPositions(tiles, positions))
          }}
          className={cn(
            editing && "dashboard-grid-editing",
            // Uchwyt zmiany rozmiaru na dotyku (iPad poziomo): 32 px zamiast 20.
            "pointer-coarse:[&_.react-resizable-handle]:h-8! pointer-coarse:[&_.react-resizable-handle]:w-8!",
          )}
        >
          {tiles.map((tile) => (
            <div key={tile.id} data-testid={`dashboard-tile-${tile.type}`}>
              <TileFrame
                tile={tile}
                editing={editing}
                actions={actions}
                onFitHeight={fitHandlers[tile.id]}
              />
            </div>
          ))}
        </GridLayout>
      )}
    </div>
  )
}
