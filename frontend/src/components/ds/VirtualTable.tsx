"use client"

import * as React from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, ChevronsUpDown } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

/**
 * VirtualTable — gęsta, wirtualizowana tabela (role="grid") na listy od kilkudziesięciu
 * do kilku tysięcy wierszy: grupy z nagłówkami, zaznaczanie (z shift-zakresem), aktywny
 * wiersz sterowany z klawiatury, kontrolowane sortowanie, slot stopki na pasek akcji.
 *
 * Komponent jest w pełni KONTROLOWANY: zaznaczenie, aktywny wiersz, sortowanie i zwinięcie
 * grup trzyma rodzic. Tabela niczego nie sortuje ani nie filtruje sama.
 */

export type VirtualTableKey = string | number

export interface VirtualTableColumn<Row> {
  /** Stable identifier for the column. */
  key: string
  /** Column header label (user-facing). */
  header: React.ReactNode
  /** CSS grid track, e.g. "minmax(0,1.2fr)" or "124px". */
  width: string
  /** Text alignment for the column body and header. Defaults to "left". */
  align?: "left" | "right" | "center"
  /** Cell renderer. */
  render: (row: Row) => React.ReactNode
  /** When set, the header becomes a sort button reporting this key. */
  sortKey?: string
}

export interface VirtualTableGroup {
  key: VirtualTableKey
  label: React.ReactNode
  /** Shown next to the label; defaults to the number of rows found for the group. */
  count?: number
  /** Extra content on the right side of the group header (e.g. SLA hint). */
  hint?: React.ReactNode
  collapsed?: boolean
  /** Row keys belonging to the group, in display order. */
  rowKeys: VirtualTableKey[]
}

export interface VirtualTableSort {
  key: string
  dir: "asc" | "desc"
}

export interface VirtualTableProps<Row> {
  columns: Array<VirtualTableColumn<Row>>
  rows: Row[]
  getRowKey: (row: Row) => VirtualTableKey
  /** Accessible name of a row — used for the selection checkbox label. */
  getRowLabel?: (row: Row) => string
  /** Row height in px. Defaults to 36 (compact) / 44 (cozy). */
  rowHeight?: number
  density?: "compact" | "cozy"

  groups?: VirtualTableGroup[]
  onToggleGroup?: (key: VirtualTableKey) => void

  /** Selection column renders only when `onSelectionChange` is provided. */
  selectedKeys?: Set<VirtualTableKey>
  onSelectionChange?: (next: Set<VirtualTableKey>) => void

  activeKey?: VirtualTableKey | null
  onActiveChange?: (key: VirtualTableKey, row: Row) => void
  /** Enter on the active row. */
  onRowActivate?: (row: Row) => void
  /** Allowlist of single keys delegated to `onKeyCommand` (case-insensitive), e.g. ["e","n"]. */
  keyCommands?: string[]
  onKeyCommand?: (key: string, row: Row) => void

  sort?: VirtualTableSort | null
  onSortChange?: (next: VirtualTableSort | null) => void

  empty?: React.ReactNode
  loading?: boolean
  /** Pinned below the scroll area (bulk-action bar). */
  footer?: React.ReactNode
  /**
   * Escape hatch: `false` renders every row in normal flow, without windowing.
   * jsdom has no layout — the scroll element measures 0×0, so the virtualizer yields
   * zero items and tests would see an empty table. Production keeps the default (`true`);
   * tests (and very short lists, if a caller prefers) pass `false`.
   */
  virtualize?: boolean
  /** Accessible name of the grid. */
  "aria-label"?: string
  className?: string
}

const SELECT_TRACK = "36px"
const OVERSCAN = 8
const SKELETON_ROWS = 8

type Item<Row> =
  | { type: "group"; group: VirtualTableGroup; count: number }
  | { type: "row"; row: Row; rowKey: VirtualTableKey }

const alignClass: Record<"left" | "right" | "center", string> = {
  left: "justify-start text-left",
  right: "justify-end text-right",
  center: "justify-center text-center",
}

/** Typing must never be hijacked: text fields, selects and contenteditable own their keys. */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  if (target.closest("[contenteditable]:not([contenteditable='false'])")) return true
  const tag = target.tagName
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT"
}

/** Buttons/links inside a row keep their native Space/Enter behaviour. */
function isInteractiveTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.closest("button, a[href], [role='button']") !== null
}

function buildItems<Row>(
  rows: Row[],
  getRowKey: (row: Row) => VirtualTableKey,
  groups: VirtualTableGroup[] | undefined,
): Array<Item<Row>> {
  if (!groups) {
    return rows.map((row) => ({ type: "row", row, rowKey: getRowKey(row) }))
  }
  const byKey = new Map<VirtualTableKey, Row>()
  for (const row of rows) byKey.set(getRowKey(row), row)
  const placed = new Set<VirtualTableKey>()
  const items: Array<Item<Row>> = []
  for (const group of groups) {
    const members: Array<Item<Row>> = []
    for (const rowKey of group.rowKeys) {
      const row = byKey.get(rowKey)
      if (row === undefined || placed.has(rowKey)) continue
      placed.add(rowKey)
      members.push({ type: "row", row, rowKey })
    }
    items.push({ type: "group", group, count: group.count ?? members.length })
    if (!group.collapsed) items.push(...members)
  }
  // Wiersz spoza wszystkich grup NIE może zniknąć po cichu — ląduje na końcu, bez nagłówka.
  for (const row of rows) {
    const rowKey = getRowKey(row)
    if (!placed.has(rowKey)) items.push({ type: "row", row, rowKey })
  }
  return items
}

interface RowProps<Row> {
  row: Row
  rowKey: VirtualTableKey
  columns: Array<VirtualTableColumn<Row>>
  template: string
  height: number
  /** Absolute offset in virtualized mode; undefined = normal flow. */
  start: number | undefined
  ariaRowIndex: number
  selectable: boolean
  selected: boolean
  active: boolean
  label: string
  cellPad: string
  onRowClick: (rowKey: VirtualTableKey) => void
  onToggleSelect: (rowKey: VirtualTableKey, shiftKey: boolean) => void
}

function VirtualTableRowInner<Row>({
  row,
  rowKey,
  columns,
  template,
  height,
  start,
  ariaRowIndex,
  selectable,
  selected,
  active,
  label,
  cellPad,
  onRowClick,
  onToggleSelect,
}: RowProps<Row>) {
  return (
    <div
      role="row"
      aria-rowindex={ariaRowIndex}
      aria-selected={selectable ? selected : undefined}
      aria-current={active ? "true" : undefined}
      data-row-key={String(rowKey)}
      data-active={active ? "" : undefined}
      onClick={() => onRowClick(rowKey)}
      style={{
        display: "grid",
        gridTemplateColumns: template,
        height,
        ...(start === undefined
          ? null
          : { position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${start}px)` }),
      }}
      className={cn(
        "cursor-pointer items-center border-b border-l-2 border-border border-l-transparent text-foreground transition-colors",
        active ? "border-l-primary bg-primary/5" : selected ? "bg-muted/60" : "hover:bg-muted/40",
      )}
    >
      {selectable ? (
        <div
          role="gridcell"
          className="flex h-full items-center justify-center"
          onClick={(event) => event.stopPropagation()}
        >
          <input
            type="checkbox"
            className="size-3.5 cursor-pointer accent-primary"
            aria-label={`Zaznacz: ${label}`}
            checked={selected}
            onChange={(event) =>
              onToggleSelect(rowKey, (event.nativeEvent as MouseEvent).shiftKey === true)
            }
          />
        </div>
      ) : null}
      {columns.map((column) => (
        <div
          key={column.key}
          role="gridcell"
          className={cn("flex h-full min-w-0 items-center", cellPad, alignClass[column.align ?? "left"])}
        >
          <div className="min-w-0 max-w-full truncate">{column.render(row)}</div>
        </div>
      ))}
    </div>
  )
}

// React.memo gubi parametr generyczny — rzutowanie przywraca sygnaturę.
const VirtualTableRow = React.memo(VirtualTableRowInner) as typeof VirtualTableRowInner

export function VirtualTable<Row>({
  columns,
  rows,
  getRowKey,
  getRowLabel,
  rowHeight,
  density = "compact",
  groups,
  onToggleGroup,
  selectedKeys,
  onSelectionChange,
  activeKey = null,
  onActiveChange,
  onRowActivate,
  keyCommands,
  onKeyCommand,
  sort = null,
  onSortChange,
  empty,
  loading = false,
  footer,
  virtualize = true,
  "aria-label": ariaLabel,
  className,
}: VirtualTableProps<Row>) {
  const height = rowHeight ?? (density === "cozy" ? 44 : 36)
  const headerHeight = density === "cozy" ? 36 : 32
  const cellPad = density === "cozy" ? "px-3 text-sm" : "px-2 text-xs"
  const selectable = typeof onSelectionChange === "function"

  const scrollRef = React.useRef<HTMLDivElement>(null)
  const anchorRef = React.useRef<VirtualTableKey | null>(null)

  const template = React.useMemo(
    () => [selectable ? SELECT_TRACK : null, ...columns.map((c) => c.width)].filter(Boolean).join(" "),
    [columns, selectable],
  )

  const items = React.useMemo(() => buildItems(rows, getRowKey, groups), [rows, getRowKey, groups])

  /** Visible rows only (collapsed groups excluded) — keyboard and shift-range order. */
  const visible = React.useMemo(() => {
    const out: Array<{ rowKey: VirtualTableKey; row: Row; itemIndex: number }> = []
    items.forEach((item, itemIndex) => {
      if (item.type === "row") out.push({ rowKey: item.rowKey, row: item.row, itemIndex })
    })
    return out
  }, [items])

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => height,
    overscan: OVERSCAN,
    // Sticky nagłówek zajmuje miejsce w przewijanym elemencie przed listą.
    scrollMargin: headerHeight,
    scrollPaddingStart: headerHeight,
  })
  React.useEffect(() => {
    virtualizer.measure()
  }, [virtualizer, height])

  // Najświeższe propsy w refie → stabilne callbacki → React.memo na wierszach działa.
  const latest = React.useRef({ selectedKeys, onSelectionChange, onActiveChange, visible })
  latest.current = { selectedKeys, onSelectionChange, onActiveChange, visible }

  const handleRowClick = React.useCallback((rowKey: VirtualTableKey) => {
    const { visible: list, onActiveChange: notify } = latest.current
    const hit = list.find((entry) => entry.rowKey === rowKey)
    if (hit) notify?.(rowKey, hit.row)
  }, [])

  const handleToggleSelect = React.useCallback((rowKey: VirtualTableKey, shiftKey: boolean) => {
    const { selectedKeys: current, onSelectionChange: notify, visible: list } = latest.current
    if (!notify) return
    const next = new Set(current ?? [])
    const willSelect = !next.has(rowKey)
    const anchor = anchorRef.current
    const from = shiftKey && anchor !== null ? list.findIndex((e) => e.rowKey === anchor) : -1
    const to = list.findIndex((e) => e.rowKey === rowKey)
    if (from >= 0 && to >= 0) {
      const [lo, hi] = from < to ? [from, to] : [to, from]
      for (let i = lo; i <= hi; i += 1) {
        if (willSelect) next.add(list[i].rowKey)
        else next.delete(list[i].rowKey)
      }
    } else if (willSelect) {
      next.add(rowKey)
    } else {
      next.delete(rowKey)
    }
    anchorRef.current = rowKey
    notify(next)
  }, [])

  // Header checkbox ---------------------------------------------------------
  const allKeys = React.useMemo(() => rows.map(getRowKey), [rows, getRowKey])
  const selectedCount = React.useMemo(
    () => (selectedKeys ? allKeys.reduce<number>((n, k) => n + (selectedKeys.has(k) ? 1 : 0), 0) : 0),
    [allKeys, selectedKeys],
  )
  const allSelected = allKeys.length > 0 && selectedCount === allKeys.length
  const someSelected = selectedCount > 0 && !allSelected
  const headerCheckboxRef = React.useRef<HTMLInputElement>(null)
  React.useEffect(() => {
    if (headerCheckboxRef.current) headerCheckboxRef.current.indeterminate = someSelected
  }, [someSelected, selectable, loading])

  const toggleAll = () => {
    if (!onSelectionChange) return
    const next = new Set(selectedKeys ?? [])
    if (allSelected) allKeys.forEach((k) => next.delete(k))
    else allKeys.forEach((k) => next.add(k))
    onSelectionChange(next)
  }

  // Keyboard ---------------------------------------------------------------
  const scrollToItem = (itemIndex: number, rowKey: VirtualTableKey) => {
    if (virtualize) {
      virtualizer.scrollToIndex(itemIndex, { align: "auto" })
      return
    }
    const wanted = String(rowKey)
    const nodes = scrollRef.current?.querySelectorAll<HTMLElement>("[data-row-key]") ?? []
    for (const el of Array.from(nodes)) {
      if (el.dataset.rowKey === wanted) {
        el.scrollIntoView?.({ block: "nearest" })
        break
      }
    }
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return
    if (isTypingTarget(event.target)) return
    if (visible.length === 0) return

    const activeIndex = activeKey === null ? -1 : visible.findIndex((e) => e.rowKey === activeKey)
    const active = activeIndex >= 0 ? visible[activeIndex] : null

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault()
      const delta = event.key === "ArrowDown" ? 1 : -1
      const nextIndex =
        activeIndex < 0
          ? delta > 0
            ? 0
            : visible.length - 1
          : Math.min(visible.length - 1, Math.max(0, activeIndex + delta))
      const target = visible[nextIndex]
      if (target.rowKey !== activeKey) onActiveChange?.(target.rowKey, target.row)
      scrollToItem(target.itemIndex, target.rowKey)
      return
    }

    // Przycisk/link w wierszu zachowuje natywne Space/Enter.
    const onOwnControl = event.target !== event.currentTarget && isInteractiveTarget(event.target)

    if (event.key === " " || event.key === "Spacebar") {
      if (onOwnControl || !active || !selectable) return
      event.preventDefault()
      handleToggleSelect(active.rowKey, false)
      return
    }
    if (event.key === "Enter") {
      if (onOwnControl || !active || !onRowActivate) return
      event.preventDefault()
      onRowActivate(active.row)
      return
    }
    if (active && onKeyCommand && keyCommands && event.key.length === 1) {
      const pressed = event.key.toLowerCase()
      if (keyCommands.some((k) => k.toLowerCase() === pressed)) {
        event.preventDefault()
        onKeyCommand(pressed, active.row)
      }
    }
  }

  // Sorting ----------------------------------------------------------------
  const cycleSort = (sortKey: string) => {
    if (!onSortChange) return
    if (!sort || sort.key !== sortKey) onSortChange({ key: sortKey, dir: "asc" })
    else if (sort.dir === "asc") onSortChange({ key: sortKey, dir: "desc" })
    else onSortChange(null)
  }

  // Render -----------------------------------------------------------------
  const isEmpty = !loading && rows.length === 0
  const columnCount = columns.length + (selectable ? 1 : 0)

  const renderItem = (item: Item<Row>, itemIndex: number, start: number | undefined) => {
    if (item.type === "group") {
      const { group } = item
      const expanded = !group.collapsed
      const Chevron = expanded ? ChevronDown : ChevronRight
      return (
        <div
          key={`g:${group.key}`}
          role="row"
          aria-rowindex={itemIndex + 2}
          data-group-key={String(group.key)}
          style={{
            height,
            ...(start === undefined
              ? null
              : { position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${start}px)` }),
          }}
          className="border-b border-border bg-muted"
        >
          <div role="gridcell" aria-colspan={columnCount} className="h-full">
            <button
              type="button"
              aria-expanded={expanded}
              onClick={() => onToggleGroup?.(group.key)}
              className={cn(
                "flex h-full w-full items-center gap-2 text-left font-semibold text-foreground hover:bg-muted-foreground/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                cellPad,
              )}
            >
              <Chevron className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate">{group.label}</span>
              <span className="shrink-0 tabular-nums font-normal text-muted-foreground">{item.count}</span>
              {group.hint ? (
                <span className="ml-auto shrink-0 font-normal text-muted-foreground">{group.hint}</span>
              ) : null}
            </button>
          </div>
        </div>
      )
    }
    return (
      <VirtualTableRow<Row>
        key={`r:${item.rowKey}`}
        row={item.row}
        rowKey={item.rowKey}
        columns={columns}
        template={template}
        height={height}
        start={start}
        ariaRowIndex={itemIndex + 2}
        selectable={selectable}
        selected={selectedKeys?.has(item.rowKey) ?? false}
        active={activeKey !== null && item.rowKey === activeKey}
        label={getRowLabel ? getRowLabel(item.row) : String(item.rowKey)}
        cellPad={cellPad}
        onRowClick={handleRowClick}
        onToggleSelect={handleToggleSelect}
      />
    )
  }

  return (
    <div className={cn("flex h-full min-h-0 flex-col overflow-hidden rounded-md border border-border bg-card", className)}>
      <div
        ref={scrollRef}
        role="grid"
        tabIndex={0}
        aria-label={ariaLabel}
        aria-rowcount={items.length + 1}
        aria-colcount={columnCount}
        aria-multiselectable={selectable || undefined}
        aria-busy={loading || undefined}
        onKeyDown={handleKeyDown}
        className="relative min-h-0 flex-1 overflow-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      >
        <div role="rowgroup" className="sticky top-0 z-10">
          <div
            role="row"
            aria-rowindex={1}
            style={{ display: "grid", gridTemplateColumns: template, height: headerHeight }}
            className="items-center border-b border-l-2 border-border border-l-transparent bg-card"
          >
            {selectable ? (
              <div role="columnheader" className="flex h-full items-center justify-center">
                <input
                  ref={headerCheckboxRef}
                  type="checkbox"
                  className="size-3.5 cursor-pointer accent-primary"
                  aria-label="Zaznacz wszystkie"
                  aria-checked={someSelected ? "mixed" : allSelected}
                  checked={allSelected}
                  disabled={allKeys.length === 0}
                  onChange={toggleAll}
                />
              </div>
            ) : null}
            {columns.map((column) => {
              const sorted = column.sortKey && sort?.key === column.sortKey ? sort.dir : null
              const SortIcon = sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ChevronsUpDown
              const headClass = cn(
                "flex h-full min-w-0 items-center text-[11px] font-semibold uppercase tracking-wide text-muted-foreground",
                density === "cozy" ? "px-3" : "px-2",
                alignClass[column.align ?? "left"],
              )
              return (
                <div
                  key={column.key}
                  role="columnheader"
                  aria-sort={
                    column.sortKey
                      ? sorted === "asc"
                        ? "ascending"
                        : sorted === "desc"
                          ? "descending"
                          : "none"
                      : undefined
                  }
                  className={headClass}
                >
                  {column.sortKey && onSortChange ? (
                    <button
                      type="button"
                      onClick={() => cycleSort(column.sortKey as string)}
                      className={cn(
                        "inline-flex min-w-0 items-center gap-1 rounded-sm uppercase tracking-wide hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        sorted && "text-foreground",
                      )}
                    >
                      <span className="truncate">{column.header}</span>
                      <SortIcon className={cn("size-3 shrink-0", !sorted && "opacity-50")} aria-hidden />
                    </button>
                  ) : (
                    <span className="truncate">{column.header}</span>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {loading ? (
          <div role="rowgroup" data-testid="virtual-table-loading">
            {Array.from({ length: SKELETON_ROWS }, (_, index) => (
              <div
                key={index}
                role="row"
                style={{ display: "grid", gridTemplateColumns: template, height }}
                className="items-center border-b border-l-2 border-border border-l-transparent"
              >
                {selectable ? <div role="gridcell" /> : null}
                {columns.map((column) => (
                  <div key={column.key} role="gridcell" className={cellPad}>
                    <Skeleton className="h-3 w-3/4" />
                  </div>
                ))}
              </div>
            ))}
          </div>
        ) : isEmpty ? (
          // Pusty stan też musi być wierszem siatki: goły <div> wewnątrz
          // role="grid" łamie aria-required-children (axe: critical).
          <div role="rowgroup">
            <div role="row">
              <div
                role="gridcell"
                aria-colspan={columns.length + (selectable ? 1 : 0)}
                className="px-4 py-12 text-center text-sm text-muted-foreground"
              >
                {empty ?? "Brak danych do wyświetlenia."}
              </div>
            </div>
          </div>
        ) : virtualize ? (
          <div
            role="rowgroup"
            style={{ height: virtualizer.getTotalSize(), width: "100%", position: "relative" }}
          >
            {virtualizer
              .getVirtualItems()
              .map((v) => renderItem(items[v.index], v.index, v.start - headerHeight))}
          </div>
        ) : (
          <div role="rowgroup">{items.map((item, index) => renderItem(item, index, undefined))}</div>
        )}
      </div>
      {footer ? <div className="shrink-0 border-t border-border bg-card">{footer}</div> : null}
    </div>
  )
}

VirtualTable.displayName = "VirtualTable"
