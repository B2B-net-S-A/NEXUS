"use client"

import { Clock, Crown, Info, Trophy } from"lucide-react"

import { cn } from"@/lib/utils"

// ── Types ──────────────────────────────────────────────────────────────

export interface HeroPodiumEntry {
 rank: number
 user_id: number
 name: string
 metric_value: number // pkt lub placements
 hit_ratio?: number | null
 prize_pln?: number
 role?: string
 placements?: number
 interviews?: number
 recommendations?: number
 excluded?: boolean
}

interface HeroLigaMistrzowProps {
 /**"Liga Mistrzów" lub"Liga Mistrzów DL" */
 title: string
 /**"Q2 2026" */
 period: string
 /** Dni pozostałe do końca kwartału */
 daysRemaining: number
 /** TOP 3 (rank 1/2/3 — porządek wizualny 2/1/3 na podiumie) */
 top3: HeroPodiumEntry[]
 /** Pełny ranking (10) — collapsible */
 fullRanking?: HeroPodiumEntry[]
 /** Nagrody: {1: 5000, 2: 3000, 3: 2000} */
 quarterlyPrizes: Record<number, number>
 /**"placementów" lub"pkt" — podpis pod value na podium */
 metricLabel: string
 /**"pkt" — sufiks wartości (dla rekruter po punktach) */
 metricUnit?: string
 /** Jeśli system punktowy — pokaż formułę */
 pointsFormula?: { placement: number; interview: number; recommendation: number } | null
 /** Warunek udziału (amber alert) */
 requirement?: string | null
 /** Highlight aktualnego usera */
 highlightUserId?: number | null
}

// ── Podium column (2 | 1 | 3) ─────────────────────────────────────────

const RANK_STYLE = {
 1: {
 bg:"from-amber-400 to-amber-500",
 text:"text-amber-950",
 medal:"🥇",
 crown: true,
 height:"h-40",
 rankColor:"bg-amber-500 text-white",
 },
 2: {
 bg:"from-slate-300 to-slate-400",
 text:"text-slate-900",
 medal:"🥈",
 crown: false,
 height:"h-32",
 rankColor:"bg-slate-400 text-white",
 },
 3: {
 bg:"from-orange-400 to-orange-500",
 text:"text-orange-950",
 medal:"🥉",
 crown: false,
 height:"h-28",
 rankColor:"bg-orange-500 text-white",
 },
} as const

function PodiumColumn({
 rank,
 entry,
 metricLabel,
 metricUnit,
 highlight,
}: {
 rank: 1 | 2 | 3
 entry?: HeroPodiumEntry
 metricLabel: string
 metricUnit?: string
 highlight?: boolean
}) {
 const style = RANK_STYLE[rank]
 return (
 <div className="flex flex-col items-center">
 {/* Name + value above podium */}
 {entry ? (
 <div className="text-center mb-3 flex flex-col items-center">
 <div className="text-2xl leading-none mb-1" aria-hidden>
 {style.medal}
 </div>
 <div className="text-white font-semibold text-sm">
 {entry.name}
 {style.crown && (
 <Crown className="inline h-3.5 w-3.5 ml-1 text-amber-300 -translate-y-0.5" />
 )}
 </div>
 {entry.role && (
 <div className="text-[10px] text-white/50 uppercase tracking-wide mt-0.5">
 {entry.role}
 </div>
 )}
 <div className="mt-2">
 <span className="text-amber-300 font-semibold text-2xl">
 {entry.metric_value}
 </span>
 {metricUnit && (
 <span className="text-amber-300/80 font-semibold text-sm ml-1">
 {metricUnit}
 </span>
 )}
 </div>
 {(entry.placements !== undefined ||
 entry.interviews !== undefined ||
 entry.recommendations !== undefined) && (
 <div className="text-[11px] text-white/60 mt-0.5">
 {entry.placements ?? 0}P / {entry.interviews ?? 0}I /{""}
 {entry.recommendations ?? 0}R
 </div>
 )}
 {entry.hit_ratio !== undefined && entry.hit_ratio !== null && (
 <div className="text-[11px] text-white/60 mt-0.5">
 hit: {entry.hit_ratio}%
 </div>
 )}
 </div>
 ) : (
 <div className="text-center mb-3 flex flex-col items-center opacity-40">
 <div className="text-2xl leading-none mb-1" aria-hidden>
 {style.medal}
 </div>
 <div className="text-white font-semibold text-sm">—</div>
 </div>
 )}
 {/* Block */}
 <div
 className={cn("w-full rounded-t-lg bg-gradient-to-b shadow-lg flex items-end justify-center pb-3",
 style.bg,
 style.height,
 highlight &&"ring-2 ring-white ring-offset-2 ring-offset-purple-700",
 )}
 >
 <span className="text-white text-4xl font-extrabold drop-shadow">
 {rank}
 </span>
 </div>
 </div>
 )
}

// ── Main ────────────────────────────────────────────────────────────────

export function HeroLigaMistrzow({
 title,
 period,
 daysRemaining,
 top3,
 fullRanking,
 quarterlyPrizes,
 metricLabel,
 metricUnit,
 pointsFormula,
 requirement,
 highlightUserId,
}: HeroLigaMistrzowProps) {
 const byRank = new Map(top3.map((e) => [e.rank, e]))
 // Progress bar: assume 90d quarter; show % elapsed.
 const progressPct = Math.max(
 0,
 Math.min(100, Math.round(((90 - daysRemaining) / 90) * 100)),
 )

 return (
 <div className="rounded-xl bg-gradient-to-br from-indigo-700 via-purple-700 to-purple-900 p-6 shadow-md text-white">
 {/* Header */}
 <div className="flex items-start justify-between mb-6 flex-wrap gap-3">
 <div className="flex items-center gap-3">
 <div className="h-12 w-12 rounded-lg bg-amber-500 flex items-center justify-center shadow-lg">
 <Trophy className="h-7 w-7 text-white" />
 </div>
 <div>
 <h2 className="font-semibold text-2xl md:text-3xl font-extrabold tracking-tight">
 {title}
 </h2>
 <p className="text-sm text-white/70">{period}</p>
 </div>
 </div>
 <div className="flex flex-col items-end">
 <div className="flex items-center gap-2 text-amber-300">
 <Clock className="h-4 w-4" />
 <span className="font-semibold text-2xl leading-none">
 {daysRemaining}
 </span>
 <span className="text-white/60 text-xs uppercase tracking-wide">
 dni
 </span>
 </div>
 <div className="mt-2 w-40 h-1.5 rounded-full bg-card/10 overflow-hidden">
 <div
 className="h-full rounded-full bg-gradient-to-r from-amber-400 to-amber-500 transition-all"
 style={{ width: `${progressPct}%` }}
 />
 </div>
 </div>
 </div>

 {/* Podium */}
 {top3.length > 0 ? (
 <div className="grid grid-cols-3 gap-4 md:gap-8 items-end max-w-2xl mx-auto">
 {[2, 1, 3].map((rank) => {
 const entry = byRank.get(rank as 1 | 2 | 3)
 return (
 <PodiumColumn
 key={rank}
 rank={rank as 1 | 2 | 3}
 entry={entry}
 metricLabel={metricLabel}
 metricUnit={metricUnit}
 highlight={
 entry !== undefined && highlightUserId === entry.user_id
 }
 />
 )
 })}
 </div>
 ) : (
 <div className="text-center py-10">
 <Trophy className="h-12 w-12 mx-auto mb-3 text-white/30" />
 <p className="text-white/60 text-sm">Brak zwycięzców w tym okresie</p>
 </div>
 )}

 {/* Prize bars */}
 <div className="grid grid-cols-3 gap-2 md:gap-3 mt-4 max-w-2xl mx-auto">
 {[1, 2, 3].map((rank) => {
 const prize = quarterlyPrizes[rank]
 const style = RANK_STYLE[rank as 1 | 2 | 3]
 return (
 <div
 key={rank}
 className="rounded-md bg-card/5 border border-white/10 px-3 py-2 text-center"
 >
 <div className="flex items-center justify-center gap-1 text-[10px] uppercase tracking-wide text-white/50">
 <Crown className={cn("h-3 w-3", style.text.replace("950","400"))} />
 {rank}. miejsce
 </div>
 <div className="text-amber-300 font-semibold text-lg leading-tight">
 {prize.toLocaleString("pl-PL")} PLN
 </div>
 </div>
 )
 })}
 </div>

 {/* Points formula */}
 {pointsFormula && (
 <div className="mt-5 rounded-md bg-card/5 border border-white/10 px-4 py-2.5 flex items-center gap-4 flex-wrap">
 <div className="flex items-center gap-1.5 text-xs text-white/60 uppercase tracking-wide">
 <Info className="h-3.5 w-3.5" />
 System punktowy
 </div>
 <div className="flex items-center gap-4 text-sm">
 <span>
 <span className="font-semibold text-emerald-300">Placement:</span>{""}
 <span className="font-mono font-bold">{pointsFormula.placement} pkt</span>
 </span>
 <span>
 <span className="font-semibold text-sky-300">Interview:</span>{""}
 <span className="font-mono font-bold">{pointsFormula.interview} pkt</span>
 </span>
 <span>
 <span className="font-semibold text-purple-300">Rekomendacja:</span>{""}
 <span className="font-mono font-bold">
 {pointsFormula.recommendation} pkt
 </span>
 </span>
 </div>
 </div>
 )}

 {/* Requirement */}
 {requirement && (
 <div className="mt-3 rounded-md bg-amber-500/10 border border-amber-400/30 px-4 py-2.5">
 <div className="text-xs text-amber-300 uppercase tracking-wide font-semibold mb-0.5">
 ⚠ Warunek udziału
 </div>
 <div className="text-sm text-white/80">{requirement}</div>
 </div>
 )}

 {/* Full ranking collapsible */}
 {fullRanking && fullRanking.length > 3 && (
 <details className="mt-4 rounded-md bg-card/5 border border-white/10">
 <summary className="cursor-pointer px-4 py-2.5 text-sm text-white/70 hover:text-white">
 Zobacz pełny ranking ({fullRanking.length - 3} więcej)
 </summary>
 <div className="px-4 pb-3 space-y-1">
 {fullRanking.slice(3).map((e) => (
 <div
 key={e.user_id}
 className={cn("flex items-center justify-between text-sm py-1.5 px-2 rounded",
 highlightUserId === e.user_id
 ?"bg-card/15 font-semibold"
 :"hover:bg-card/5",
 )}
 >
 <span className="text-white/80">
 #{e.rank} {e.name}
 {e.role && (
 <span className="text-white/40 text-xs ml-1.5 uppercase">
 {e.role}
 </span>
 )}
 </span>
 <span className="tabular-nums">
 <span className="font-bold text-amber-300">
 {e.metric_value}
 </span>
 {metricUnit && (
 <span className="text-white/50 ml-1 text-xs">
 {metricUnit}
 </span>
 )}
 </span>
 </div>
 ))}
 </div>
 </details>
 )}
 </div>
 )
}
