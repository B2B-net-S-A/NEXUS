"use client"

import { useMemo, useState } from "react"
import { ChevronDown, ChevronUp, Crown } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

import { fillRateColor, hitRatioColor, type DlRow } from "./types"

type SortKey =
  | "placements"
  | "total_requests"
  | "total_vacancies"
  | "hit_ratio"
  | "fill_rate"
  | "name"

interface DlRankingProps {
  rows: DlRow[]
  highlightUserId?: number | null
  targetPct: number
}

export function DlRanking({ rows, highlightUserId, targetPct }: DlRankingProps) {
  const [sortBy, setSortBy] = useState<SortKey>("placements")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")

  const sorted = useMemo(() => {
    const data = [...rows]
    data.sort((a, b) => {
      const va = a[sortBy] as number | string
      const vb = b[sortBy] as number | string
      if (typeof va === "string" && typeof vb === "string") {
        return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va)
      }
      const na = Number(va) || 0
      const nb = Number(vb) || 0
      return sortDir === "asc" ? na - nb : nb - na
    })
    return data
  }, [rows, sortBy, sortDir])

  function toggleSort(key: SortKey) {
    if (sortBy === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc")
    } else {
      setSortBy(key)
      setSortDir("desc")
    }
  }

  const Header = ({ col, label }: { col: SortKey; label: string }) => (
    <th
      className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2 cursor-pointer select-none"
      onClick={() => toggleSort(col)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {sortBy === col &&
          (sortDir === "asc" ? (
            <ChevronUp className="h-3 w-3" />
          ) : (
            <ChevronDown className="h-3 w-3" />
          ))}
      </span>
    </th>
  )

  const rankBadge = (idx: number): string => {
    if (idx === 0) return "bg-emerald-500 text-white"
    if (idx === 1) return "bg-sky-500 text-white"
    if (idx === 2) return "bg-amber-500 text-white"
    return "bg-slate-200 text-slate-700"
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-border">
          <tr>
            <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2 w-12">
              #
            </th>
            <Header col="name" label="Delivery Lead" />
            <Header col="total_requests" label="Zapytania" />
            <Header col="total_vacancies" label="Wakaty" />
            <Header col="placements" label="Placements" />
            <Header col="hit_ratio" label="Hit Ratio" />
            <Header col="fill_rate" label="Fill Rate" />
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {sorted.map((r, idx) => {
            const isMe = highlightUserId === r.user_id
            return (
              <tr
                key={r.user_id}
                className={cn("hover:bg-primary/10", isMe && "bg-primary/10")}
              >
                <td className="px-3 py-2">
                  <span
                    className={cn(
                      "inline-flex items-center justify-center h-6 w-6 rounded-full text-xs font-bold",
                      rankBadge(idx),
                    )}
                  >
                    {idx + 1}
                  </span>
                </td>
                <td className="px-3 py-2 font-medium text-foreground">
                  {r.name}
                  {isMe && (
                    <Badge variant="soft" size="sm" className="ml-2">
                      Ja
                    </Badge>
                  )}
                  {r.target_achieved && (
                    <Crown
                      className="inline h-3.5 w-3.5 ml-1.5 text-amber-500"
                      aria-label={`hit ratio ≥ ${targetPct}%`}
                    />
                  )}
                </td>
                <td className="px-3 py-2 tabular-nums">{r.total_requests}</td>
                <td className="px-3 py-2 tabular-nums text-sky-600">
                  {r.total_vacancies}
                </td>
                <td className="px-3 py-2 tabular-nums font-semibold">
                  {r.placements}
                </td>
                <td
                  className={cn(
                    "px-3 py-2 tabular-nums",
                    hitRatioColor(r.hit_ratio, targetPct),
                  )}
                >
                  {r.hit_ratio.toFixed(1)}%
                </td>
                <td
                  className={cn("px-3 py-2 tabular-nums", fillRateColor(r.fill_rate))}
                >
                  {r.fill_rate.toFixed(1)}%
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {sorted.length === 0 && (
        <p className="text-center text-sm text-muted-foreground py-6">
          Brak danych w tym okresie.
        </p>
      )}
    </div>
  )
}
