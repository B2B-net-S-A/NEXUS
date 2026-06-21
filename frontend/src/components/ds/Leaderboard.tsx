import * as React from "react"
import { Trophy } from "lucide-react"

import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

// ── Initials avatar ──────────────────────────────────────────────────────────

interface InitialsProps {
  name: string
  className?: string
}

/** Small circular avatar rendering up to two uppercase initials. */
export function Initials({ name, className }: InitialsProps) {
  const initials = name
    .split(" ")
    .map((part) => part[0])
    .filter(Boolean)
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
      {initials}
    </span>
  )
}

// ── Rank styling (token-pure, no literal gold/silver) ─────────────────────────

/** Token-based rank chip styling: #1 = primary tint, #2–3 = muted. */
function rankChipClass(rank: number): string {
  return rank === 1
    ? "bg-primary/15 text-primary"
    : "bg-muted text-muted-foreground"
}

// ── Podium ────────────────────────────────────────────────────────────────────

export interface PodiumEntry {
  rank: number
  name: string
  points: number
  me?: boolean
}

export interface PodiumProps {
  entries: PodiumEntry[]
  /** Reference score for the progress bars. Defaults to the top entry's points. */
  leaderPoints?: number
  title?: string
  className?: string
}

/** Top-3 podium with progress bars relative to the leader's score. */
export function Podium({
  entries,
  leaderPoints,
  title = "Liga Mistrzów",
  className,
}: PodiumProps) {
  const reference =
    leaderPoints ?? entries.reduce((max, e) => Math.max(max, e.points), 0) ?? 1

  return (
    <Card size="lg" className={className}>
      <div className="mb-5 flex items-center gap-2">
        <Trophy className="h-4 w-4 text-primary" />
        <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
      </div>
      <div className="space-y-2">
        {entries.map((entry) => (
          <div
            key={entry.rank}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2.5",
              entry.me ? "bg-primary/5 ring-1 ring-primary/25" : "bg-muted/40",
            )}
          >
            <span
              className={cn(
                "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold tabular-nums",
                rankChipClass(entry.rank),
              )}
            >
              {entry.rank}
            </span>
            <Initials name={entry.name} />
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-2 truncate text-sm font-medium text-foreground">
                <span className="truncate">{entry.name}</span>
                {entry.me && (
                  <Badge variant="soft" size="sm">
                    Ja
                  </Badge>
                )}
              </p>
              <div className="mt-1.5 flex items-center gap-2">
                <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary/60"
                    style={{
                      width: `${Math.min(100, (entry.points / (reference || 1)) * 100)}%`,
                    }}
                  />
                </div>
                <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                  {entry.points} pkt
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

// ── Leaderboard ────────────────────────────────────────────────────────────────

export interface LeaderboardRow {
  name: string
  /** Primary metric shown in the value column. */
  metric: number | string
  me?: boolean
}

export interface LeaderboardProps {
  rows: LeaderboardRow[]
  title?: string
  /** Header label for the value column. */
  metricLabel?: string
  className?: string
}

/** Generic ranked table: rank chip + initials + name + a single metric. */
export function Leaderboard({
  rows,
  title = "Ranking",
  metricLabel = "Wynik",
  className,
}: LeaderboardProps) {
  return (
    <Card size="lg" className={className}>
      <div className="mb-5 flex items-center gap-2">
        <Trophy className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
      </div>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-10">#</TableHead>
            <TableHead>Osoba</TableHead>
            <TableHead className="text-right">{metricLabel}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, idx) => {
            const rank = idx + 1
            return (
              <TableRow
                key={row.name}
                className={cn(
                  "transition-colors",
                  row.me && "bg-primary/5 hover:bg-primary/5",
                )}
              >
                <TableCell>
                  <span
                    className={cn(
                      "flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold tabular-nums",
                      rankChipClass(rank),
                    )}
                  >
                    {rank}
                  </span>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2.5">
                    <Initials name={row.name} />
                    <span className="font-medium text-foreground">{row.name}</span>
                    {row.me && (
                      <Badge variant="soft" size="sm">
                        Ja
                      </Badge>
                    )}
                  </div>
                </TableCell>
                <TableCell className="text-right font-semibold tabular-nums text-foreground">
                  {row.metric}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </Card>
  )
}
