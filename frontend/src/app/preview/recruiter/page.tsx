"use client"

import {
  ArrowDownRight,
  ArrowUpRight,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  Filter,
  GitCompareArrows,
  RefreshCw,
  Target,
  Trophy,
  Users,
} from "lucide-react"

import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

// ── Mock data (prototyp — bez backendu) ────────────────────────────────────

const KPIS = [
  { label: "Weryfikacje", value: 540, delta: 12, sub: "Ja 86 · cel 75", icon: Filter, spark: [40, 42, 38, 45, 44, 50, 52, 58] },
  { label: "Rekomendacje", value: 210, delta: 8, sub: "Ja 31 tego miesiąca", icon: Users, spark: [22, 20, 24, 23, 26, 25, 28, 30] },
  { label: "Interviews", value: 96, delta: -3, sub: "Ja 14 tego miesiąca", icon: CheckCircle2, spark: [19, 18, 20, 17, 18, 16, 15, 14] },
  { label: "Placements", value: 38, delta: 18, sub: "Ja 6 tego miesiąca", icon: Target, spark: [3, 4, 3, 5, 4, 6, 5, 6] },
] as const

const FUNNEL = [
  { label: "Weryfikacje", count: 540, width: 100, conv: "—" },
  { label: "Rekomendacje", count: 210, width: 39, conv: "39%" },
  { label: "Interviews", count: 96, width: 18, conv: "46%" },
  { label: "Placements", count: 38, width: 7, conv: "40%" },
] as const

const PODIUM = [
  { rank: 1, name: "Anna Kowalska", points: 1240, me: false },
  { rank: 2, name: "Piotr Zieliński", points: 1080, me: false },
  { rank: 3, name: "Marta Nowak", points: 960, me: true },
] as const
const LEADER_POINTS = PODIUM[0].points

const TEAM = [
  { name: "Anna Kowalska", role: "recruiter", cat: "Dev", wer: 92, rek: 41, int: 18, plac: 9, hit: 9.8, me: false },
  { name: "Piotr Zieliński", role: "tac", cat: "Infra", wer: 110, rek: 38, int: 15, plac: 7, hit: 6.4, me: false },
  { name: "Marta Nowak", role: "recruiter", cat: "Data & AI", wer: 86, rek: 31, int: 14, plac: 6, hit: 7.0, me: true },
  { name: "Tomasz Lis", role: "sourcer", cat: "Dev", wer: 124, rek: 29, int: 11, plac: 4, hit: 3.2, me: false },
  { name: "Karolina Wójcik", role: "recruiter", cat: "Security & QA", wer: 71, rek: 26, int: 13, plac: 5, hit: 7.0, me: false },
  { name: "Michał Adamski", role: "tac", cat: "Management", wer: 57, rek: 18, int: 8, plac: 3, hit: 5.3, me: false },
] as const

const ROLE_STYLE: Record<string, "soft" | "info" | "success" | "neutral"> = {
  recruiter: "soft",
  tac: "info",
  sourcer: "success",
}

const MEDAL: Record<number, string> = {
  1: "bg-amber-100 text-amber-800",
  2: "bg-slate-200 text-slate-700",
  3: "bg-orange-100 text-orange-800",
}

// ── Bits ───────────────────────────────────────────────────────────────────

function Initials({ name, className }: { name: string; className?: string }) {
  const i = name
    .split(" ")
    .map((s) => s[0])
    .slice(0, 2)
    .join("")
    .toUpperCase()
  return (
    <span
      className={cn(
        "flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary",
        className,
      )}
    >
      {i}
    </span>
  )
}

function TrendPill({ value }: { value: number }) {
  const up = value >= 0
  return (
    <Badge variant={up ? "success" : "danger"} size="sm" className="gap-0.5 px-1.5">
      {up ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
      {up ? "+" : ""}
      {value}%
    </Badge>
  )
}

function Sparkline({ points, className }: { points: readonly number[]; className?: string }) {
  const w = 72
  const h = 26
  const max = Math.max(...points)
  const min = Math.min(...points)
  const range = max - min || 1
  const step = w / (points.length - 1)
  const coords = points.map((p, i) => [i * step, h - ((p - min) / range) * h] as const)
  const d = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ")
  const [lx, ly] = coords[coords.length - 1]
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} fill="none" className={cn("shrink-0", className)}>
      <path d={d} stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" className="opacity-50" />
      <circle cx={lx} cy={ly} r="2.2" fill="currentColor" />
    </svg>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────

export default function RecruiterPreview() {
  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-[1180px] space-y-7 px-6 py-9">
        {/* Header */}
        <div className="flex flex-wrap items-end justify-between gap-4 border-b border-border pb-6">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-primary">
              Panel Rekrutacja · Rekruter
            </p>
            <h1 className="mt-2 text-[28px] font-semibold leading-none tracking-tight text-foreground">
              Cześć, Marta
            </h1>
            <p className="mt-2.5 text-sm text-muted-foreground">
              Twój wynik na tle zespołu · zaktualizowano 2 min temu
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="gap-2">
              <CalendarDays className="h-4 w-4 text-muted-foreground" />
              Czerwiec 2026
              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
            </Button>
            <Button variant="outline" size="sm">
              <RefreshCw className="h-4 w-4" />
              Odśwież
            </Button>
          </div>
        </div>

        {/* KPI row */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {KPIS.map((k) => (
            <Card key={k.label} className="p-5 transition-shadow duration-200 hover:shadow-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <k.icon className="h-3.5 w-3.5" />
                  </span>
                  <span className="text-[13px] font-medium text-muted-foreground">{k.label}</span>
                </div>
                <TrendPill value={k.delta} />
              </div>
              <div className="mt-4 flex items-end justify-between gap-3">
                <div>
                  <div className="text-[32px] font-semibold leading-none tracking-tight tabular-nums text-foreground">
                    {k.value}
                  </div>
                  <p className="mt-2.5 text-xs text-muted-foreground">{k.sub}</p>
                </div>
                <Sparkline points={k.spark} className="text-primary" />
              </div>
            </Card>
          ))}
        </div>

        {/* Funnel + Podium */}
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-5">
          {/* Funnel */}
          <Card className="p-6 lg:col-span-3">
            <div className="mb-6 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <GitCompareArrows className="h-4 w-4 text-muted-foreground" />
                <h2 className="text-[15px] font-semibold text-foreground">Lejek rekrutacyjny</h2>
              </div>
              <Badge variant="soft" size="sm">
                Wer → Plac · 7,0%
              </Badge>
            </div>
            <div className="space-y-3.5">
              {FUNNEL.map((f) => (
                <div key={f.label} className="flex items-center gap-4">
                  <span className="w-24 shrink-0 text-sm text-muted-foreground">{f.label}</span>
                  <div className="relative h-8 flex-1 overflow-hidden rounded-full bg-muted">
                    <div
                      className="flex h-full items-center justify-end rounded-full bg-primary/85 pr-3"
                      style={{ width: `${Math.max(f.width, 9)}%` }}
                    >
                      <span className="text-xs font-semibold tabular-nums text-primary-foreground">
                        {f.count}
                      </span>
                    </div>
                  </div>
                  <span className="w-16 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                    {f.conv}
                  </span>
                </div>
              ))}
            </div>
          </Card>

          {/* Liga Mistrzów podium */}
          <Card className="p-6 lg:col-span-2">
            <div className="mb-5 flex items-center gap-2">
              <Trophy className="h-4 w-4 text-primary" />
              <h2 className="text-[15px] font-semibold text-foreground">Liga Mistrzów</h2>
              <Badge variant="soft" size="sm" className="ml-auto">
                Q2 · 12 dni
              </Badge>
            </div>
            <div className="space-y-2">
              {PODIUM.map((p) => (
                <div
                  key={p.rank}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5",
                    p.me ? "bg-primary/5 ring-1 ring-primary/25" : "bg-muted/40",
                  )}
                >
                  <span
                    className={cn(
                      "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold tabular-nums",
                      MEDAL[p.rank],
                    )}
                  >
                    {p.rank}
                  </span>
                  <Initials name={p.name} />
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2 truncate text-sm font-medium text-foreground">
                      <span className="truncate">{p.name}</span>
                      {p.me && (
                        <Badge variant="soft" size="sm">
                          Ja
                        </Badge>
                      )}
                    </p>
                    <div className="mt-1.5 flex items-center gap-2">
                      <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary/60"
                          style={{ width: `${(p.points / LEADER_POINTS) * 100}%` }}
                        />
                      </div>
                      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                        {p.points} pkt
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* Team leaderboard */}
        <Card className="p-6">
          <div className="mb-5 flex items-center gap-2">
            <Users className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-[15px] font-semibold text-foreground">Zespół</h2>
            <span className="text-sm text-muted-foreground">· ranking po placementach · czerwiec 2026</span>
          </div>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-10">#</TableHead>
                <TableHead>Osoba</TableHead>
                <TableHead>Rola</TableHead>
                <TableHead>Kategoria</TableHead>
                <TableHead className="text-right">Wer</TableHead>
                <TableHead className="text-right">Rek</TableHead>
                <TableHead className="text-right">Int</TableHead>
                <TableHead className="text-right">Plac</TableHead>
                <TableHead className="w-44">Skuteczność</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {TEAM.map((r, idx) => (
                <TableRow key={r.name} className={cn("transition-colors", r.me && "bg-primary/5 hover:bg-primary/5")}>
                  <TableCell>
                    {idx < 3 ? (
                      <span
                        className={cn(
                          "flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold tabular-nums",
                          MEDAL[idx + 1],
                        )}
                      >
                        {idx + 1}
                      </span>
                    ) : (
                      <span className="pl-1 text-sm tabular-nums text-muted-foreground">{idx + 1}</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2.5">
                      <Initials name={r.name} />
                      <span className="font-medium text-foreground">{r.name}</span>
                      {r.me && (
                        <Badge variant="soft" size="sm">
                          Ja
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={ROLE_STYLE[r.role] ?? "neutral"} size="sm" uppercase>
                      {r.role}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{r.cat}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{r.wer}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{r.rek}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{r.int}</TableCell>
                  <TableCell className="text-right font-semibold tabular-nums text-foreground">{r.plac}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2.5">
                      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary"
                          style={{ width: `${Math.min(100, r.hit * 8)}%` }}
                        />
                      </div>
                      <span className="text-xs tabular-nums text-muted-foreground">{r.hit.toFixed(1)}%</span>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </div>
    </div>
  )
}
