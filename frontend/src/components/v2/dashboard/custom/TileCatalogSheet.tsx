"use client"

// Katalog kafelków (panel z prawej): kategorie, wyszukiwarka, „Własna metryka".
// Kafelki, do których konto nie ma dostępu, są widoczne i wyszarzone z powodem
// — znikający kafelek czytałby się jak brak funkcji, a nie brak uprawnień.

import { useMemo, useState } from "react"
import { Lock, Plus, Search, Wand2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import {
  TILE_CATEGORY_LABELS,
  TILE_TEMPLATES,
  templateAvailability,
  type TileCategory,
  type TileTemplate,
} from "@/lib/dashboard-tiles/catalog"
import { cn } from "@/lib/utils"
import type { User } from "@/store/auth"

type CategoryFilter = TileCategory | "all"

function normalize(text: string): string {
  return text.toLocaleLowerCase("pl").normalize("NFD").replace(/\p{Diacritic}/gu, "")
}

export function TileCatalogSheet({
  open,
  onOpenChange,
  user,
  onPick,
  onCustomMetric,
  highlightKey,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  user: User | null | undefined
  onPick: (template: TileTemplate) => void
  onCustomMetric: () => void
  highlightKey?: string | null
}) {
  const [query, setQuery] = useState("")
  const [category, setCategory] = useState<CategoryFilter>("all")

  const counts = useMemo(() => {
    const out: Record<string, number> = { all: TILE_TEMPLATES.length }
    for (const t of TILE_TEMPLATES) out[t.category] = (out[t.category] ?? 0) + 1
    return out
  }, [])

  const visible = TILE_TEMPLATES.filter((t) => {
    if (category !== "all" && t.category !== category) return false
    if (!query.trim()) return true
    const q = normalize(query.trim())
    return normalize(`${t.label} ${t.description}`).includes(q)
  })

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" size="xl" className="flex flex-col gap-0 p-0">
        <SheetHeader className="border-b border-border p-5">
          <SheetTitle>Dodaj kafelek</SheetTitle>
          <SheetDescription>
            Wybierz gotowy kafelek i ustaw, co ma pokazywać — albo zbuduj własną metrykę.
          </SheetDescription>
          <label className="relative mt-2 block">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Szukaj: zamówienia, lejek, CV…"
              aria-label="Szukaj kafelka"
              className="pl-9"
            />
          </label>
        </SheetHeader>
        <div className="flex min-h-0 flex-1">
          <nav
            aria-label="Kategorie kafelków"
            className="hidden w-52 shrink-0 flex-col gap-0.5 border-r border-border p-3 sm:flex"
          >
            {(["all", ...Object.keys(TILE_CATEGORY_LABELS)] as CategoryFilter[]).map((c) => (
              <button
                key={c}
                type="button"
                aria-pressed={category === c}
                onClick={() => setCategory(c)}
                className={cn(
                  "flex items-center justify-between rounded-md px-2.5 py-2 text-left text-sm",
                  category === c
                    ? "bg-primary/10 font-semibold text-primary"
                    : "text-foreground hover:bg-muted",
                )}
              >
                <span>{c === "all" ? "Wszystkie" : TILE_CATEGORY_LABELS[c]}</span>
                <span className="font-mono text-xs text-muted-foreground">{counts[c] ?? 0}</span>
              </button>
            ))}
          </nav>
          <div className="grid min-h-0 flex-1 auto-rows-min grid-cols-1 gap-3 overflow-y-auto p-4 md:grid-cols-2">
            <div className="flex flex-col gap-2 rounded-xl border border-primary bg-primary/5 p-3 md:col-span-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-primary">
                <Wand2 className="h-4 w-4" aria-hidden />
                Własna metryka
              </div>
              <p className="text-xs text-muted-foreground">
                Zbuduj kafelek od zera: wybierz dane, co liczyć, filtry, okres i wykres.
              </p>
              <Button size="sm" className="self-start" onClick={onCustomMetric}>
                <Plus className="h-4 w-4" />
                Zbuduj metrykę
              </Button>
            </div>
            {visible.length === 0 ? (
              <p className="text-sm text-muted-foreground md:col-span-2">
                Żaden kafelek nie pasuje do wyszukiwania.
              </p>
            ) : null}
            {visible.map((t) => {
              const availability = templateAvailability(t, user)
              return (
                <div
                  key={t.key}
                  className={cn(
                    "flex flex-col gap-2 rounded-xl border border-border bg-card p-3",
                    highlightKey === t.key && "ring-2 ring-primary",
                    !availability.ok && "opacity-60",
                  )}
                >
                  <div>
                    <div className="text-sm font-semibold text-foreground">{t.label}</div>
                    <p className="mt-0.5 text-xs leading-snug text-muted-foreground">
                      {t.description}
                    </p>
                  </div>
                  <div className="mt-auto flex items-center justify-between gap-2">
                    <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
                      {TILE_CATEGORY_LABELS[t.category]}
                    </span>
                    {availability.ok ? (
                      <Button
                        variant="outline"
                        size="sm"
                        aria-label={`Dodaj kafelek ${t.label}`}
                        onClick={() => onPick(t)}
                      >
                        <Plus className="h-4 w-4" />
                        Dodaj
                      </Button>
                    ) : (
                      <span className="flex items-center gap-1 text-xs text-muted-foreground">
                        <Lock className="h-3.5 w-3.5" aria-hidden />
                        {availability.reason}
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}
