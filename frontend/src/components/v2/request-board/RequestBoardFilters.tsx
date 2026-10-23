"use client"

import { useId, type ReactNode } from "react"
import { X } from "lucide-react"

import { Button } from "@/components/ui/button"
import type { RequestBoard } from "@/lib/api/requestAllocation"
import { pluralPl } from "@/lib/plural-pl"
import {
  DUE_OPTIONS,
  EMPTY_FILTERS,
  SENT_OPTIONS,
  activeFilterCount,
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
// Pole z wartością inną niż domyślna — ten sam język co pigułki filtrów na
// liście kandydatów i rekrutacji. Bez tego „P1 Pilne” i „Każdy priorytet”
// wyglądały tak samo i nie było widać, który filtr zawęża listę.
const activeClass = "border-primary/30 bg-primary/10 font-medium text-primary"

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
  const activeCount = activeFilterCount(filters)
  const field = (key: keyof BoardFilters, base: string) => ({
    active: Boolean(filters[key]),
    className: cn(base, filters[key] && activeClass),
    onClear: () => set(key, ""),
  })
  const q = field("q", inputClass)
  const client = field("client", fieldClass)
  const lead = field("lead", fieldClass)
  const who = field("who", fieldClass)
  const cat = field("cat", fieldClass)
  const prio = field("prio", fieldClass)
  const due = field("due", fieldClass)
  const sent = field("sent", fieldClass)

  return (
    <div className="grid grid-cols-2 items-end gap-3 rounded-lg border border-border bg-card p-3 @min-[520px]/rboard:flex @min-[520px]/rboard:flex-wrap">
      <FilterField label="Stanowisko" active={q.active} onClear={q.onClear}>
        {(id) => (
          <input
            id={id}
            data-active={q.active}
            className={q.className}
            placeholder="np. Java albo numer"
            value={filters.q}
            onChange={(e) => set("q", e.target.value)}
          />
        )}
      </FilterField>
      <FilterField label="Klient" active={client.active} onClear={client.onClear}>
        {(id) => (
          <select
            id={id}
            data-active={client.active}
            className={client.className}
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
        )}
      </FilterField>
      <FilterField label="Delivery Lead" active={lead.active} onClear={lead.onClear}>
        {(id) => (
          <select
            id={id}
            data-active={lead.active}
            className={lead.className}
            value={filters.lead}
            onChange={(e) => set("lead", e.target.value)}
          >
            <option value="">Wszyscy</option>
            {leads.options.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
            {leads.hasNone && <option value="none">Bez Delivery Leada</option>}
          </select>
        )}
      </FilterField>
      <FilterField label="Rekruter" active={who.active} onClear={who.onClear}>
        {(id) => (
          <select
            id={id}
            data-active={who.active}
            className={who.className}
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
        )}
      </FilterField>
      <FilterField label="Kategoria" active={cat.active} onClear={cat.onClear}>
        {(id) => (
          <select
            id={id}
            data-active={cat.active}
            className={cat.className}
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
        )}
      </FilterField>
      <FilterField label="Priorytet" active={prio.active} onClear={prio.onClear}>
        {(id) => (
          <select
            id={id}
            data-active={prio.active}
            className={prio.className}
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
        )}
      </FilterField>
      <FilterField label="Termin" active={due.active} onClear={due.onClear}>
        {(id) => (
          <select
            id={id}
            data-active={due.active}
            className={due.className}
            value={filters.due}
            onChange={(e) => set("due", e.target.value as BoardFilters["due"])}
          >
            {DUE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        )}
      </FilterField>
      <FilterField label="Wysłani" active={sent.active} onClear={sent.onClear}>
        {(id) => (
          <select
            id={id}
            data-active={sent.active}
            className={sent.className}
            value={filters.sent}
            onChange={(e) => set("sent", e.target.value as BoardFilters["sent"])}
          >
            {SENT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        )}
      </FilterField>
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
      <div className="col-span-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 @min-[520px]/rboard:ml-auto @min-[520px]/rboard:justify-end">
        {activeCount > 0 ? (
          <span className="text-sm font-medium text-primary">
            {activeCount} {pluralPl(activeCount, "filtr aktywny", "filtry aktywne", "filtrów aktywnych")}
          </span>
        ) : null}
        <span className="text-sm text-muted-foreground">
          Pokazuję {shown} z {total}
        </span>
        {/* Zawsze na pasku, bez filtrów wyszarzony: przycisk, który pojawiał się
            dopiero po ustawieniu filtra, czytało się jako brak tej opcji. */}
        <Button
          variant="outline"
          size="sm"
          disabled={!hasActiveFilters(filters)}
          onClick={() => onChange(EMPTY_FILTERS)}
        >
          Wyczyść filtry
        </Button>
      </div>
    </div>
  )
}

interface FilterFieldProps {
  label: string
  active: boolean
  onClear: () => void
  children: (id: string) => ReactNode
}

/**
 * Etykieta nad polem filtra. Użyty filtr ma etykietę w kolorze i krzyżyk,
 * który czyści tylko jego. Krzyżyk stoi obok `<label>`, nie w nim — przycisk
 * w etykiecie przejąłby jej powiązanie z listą wyboru.
 */
function FilterField({ label, active, onClear, children }: FilterFieldProps) {
  const id = useId()
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex min-h-4 items-center gap-1 text-xs">
        <label
          htmlFor={id}
          className={cn("font-medium", active ? "text-primary" : "text-muted-foreground")}
        >
          {label}
        </label>
        {active ? (
          <button
            type="button"
            onClick={onClear}
            aria-label={`Wyczyść filtr: ${label}`}
            title="Wyczyść ten filtr"
            className="-my-1 inline-flex size-6 items-center justify-center rounded text-primary hover:bg-primary/15 focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <X className="size-3.5" aria-hidden="true" />
          </button>
        ) : null}
      </div>
      {children(id)}
    </div>
  )
}
