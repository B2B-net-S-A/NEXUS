"use client"

// Pierwsze wejście: pusty pulpit (decyzja Artura) z podpowiedzią kafelków
// polecanych dla roli — jednym kliknięciem pojedynczo albo wszystkie naraz.

import { LayoutGrid, Plus, Wand2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import type { TileTemplate } from "@/lib/dashboard-tiles/catalog"

export function EmptyDashboard({
  roleLabel,
  recommended,
  onAdd,
  onAddAll,
  onOpenCatalog,
  onCustomMetric,
  disabled,
}: {
  roleLabel: string | null
  recommended: TileTemplate[]
  onAdd: (template: TileTemplate) => void
  onAddAll: () => void
  onOpenCatalog: () => void
  onCustomMetric: () => void
  disabled?: boolean
}) {
  return (
    <section
      aria-labelledby="empty-dashboard-title"
      className="mx-auto flex w-full max-w-3xl flex-col gap-5 rounded-2xl border border-border bg-card p-6 shadow-sm sm:p-8"
    >
      <div className="flex items-start gap-4">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <LayoutGrid className="h-6 w-6" aria-hidden />
        </span>
        <div>
          <h2 id="empty-dashboard-title" className="text-lg font-semibold text-foreground">
            Twój pulpit jest pusty
          </h2>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
            Dodaj kafelki z danymi, które chcesz widzieć na starcie dnia. Każdy kafelek
            ustawiasz osobno — zakres, klienta, okres i wygląd. Układ zapisuje się na
            Twoim koncie.
          </p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button onClick={onOpenCatalog} disabled={disabled}>
          <Plus className="h-4 w-4" />
          Dodaj kafelek
        </Button>
        <Button variant="outline" onClick={onCustomMetric} disabled={disabled}>
          <Wand2 className="h-4 w-4" />
          Zbuduj własną metrykę
        </Button>
      </div>
      {recommended.length > 0 ? (
        <div className="border-t border-border pt-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-semibold text-foreground">
              {roleLabel ? `Polecane dla roli ${roleLabel}` : "Polecane na start"}
            </span>
            <Button variant="tertiary" size="sm" onClick={onAddAll} disabled={disabled}>
              Dodaj wszystkie {recommended.length}
            </Button>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2">
            {recommended.map((t) => (
              <li
                key={t.key}
                className="flex items-center justify-between gap-3 rounded-xl border border-border p-3"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-foreground">{t.label}</div>
                  <p className="line-clamp-2 text-xs text-muted-foreground">{t.description}</p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  aria-label={`Dodaj ${t.label}`}
                  onClick={() => onAdd(t)}
                  disabled={disabled}
                >
                  <Plus className="h-4 w-4" />
                  Dodaj
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  )
}
