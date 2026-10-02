"use client"

import { Button } from "@/components/ui/button"
import type { RequestBoard } from "@/lib/api/requestAllocation"
import {
  DUE_OPTIONS,
  EMPTY_FILTERS,
  SENT_OPTIONS,
  clientOptions,
  hasActiveFilters,
  leadOptions,
  peopleOptions,
  type BoardFilters,
} from "@/lib/request-board"
import { PRIORITY_LEVEL_OPTIONS } from "@/lib/request-priority"
import { cn } from "@/lib/utils"

// Wąski kontener (kafelek na telefonie): pola w dwóch kolumnach na całą
// szerokość — dziewięć pól jedno pod drugim zajmowało ponad pół ekranu.
// Od 520 px pulpitu (`rboard`) pola stoją w rzędzie i zawijają się.
const fieldBase =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
/** Lista wyboru: w rzędzie tak szeroka jak najdłuższa pozycja, najwyżej 220 px. */
const fieldClass = `${fieldBase} @min-[520px]/rboard:w-auto @min-[520px]/rboard:max-w-[220px]`
/** Pole tekstowe: w rzędzie stała szerokość. */
const inputClass = `${fieldBase} @min-[520px]/rboard:w-44`

interface Props {
  board: RequestBoard
  filters: BoardFilters
  onChange: (next: BoardFilters) => void
  shown: number
  total: number
  /** Ile wierszy zostanie po włączeniu „Bez rekrutera” przy obecnych filtrach. */
  unstaffed: number
}

/**
 * Pasek filtrów pulpitu — te same wymiary co lista rekrutacji: stanowisko,
 * klient, Delivery Lead, Rekruter, kategoria, priorytet, termin, wysłani
 * i przełącznik „Bez rekrutera”.
 */
export function RequestBoardFilters({
  board,
  filters,
  onChange,
  shown,
  total,
  unstaffed,
}: Props) {
  const set = <K extends keyof BoardFilters>(key: K, value: BoardFilters[K]) =>
    onChange({ ...filters, [key]: value })
  const leads = leadOptions(board)
  const onlyUnstaffed = filters.nobody === "1"

  return (
    <div className="grid grid-cols-2 items-end gap-3 rounded-lg border border-border bg-card p-3 @min-[520px]/rboard:flex @min-[520px]/rboard:flex-wrap">
      <label className="flex min-w-0 flex-col gap-1 text-xs font-medium text-muted-foreground">
        Stanowisko
        <input
          className={inputClass}
          placeholder="np. Java"
          value={filters.q}
          onChange={(e) => set("q", e.target.value)}
        />
      </label>
      <label className="flex min-w-0 flex-col gap-1 text-xs font-medium text-muted-foreground">
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
      <label className="flex min-w-0 flex-col gap-1 text-xs font-medium text-muted-foreground">
        Delivery Lead
        <select
          className={fieldClass}
          value={filters.lead}
          onChange={(e) => set("lead", e.target.value)}
        >
          <option value="">Wszyscy</option>
          {leads.options.map((lead) => (
            <option key={lead.id} value={lead.id}>
              {lead.name}
            </option>
          ))}
          {leads.hasNone && <option value="none">Bez Delivery Leada</option>}
        </select>
      </label>
      <label className="flex min-w-0 flex-col gap-1 text-xs font-medium text-muted-foreground">
        Rekruter
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
      <label className="flex min-w-0 flex-col gap-1 text-xs font-medium text-muted-foreground">
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
      <label className="flex min-w-0 flex-col gap-1 text-xs font-medium text-muted-foreground">
        Priorytet
        <select
          className={fieldClass}
          value={filters.prio}
          onChange={(e) => set("prio", e.target.value as BoardFilters["prio"])}
        >
          <option value="">Każdy priorytet</option>
          {PRIORITY_LEVEL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex min-w-0 flex-col gap-1 text-xs font-medium text-muted-foreground">
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
      <label className="flex min-w-0 flex-col gap-1 text-xs font-medium text-muted-foreground">
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
      {/* Przełącznik, nie pole wyboru: to sygnał „komu trzeba kogoś dać”, jak
          „Bez rekrutera” na liście rekrutacji. Liczba = tyle wierszy zostanie
          po kliknięciu przy obecnych filtrach. */}
      <button
        type="button"
        aria-pressed={onlyUnstaffed}
        onClick={() => set("nobody", onlyUnstaffed ? "" : "1")}
        title="Szukamy kandydatów, a nikt nad requestem nie pracuje. Propozycja automatu to jeszcze nie przydział."
        className={cn(
          "inline-flex h-10 items-center justify-between gap-2 rounded-md border px-3 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-ring",
          onlyUnstaffed
            ? "border-warning/40 bg-warning-muted text-warning-muted-foreground"
            : "border-input bg-background text-foreground hover:bg-accent",
        )}
      >
        Bez rekrutera
        <span className="font-mono tabular-nums">{unstaffed}</span>
      </button>
      <div className="col-span-2 flex items-center justify-between gap-3 @min-[520px]/rboard:ml-auto @min-[520px]/rboard:justify-end">
        <span className="text-sm text-muted-foreground">
          Pokazuję {shown} z {total}
        </span>
        {hasActiveFilters(filters) && (
          <Button variant="outline" size="sm" onClick={() => onChange(EMPTY_FILTERS)}>
            Wyczyść filtry
          </Button>
        )}
      </div>
    </div>
  )
}
