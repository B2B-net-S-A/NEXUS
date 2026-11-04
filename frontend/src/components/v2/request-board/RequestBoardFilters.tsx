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
  groupCatValue,
  hasActiveFilters,
  isSentActive,
  leadOptions,
  peopleOptions,
  sentBound,
  sentRangeLabel,
  type BoardFilters,
} from "@/lib/request-board"
import { PRIORITY_LEVEL_OPTIONS } from "@/lib/request-priority"
import { cn } from "@/lib/utils"

import { BoardMultiSelect, type BoardMultiSelectOption } from "./BoardMultiSelect"

/** Filtry-listy z kilkoma wartościami naraz. */
type ListKey = "client" | "lead" | "who" | "cat" | "prio" | "due"

// Wąski kontener (kafelek na telefonie): pola w dwóch kolumnach na całą
// szerokość — dziewięć pól jedno pod drugim zajmowało ponad pół ekranu.
// Od 520 px pulpitu (`rboard`) pola stoją w rzędzie i zawijają się.
const fieldBase =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
/** Lista wyboru: w rzędzie tak szeroka jak napis na przycisku, najwyżej 220 px. */
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
  const q = { active: Boolean(filters.q), onClear: () => set("q", "") }
  const pickerClass = (active: boolean) => cn(fieldClass, active && activeClass)
  const list = <K extends ListKey>(
    key: K,
    label: string,
    placeholder: string,
    options: readonly BoardMultiSelectOption<BoardFilters[K][number]>[],
  ) => {
    const active = filters[key].length > 0
    return (
      <FilterField label={label} active={active} onClear={() => set(key, [])}>
        {(id) => (
          <BoardMultiSelect
            id={id}
            className={pickerClass(active)}
            placeholder={placeholder}
            options={options}
            value={filters[key]}
            onChange={(next) => set(key, next as BoardFilters[K])}
          />
        )}
      </FilterField>
    )
  }
  const sentActive = isSentActive(filters)
  const range = sentRangeLabel(filters)

  return (
    <div className="grid grid-cols-2 items-end gap-3 rounded-lg border border-border bg-card p-3 @min-[520px]/rboard:flex @min-[520px]/rboard:flex-wrap">
      <FilterField label="Stanowisko" active={q.active} onClear={q.onClear}>
        {(id) => (
          <input
            id={id}
            data-active={q.active}
            className={cn(inputClass, q.active && activeClass)}
            placeholder="np. Java albo numer"
            value={filters.q}
            onChange={(e) => set("q", e.target.value)}
          />
        )}
      </FilterField>
      {list(
        "client",
        "Klient",
        "Wszyscy klienci",
        clientOptions(board).map((c) => ({ value: c, label: c })),
      )}
      {list("lead", "Delivery Lead", "Wszyscy", [
        ...leads.options.map((l) => ({ value: l.id, label: l.name })),
        ...(leads.hasNone ? [{ value: "none", label: "Bez Delivery Leada" }] : []),
      ])}
      {list(
        "who",
        "Rekruter",
        "Wszyscy",
        peopleOptions(board).map((p) => ({ value: p.id, label: p.name })),
      )}
      {list(
        "cat",
        "Kategoria",
        "Wszystkie kategorie",
        board.groups.map((g) => ({ value: groupCatValue(g), label: g.name })),
      )}
      {list("prio", "Priorytet", "Każdy priorytet", PRIORITY_LEVEL_OPTIONS)}
      {list("due", "Termin", "Każdy termin", DUE_OPTIONS)}
      <FilterField
        label="Wysłani"
        active={sentActive}
        onClear={() => onChange({ ...filters, sent: [], sentFrom: "", sentTo: "" })}
      >
        {(id) => (
          <BoardMultiSelect
            id={id}
            className={pickerClass(sentActive)}
            active={sentActive}
            placeholder="Dowolnie"
            options={SENT_OPTIONS}
            value={filters.sent}
            onChange={(next) => set("sent", next)}
            extraLabels={range ? [range] : []}
            footer={
              <SentRangeFields
                from={filters.sentFrom}
                to={filters.sentTo}
                onChange={(sentFrom, sentTo) => onChange({ ...filters, sentFrom, sentTo })}
              />
            }
          />
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

interface SentRangeFieldsProps {
  from: string
  to: string
  onChange: (from: string, to: string) => void
}

/**
 * Własny przedział „Wysłani” (prośba Head of Recruitment 27.10.2026): od / do,
 * jedna granica wystarczy. Pole przyjmuje tylko liczby całkowite — reszta
 * czyści granicę. Liczy się razem z zaznaczonymi pozycjami listy.
 */
function SentRangeFields({ from, to, onChange }: SentRangeFieldsProps) {
  const rangeInput =
    "h-8 w-16 rounded-md border border-input bg-background px-2 text-sm tabular-nums text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
  return (
    <fieldset className="mt-1 border-t border-border px-2 pt-2 pb-1">
      <legend className="sr-only">Własny przedział wysłanych</legend>
      <p className="mb-1.5 text-xs font-medium text-muted-foreground">Własny przedział</p>
      <div className="flex items-center gap-2 text-sm">
        <label className="flex items-center gap-1.5">
          od
          <input
            type="number"
            inputMode="numeric"
            min={0}
            className={rangeInput}
            aria-label="Wysłanych od"
            value={from}
            onChange={(e) => onChange(sentBound(e.target.value), to)}
          />
        </label>
        <label className="flex items-center gap-1.5">
          do
          <input
            type="number"
            inputMode="numeric"
            min={0}
            className={rangeInput}
            aria-label="Wysłanych do"
            value={to}
            onChange={(e) => onChange(from, sentBound(e.target.value))}
          />
        </label>
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground">Bez requestów z championem.</p>
    </fieldset>
  )
}
