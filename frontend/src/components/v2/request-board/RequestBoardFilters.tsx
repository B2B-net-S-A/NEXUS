"use client"

import { Button } from "@/components/ui/button"
import type { RequestBoard } from "@/lib/api/requestAllocation"
import {
  DUE_OPTIONS,
  SENT_OPTIONS,
  clientOptions,
  hasActiveFilters,
  peopleOptions,
  type BoardFilters,
} from "@/lib/request-board"

const fieldClass =
  "h-10 rounded-md border border-input bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"

interface Props {
  board: RequestBoard
  filters: BoardFilters
  onChange: (next: BoardFilters) => void
  shown: number
  total: number
}

/** Pasek filtrów pulpitu — stanowisko, klient, termin, wysłani, kto, kategoria. */
export function RequestBoardFilters({ board, filters, onChange, shown, total }: Props) {
  const set = <K extends keyof BoardFilters>(key: K, value: BoardFilters[K]) =>
    onChange({ ...filters, [key]: value })

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-card p-3">
      <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
        Stanowisko
        <input
          className={`${fieldClass} w-44`}
          placeholder="np. Java"
          value={filters.q}
          onChange={(e) => set("q", e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
        Klient
        <select
          className={fieldClass}
          value={filters.client}
          onChange={(e) => set("client", e.target.value)}
        >
          <option value="">Wszyscy klienci</option>
          {clientOptions(board).map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
        Termin
        <select
          className={fieldClass}
          value={filters.due}
          onChange={(e) => set("due", e.target.value as BoardFilters["due"])}
        >
          {DUE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
        Wysłani
        <select
          className={fieldClass}
          value={filters.sent}
          onChange={(e) => set("sent", e.target.value as BoardFilters["sent"])}
        >
          {SENT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
        Kto pracuje
        <select
          className={fieldClass}
          value={filters.who}
          onChange={(e) => set("who", e.target.value)}
        >
          <option value="">Wszyscy</option>
          {peopleOptions(board).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
        Kategoria
        <select
          className={fieldClass}
          value={filters.cat}
          onChange={(e) => set("cat", e.target.value)}
        >
          <option value="">Wszystkie kategorie</option>
          {board.groups.map((g) => (
            <option key={g.category_id ?? "none"} value={g.category_id ?? "none"}>
              {g.name}
            </option>
          ))}
        </select>
      </label>
      <div className="ml-auto flex items-center gap-3">
        <span className="text-sm text-muted-foreground">
          Pokazuję {shown} z {total}
        </span>
        {hasActiveFilters(filters) && (
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              onChange({ q: "", client: "", due: "", sent: "", who: "", cat: "" })
            }
          >
            Wyczyść filtry
          </Button>
        )}
      </div>
    </div>
  )
}
