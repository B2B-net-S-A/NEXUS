"use client"

import { Crown, Medal, Trophy } from"lucide-react"

import { Card } from"@/components/ui/card"
import { cn } from"@/lib/utils"

// ── Types ──────────────────────────────────────────────────────────────

export interface PodiumEntry {
 rank: number
 user_id: number
 name: string
 metric_value: number
 hit_ratio?: number | null
 prize_pln?: number
 extras?: Record<string, unknown>
}

interface ChampionsPodiumProps {
 title: string
 subtitle?: string
 period: string
 top3: PodiumEntry[]
 metricLabel: string // np."placements","rekomendacji"
 targetPct?: number | null // dla DL: próg 30%
 highlightUserId?: number | null
 empty?: React.ReactNode
}

// ── Medal style ─────────────────────────────────────────────────────────

const RANK_STYLE = {
 1: {
 icon: Crown,
 border: "border-amber-400",
 bg: "bg-linear-to-br from-amber-50 to-amber-100",
 text: "text-amber-600",
 medal: "🥇",
 height: "h-36",
 },
 2: {
 icon: Medal,
 border: "border-slate-300",
 bg: "bg-linear-to-br from-slate-50 to-slate-100",
 text: "text-slate-500",
 medal: "🥈",
 height: "h-32",
 },
 3: {
 icon: Medal,
 border: "border-orange-300",
 bg: "bg-linear-to-br from-orange-50 to-orange-100",
 text: "text-orange-600",
 medal: "🥉",
 height: "h-28",
 },
} as const

// ── Main ──────────────────────────────────────────────────────────────

export function ChampionsPodium({
 title,
 subtitle,
 period,
 top3,
 metricLabel,
 targetPct,
 highlightUserId,
 empty,
}: ChampionsPodiumProps) {
 const byRank = new Map(top3.map((e) => [e.rank, e]))

 if (!top3.length) {
 return (
 <Card>
 <div className="flex flex-col items-center justify-center py-10 text-muted-foreground">
 <Trophy className="h-10 w-10 mb-3 opacity-30" />
 <p className="text-sm font-medium">
 {empty ??"Brak zwycięzców w tym okresie"}
 </p>
 {targetPct !== null && targetPct !== undefined && (
 <p className="text-xs mt-1">
 Próg wejścia na podium: {targetPct}% hit ratio
 </p>
 )}
 </div>
 </Card>
 )
 }

 return (
 <Card>
 <div className="flex items-start justify-between mb-4">
 <div>
 <div className="flex items-center gap-2">
 <Trophy className="h-4 w-4 text-amber-500" />
 <h3 className="font-semibold text-lg font-bold text-foreground">
 {title}
 </h3>
 </div>
 {subtitle && (
 <p className="text-xs text-muted-foreground mt-0.5">
 {subtitle}
 </p>
 )}
 </div>
 <span className="text-xs font-semibold uppercase tracking-wider text-primary">
 {period}
 </span>
 </div>

 {/* Podium grid — porządek wizualny: 2 | 1 | 3 */}
 <div className="grid grid-cols-3 gap-3 items-end">
 {[2, 1, 3].map((rank) => {
 const entry = byRank.get(rank)
 const style = RANK_STYLE[rank as 1 | 2 | 3]
 const isMe = entry && highlightUserId === entry.user_id
 return (
 <div key={rank} className="flex flex-col items-center">
 <div
 className={cn("w-full rounded-lg border-2 p-3 flex flex-col items-center justify-end transition-all",
 style.height,
 style.bg,
 isMe ?"border-primary ring-2 ring-[hsl(var(--muted))]" : style.border,
 )}
 >
 <div className="text-3xl mb-1" aria-hidden>
 {style.medal}
 </div>
 <p
 className={cn("text-sm font-bold text-center line-clamp-2","text-foreground",
 )}
 title={entry?.name}
 >
 {entry?.name ??"—"}
 </p>
 {entry && (
 <>
 <p className={cn("text-2xl font-extrabold mt-1", style.text)}>
 {entry.metric_value}
 </p>
 <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
 {metricLabel}
 </p>
 {entry.hit_ratio !== null && entry.hit_ratio !== undefined && (
 <p className="text-[10px] text-muted-foreground">
 hit: {entry.hit_ratio}%
 </p>
 )}
 {!!entry.prize_pln && (
 <p className="text-[11px] font-bold text-[#1d5e31] mt-1">
 {entry.prize_pln.toLocaleString("pl-PL")} PLN
 </p>
 )}
 </>
 )}
 </div>
 <span className="mt-2 text-[11px] font-bold text-muted-foreground">
 #{rank}
 </span>
 </div>
 )
 })}
 </div>

 {targetPct !== null && targetPct !== undefined && (
 <p className="mt-3 text-[10px] text-center text-muted-foreground">
 Próg wejścia: hit ratio ≥ {targetPct}%
 </p>
 )}
 </Card>
 )
}
