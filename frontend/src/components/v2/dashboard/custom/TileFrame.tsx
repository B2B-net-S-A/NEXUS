"use client"

// Ramka kafelka: nagłówek (tytuł, chip ustawień, menu) i przewijana treść.
//
// Widżety ze starego pulpitu mają WŁASNĄ kartę z nagłówkiem (`ownChrome`) —
// ramka nie dubluje ich tytułu w trybie widoku. W trybie edycji każdy kafelek
// dostaje ten sam pasek z uchwytem i akcjami, żeby dało się go przesunąć,
// ustawić, zduplikować i usunąć niezależnie od tego, co jest w środku.

import Link from "next/link"
import { Copy, GripVertical, MoreHorizontal, Settings2, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { DashboardTile } from "@/lib/api/userDashboard"
import { TILE_DEFINITIONS, tileTitle } from "@/lib/dashboard-tiles/catalog"
import { metricChip } from "@/lib/dashboard-tiles/layout"
import { safeInternalPath } from "@/lib/safe-href"
import { cn } from "@/lib/utils"

import { TileContent } from "./TileContent"

export const DRAG_HANDLE_CLASS = "dashboard-tile-drag-handle"

export interface TileActions {
  onSettings: (id: string) => void
  onDuplicate: (id: string) => void
  onRemove: (id: string) => void
  /** Trwa zapis pulpitu — akcje menu są wyłączone (FE-N07). */
  busy?: boolean
}

export function TileFrame({
  tile,
  editing,
  actions,
  children,
}: {
  tile: DashboardTile
  editing: boolean
  actions: TileActions
  /** Podgląd w oknie ustawień podmienia treść na wersję bez odpytywania. */
  children?: React.ReactNode
}) {
  const def = TILE_DEFINITIONS[tile.type]
  const title = tileTitle(tile)
  // Runda 8 (R8-N10-5): kafelek z zapisanym `/\host` nie wyprowadza poza NEXUS.
  const linkTo = safeInternalPath(tile.config.link_to)
  const chip = tile.config.metric ? metricChip(tile.config.metric) : null
  const showHeader = editing || !def.ownChrome
  const body = children ?? <TileContent tile={tile} />

  return (
    <section
      aria-label={title}
      className={cn(
        "group relative flex h-full min-h-0 flex-col overflow-hidden rounded-xl",
        !def.ownChrome && "border border-border bg-card p-4",
        def.ownChrome && !editing && "bg-transparent",
        editing && "border border-dashed border-primary/50 bg-card p-3",
      )}
    >
      {showHeader ? (
        <header className="mb-2 flex min-h-7 shrink-0 items-start gap-2">
          {editing ? (
            <span
              className={cn(
                DRAG_HANDLE_CLASS,
                // `hit-area` powiększa pole chwytu do ~32 px (tablet w trybie edycji).
                "hit-area flex cursor-grab touch-none items-center text-muted-foreground active:cursor-grabbing",
              )}
              title="Przeciągnij, aby przesunąć"
              aria-hidden
            >
              <GripVertical className="h-4 w-4" aria-hidden />
            </span>
          ) : null}
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold text-foreground">
              {linkTo && !editing ? (
                <Link href={linkTo} className="hover:underline">
                  {title}
                </Link>
              ) : (
                title
              )}
            </h3>
            {chip ? <p className="truncate text-xs text-muted-foreground">{chip}</p> : null}
          </div>
          {editing ? (
            <div className="flex shrink-0 items-center">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Ustawienia kafelka ${title}`}
                onClick={() => actions.onSettings(tile.id)}
              >
                <Settings2 className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Duplikuj kafelek ${title}`}
                onClick={() => actions.onDuplicate(tile.id)}
              >
                <Copy className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Usuń kafelek ${title}`}
                className="text-destructive"
                onClick={() => actions.onRemove(tile.id)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-sm" aria-label={`Menu kafelka ${title}`}>
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem disabled={actions.busy} onSelect={() => actions.onSettings(tile.id)}>
                  Ustawienia kafelka
                </DropdownMenuItem>
                <DropdownMenuItem disabled={actions.busy} onSelect={() => actions.onDuplicate(tile.id)}>
                  Duplikuj
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="text-destructive"
                  disabled={actions.busy}
                  onSelect={() => actions.onRemove(tile.id)}
                >
                  Usuń z pulpitu
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </header>
      ) : null}
      <div
        className={cn(
          // `@container`: widżety w kafelku reagują na szerokość KAFELKA,
          // nie okna (audyt 23.09.2026, P1-02).
          "@container min-h-0 flex-1",
          tile.type === "metric_number" ? "overflow-hidden" : "overflow-auto",
          editing && "pointer-events-none select-none opacity-80",
        )}
      >
        {body}
      </div>
      {!showHeader ? (
        // Na dotyku menu jest zawsze widoczne — `group-hover` tam nie działa,
        // a to jedyne miejsce na ustawienia/usunięcie kafelka na telefonie.
        <div className="absolute right-2 top-2 z-10 transition-opacity focus-within:opacity-100 pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="icon-sm"
                className="bg-card"
                aria-label={`Menu kafelka ${title}`}
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem disabled={actions.busy} onSelect={() => actions.onSettings(tile.id)}>
                Ustawienia kafelka
              </DropdownMenuItem>
              <DropdownMenuItem disabled={actions.busy} onSelect={() => actions.onDuplicate(tile.id)}>
                Duplikuj
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-destructive"
                disabled={actions.busy}
                onSelect={() => actions.onRemove(tile.id)}
              >
                Usuń z pulpitu
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      ) : null}
    </section>
  )
}
