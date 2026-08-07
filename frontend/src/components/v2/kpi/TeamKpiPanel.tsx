"use client"

import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ChevronDown, ChevronUp, Search, Users } from "lucide-react"

import api from "@/lib/api"
import { cn } from "@/lib/utils"
import { ROLE_LABELS, hasRole, useAuthStore, type UserRole } from "@/store/auth"

// ── Types (mirror TeamPanelSchema z backendu) ─────────────────────────────

type Period = "day" | "week" | "month"

interface TeamMember {
  user_id: number
  name: string
  role: string
  weryfikacje: number
  rekomendacje: number
  interview: number
  akceptacje: number
  placementy: number
  cv_to_base: number
  precision_pct: number | null
  precision_verified_30d: number
  precision_sent_30d: number
}

interface TeamTotals {
  weryfikacje: number
  rekomendacje: number
  interview: number
  akceptacje: number
  placementy: number
  cv_to_base: number
  precision_pct: number | null
  people: number
}

interface TeamPanel {
  period: string
  precision_target_pct: number
  rows: TeamMember[]
  totals: TeamTotals
}

const PERIOD_LABEL: Record<Period, string> = {
  day: "Dziś",
  week: "Tydzień",
  month: "Miesiąc",
}

// Próg minimalnej liczby weryfikacji w 30 dniach, by pokazać precision
// (lustro `_PRECISION_MIN_DENOM` z backendu).
const PRECISION_MIN_DENOM = 5

// Kolumny liczbowe — klucz do sortowania + nagłówek + krótki opis (title).
type NumKey = Exclude<
  keyof TeamMember,
  "user_id" | "name" | "role" | "precision_verified_30d" | "precision_sent_30d"
>
type SortKey = "name" | NumKey

const COLUMNS: { key: NumKey; label: string; hint: string }[] = [
  { key: "weryfikacje", label: "Weryfikacje", hint: "Kandydaci przeniesieni na etap Zweryfikowany" },
  { key: "rekomendacje", label: "Rekomendacje", hint: "CV wysłane do klienta" },
  { key: "interview", label: "Interview", hint: "Zaproszenia na rozmowę" },
  { key: "akceptacje", label: "Akceptacje", hint: "Kandydaci zaakceptowani" },
  { key: "placementy", label: "Placementy", hint: "Aktywne kontrakty (hired)" },
  { key: "precision_pct", label: "Precision", hint: "Rekomendacje ÷ weryfikacje (30 dni)" },
  { key: "cv_to_base", label: "CV do bazy", hint: "Nowi kandydaci dodani do bazy" },
]

// ── Widget ─────────────────────────────────────────────────────────────────

/**
 * „KPI zespołu" — managerski widok lejka per osoba dla całego zespołu.
 *
 * Atrybucja verifier-anchored (identyczna z „Moje KPI"), więc kolumny sumują
 * się do tych samych liczb, które każdy widzi u siebie. Filtry: okno czasu
 * (Dziś/Tydzień/Miesiąc — zmienia zapytanie), rola (dropdown) oraz osoba
 * (wyszukiwarka). Sortowanie po dowolnej kolumnie (klik w nagłówek).
 *
 * Widoczny dla każdej roli operacyjnej (decyzja właściciela 2026-08-07:
 * cały zespół widzi imienne wyniki wszystkich, jak w InfraReporterze).
 * Finance i legacy `user` — null (backend też ich odcina).
 */
export function TeamKpiPanel({ className }: { className?: string }) {
  const user = useAuthStore((s) => s.user)
  const canView = hasRole(
    user,
    "admin",
    "head_of_recruitment",
    "delivery_lead",
    "tac",
    "recruiter",
    "sourcer",
  )

  const [period, setPeriod] = useState<Period>("week")
  const [roleFilter, setRoleFilter] = useState<UserRole | "all">("all")
  const [nameQuery, setNameQuery] = useState("")
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
    key: "placementy",
    dir: "desc",
  })

  const { data, isLoading, error } = useQuery<TeamPanel>({
    queryKey: ["team-kpi-panel", period],
    queryFn: () =>
      api.get(`/api/kpis/team/panel?period=${period}`).then((r) => r.data),
    enabled: canView,
    staleTime: 60_000,
  })

  // Role obecne w danych → opcje dropdowna (zachowaj hierarchię).
  const roleOptions = useMemo(() => {
    if (!data) return [] as UserRole[]
    const present = new Set(data.rows.map((r) => r.role))
    const order: UserRole[] = [
      "head_of_recruitment",
      "delivery_lead",
      "tac",
      "recruiter",
      "sourcer",
      "admin",
      "user",
    ]
    return order.filter((r) => present.has(r))
  }, [data])

  const filtered = useMemo(() => {
    if (!data) return [] as TeamMember[]
    const q = nameQuery.trim().toLowerCase()
    let rows = data.rows
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
  }, [data, roleFilter, nameQuery, sort])

  // Suma WIDOCZNYCH wierszy (po filtrach), nie całego zespołu.
  const totals = useMemo(() => {
    const base = {
      weryfikacje: 0,
      rekomendacje: 0,
      interview: 0,
      akceptacje: 0,
      placementy: 0,
      cv_to_base: 0,
      v30: 0,
      s30: 0,
    }
    for (const r of filtered) {
      base.weryfikacje += r.weryfikacje
      base.rekomendacje += r.rekomendacje
      base.interview += r.interview
      base.akceptacje += r.akceptacje
      base.placementy += r.placementy
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

  if (!canView) return null

  const target = data?.precision_target_pct ?? 75

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
          hit ? "text-emerald-600" : "text-amber-600",
        )}
      >
        {pct}%
      </span>
    )
  }

  return (
    <section
      className={cn("rounded-xl border border-border bg-card p-4", className)}
      aria-label="KPI zespołu"
    >
      <header className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">KPI zespołu</h2>
          {data && (
            <span className="text-xs text-muted-foreground">
              · {filtered.length}/{data.totals.people} os.
            </span>
          )}
        </div>
        <div className="inline-flex rounded-lg border border-border p-0.5 text-xs">
          {(["day", "week", "month"] as Period[]).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPeriod(p)}
              className={cn(
                "rounded-md px-2.5 py-1 font-medium transition-colors",
                period === p
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {PERIOD_LABEL[p]}
            </button>
          ))}
        </div>
      </header>

      {/* Filtry: rola + osoba */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value as UserRole | "all")}
          className="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-hidden focus:ring-2 focus:ring-ring"
          aria-label="Filtruj po roli"
        >
          <option value="all">Wszystkie role</option>
          {roleOptions.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r]}
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

      {/* Tabela */}
      {isLoading ? (
        <div className="space-y-2 py-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-8 animate-pulse rounded bg-[hsl(var(--border))]"
            />
          ))}
        </div>
      ) : error ? (
        <p className="py-6 text-center text-xs text-muted-foreground">
          Nie udało się wczytać KPI zespołu.
        </p>
      ) : filtered.length === 0 ? (
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
                  <td className="px-2 py-2 text-right tabular-nums text-foreground">
                    {r.weryfikacje}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-foreground">
                    {r.rekomendacje}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-foreground">
                    {r.interview}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-foreground">
                    {r.akceptacje}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums font-semibold text-foreground">
                    {r.placementy}
                  </td>
                  <td className="px-2 py-2 text-right">
                    {precisionCell(r.precision_pct)}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-foreground">
                    {r.cv_to_base}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-border bg-muted/30 text-sm font-semibold">
                <td className="py-2 pr-3 text-foreground">
                  Razem ({filtered.length})
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {totals.weryfikacje}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {totals.rekomendacje}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {totals.interview}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {totals.akceptacje}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {totals.placementy}
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
    </section>
  )
}

export default TeamKpiPanel
