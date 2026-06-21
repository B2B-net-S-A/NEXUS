"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

export interface DataTableColumn<T> {
  /** Stable identifier for the column. */
  key: string
  /** Column header label (user-facing). */
  header: string
  /** Text alignment for the column body and header. Defaults to "left". */
  align?: "left" | "right"
  /** Optional fixed column width (e.g. "12rem", "120px"). */
  width?: string
  /** Custom cell renderer. Falls back to nothing when omitted. */
  render?: (row: T) => React.ReactNode
}

export interface DataTableProps<T> {
  /** Column definitions, in display order. */
  columns: Array<DataTableColumn<T>>
  /** Row data. */
  rows: T[]
  /** Stable key extractor for a row. */
  getRowKey: (row: T) => string | number
  /** When true, the row is visually emphasized (bg-primary/5). */
  rowHighlighted?: (row: T) => boolean
  /** Row click handler. When provided, rows become interactive. */
  onRowClick?: (row: T) => void
  /** Content shown when there are no rows. Defaults to a centered message. */
  empty?: React.ReactNode
}

const alignClass: Record<"left" | "right", string> = {
  left: "text-left",
  right: "text-right",
}

export function DataTable<T>({
  columns,
  rows,
  getRowKey,
  rowHighlighted,
  onRowClick,
  empty,
}: DataTableProps<T>) {
  const isInteractive = typeof onRowClick === "function"

  return (
    <div className="flow-root">
      <div className="-mx-4 -my-2 overflow-x-auto sm:-mx-6 lg:-mx-8">
        <div className="inline-block min-w-full py-2 align-middle sm:px-6 lg:px-8">
          {rows.length === 0 ? (
            <div className="px-4 py-12 text-center text-sm text-muted-foreground sm:px-0">
              {empty ?? "Brak danych do wyświetlenia."}
            </div>
          ) : (
            <table className="min-w-full divide-y divide-border">
              <thead>
                <tr>
                  {columns.map((column, index) => (
                    <th
                      key={column.key}
                      scope="col"
                      style={column.width ? { width: column.width } : undefined}
                      className={cn(
                        "py-3.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground",
                        alignClass[column.align ?? "left"],
                        index === 0 ? "pl-4 pr-3 sm:pl-0" : "px-3",
                        index === columns.length - 1 && "pr-4 sm:pr-0",
                      )}
                    >
                      {column.header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((row) => {
                  const highlighted = rowHighlighted?.(row) ?? false
                  return (
                    <tr
                      key={getRowKey(row)}
                      onClick={isInteractive ? () => onRowClick?.(row) : undefined}
                      className={cn(
                        "transition-colors",
                        highlighted ? "bg-primary/5" : "hover:bg-muted/40",
                        isInteractive && "cursor-pointer",
                      )}
                    >
                      {columns.map((column, index) => (
                        <td
                          key={column.key}
                          className={cn(
                            "whitespace-nowrap py-4 text-sm text-foreground",
                            alignClass[column.align ?? "left"],
                            index === 0 ? "pl-4 pr-3 sm:pl-0" : "px-3",
                            index === columns.length - 1 && "pr-4 sm:pr-0",
                          )}
                        >
                          {column.render ? column.render(row) : null}
                        </td>
                      ))}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

DataTable.displayName = "DataTable"
