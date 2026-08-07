"use client"

import { useMemo, useState } from "react"
import { ChevronDown, ChevronUp, Search } from "lucide-react"

import { cn } from "@/lib/utils"
import { ROLE_LABELS, type UserRole } from "@/store/auth"
import type {
  RecruitmentTeamTable as RecruitmentTeamTableData,
  RecruitmentTeamTableRow,
} from "@/lib/dashboard-v2-api"

// Prezentacyjna ekstrakcja tabeli z components/v2/kpi/TeamKpiPanel.tsx —
// logika sortowania/filtrów 1:1, ale dane przychodzą propsem (composite
// /api/dashboard/v2/recruitment-stats), a nie własnym fetchem. Wiersz
// „Razem" liczy sumę WIDOCZNYCH wierszy (po filtrach), nie całego zespołu.

// Lustro `_PRECISION_MIN_DENOM` z backendu (app/services/kpi_panel.py).
const PRECISION_MIN_DENOM = 5

type NumKey =
  | "verifications"
  | "recommendations"
  | "interviews"
  | "acceptances"
  | "placements"
  | "precision_pct"
  | "cv_to_base"
type SortKey = "name" | NumKey

const COLUMNS: { key: NumKey; label: string; hint: string }[] = [
  {
    key: "verifications",
    label: "Weryfikacje",
    hint: "Kandydaci przeniesieni na etap Zweryfikowany",
  },
  { key: "recommendations", label: "Rekomendacje", hint: "CV wysłane do klienta" },
  { key: "interviews", label: "Interview", hint: "Zaproszenia na rozmowę" },
  {
    key: "acceptances",
    label: "Akceptacje",
    hint: "Klient zaakceptował kandydata",
  },
  { key: "placements", label: "Placementy", hint: "Zatrudnieni (hired)" },
  {
    key: "precision_pct",
    label: "Precision",
    hint: "Rekomendacje ÷ weryfikacje (30 dni)",
  },
  { key: "cv_to_base", label: "CV do bazy", hint: "Nowi kandydaci dodani do bazy" },
]

export function RecruitmentTeamTable({
  table,
  className,
}: {
  table: RecruitmentTeamTableData
  className?: string
}) {
  const [roleFilter, setRoleFilter] = useState<string>("all")
  const [nameQuery, setNameQuery] = useState("")
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
    key: "placements",
    dir: "desc",
  })

  const roleOptions = useMemo(() => {
    const present = new Set(table.rows.map((r) => r.role))
    const order = [
      "head_of_recruitment",
      "delivery_lead",
      "tac",
      "recruiter",
      "sourcer",
      "admin",
      "user",
    ]
    return order.filter((r) => present.has(r))
  }, [table.rows])

  const filtered = useMemo(() => {
    const q = nameQuery.trim().toLowerCase()
    let rows = table.rows
    if (roleFilter !== "all") rows = rows.filter((r) => r.role === roleFilter)
    if (q) rows = rows.filter((r) => r.name.toLowerCase().includes(q))

    const dir = sort.dir === "asc" ? 1 : -1
    return [...rows].sort((a, b) => {
      if (sort.key === "name") return dir * a.name.localeCompare(b.name, "pl")
      const av = (a[sort.key] ?? -1) as number
      const bv = (b[sort.key] ?? -1) as number
      if (av === bv) return a.name.localeCompare(b.name, "pl")
      return dir * (av - bv)
    })
  }, [table.rows, roleFilter, nameQuery, sort])

  const totals = useMemo(() => {
    const base = {
      verifications: 0,
      recommendations: 0,
      interviews: 0,
      acceptances: 0,
      placements: 0,
      cv_to_base: 0,
      v30: 0,
      s30: 0,
    }
    for (const r of filtered) {
      base.verifications += r.verifications
      base.recommendations += r.recommendations
      base.interviews += r.interviews
      base.acceptances += r.acceptances
      base.placements += r.placements
      base.cv_to_base += r.cv_to_base
      base.v30 += r.precision_verified_30d
      base.s30 += r.precision_sent_30d
    }
    const precision =
      base.v30 >= PRECISION_MIN_DENOM
        ? Math.round((100 * base.s30) / base.v30)
        : null
    return { ...base, precision }
  }, [filtered])

  const target = table.precision_target_pct

  function toggleSort(key: SortKey) {
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === "desc" ? "asc" : "desc" }
        : { key, dir: key === "name" ? "asc" : "desc" },
    )
  }

  function SortIcon({ active, dir }: { active: boolean; dir: "asc" | "desc" }) {
    if (!active)
      return <ChevronDown className="h-3 w-3 opacity-25" aria-hidden />
    return dir === "desc" ? (
      <ChevronDown className="h-3 w-3" aria-hidden />
    ) : (
      <ChevronUp className="h-3 w-3" aria-hidden />
    )
  }

  function precisionCell(pct: number | null) {
    if (pct == null) return <span className="text-muted-foreground">—</span>
    const hit = pct >= target
    return (
      <span
        className={cn(
          "font-semibold tabular-nums",
          hit ? "text-success" : "text-warning",
        )}
      >
        {pct}%
      </span>
    )
  }

  function numCell(row: RecruitmentTeamTableRow, key: NumKey) {
    if (key === "precision_pct") return precisionCell(row.precision_pct)
    return (
      <span
        className={cn(
          "tabular-nums text-foreground",
          key === "placements" && "font-semibold",
        )}
      >
        {row[key]}
      </span>
    )
  }

  return (
    <div className={className}>
      {/* Filtry: rola + osoba */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
          className="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-hidden focus:ring-2 focus:ring-ring"
          aria-label="Filtruj po roli"
        >
          <option value="all">Wszystkie role</option>
          {roleOptions.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r as UserRole] ?? r}
            </option>
          ))}
        </select>
        <div className="relative flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={nameQuery}
            onChange={(e) => setNameQuery(e.target.value)}
            placeholder="Szukaj osoby…"
            className="h-8 w-full rounded-md border border-border bg-background pl-7 pr-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-hidden focus:ring-2 focus:ring-ring"
            aria-label="Szukaj osoby"
          />
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="py-6 text-center text-xs text-muted-foreground">
          Brak osób spełniających filtry.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="py-2 pr-3 text-left font-medium">
                  <button
                    type="button"
                    onClick={() => toggleSort("name")}
                    className="inline-flex items-center gap-1 hover:text-foreground"
                  >
                    Osoba
                    <SortIcon active={sort.key === "name"} dir={sort.dir} />
                  </button>
                </th>
                {COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    className="px-2 py-2 text-right font-medium"
                    title={c.hint}
                  >
                    <button
                      type="button"
                      onClick={() => toggleSort(c.key)}
                      className="inline-flex items-center gap-1 hover:text-foreground"
                    >
                      {c.label}
                      <SortIcon active={sort.key === c.key} dir={sort.dir} />
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr
                  key={r.user_id}
                  className="border-b border-border/50 last:border-0 hover:bg-muted/40"
                >
                  <td className="py-2 pr-3">
                    <div className="flex flex-col">
                      <span className="font-medium text-foreground">
                        {r.name}
                      </span>
                      <span className="text-[11px] text-muted-foreground">
                        {ROLE_LABELS[r.role as UserRole] ?? r.role}
                      </span>
                    </div>
                  </td>
                  {COLUMNS.map((c) => (
                    <td key={c.key} className="px-2 py-2 text-right">
                      {numCell(r, c.key)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-border bg-muted/30 text-sm font-semibold">
                <td className="py-2 pr-3 text-foreground">
                  Razem ({filtered.length})
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {totals.verifications}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {totals.recommendations}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {totals.interviews}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {totals.acceptances}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {totals.placements}
                </td>
                <td className="px-2 py-2 text-right">
                  {precisionCell(totals.precision)}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {totals.cv_to_base}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  )
}

export default RecruitmentTeamTable
