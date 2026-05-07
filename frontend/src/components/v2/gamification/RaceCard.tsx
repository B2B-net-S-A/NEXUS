"use client"

import { Clock, Gift, Info, Trophy } from"lucide-react"

import { cn } from"@/lib/utils"

interface RaceEntry {
 rank: number
 user_id: number
 name: string
 metric_value: number
 role?: string
 excluded?: boolean
 extras?: Record<string, unknown>
}

interface RaceCardProps {
 title: string
 period: string
 daysRemaining: number
 variant: "blue" |"green"
 prize: { amount_pln: number; name: string }
 requirements: string[]
 ranking: RaceEntry[]
 metricSuffix: string //"rek." /"plac."
 highlightUserId?: number | null
}

const VARIANT = {
 blue: {
 headerBg: "from-indigo-500 via-blue-600 to-indigo-700",
 accent: "text-primary",
 badge: "bg-primary/15 text-primary",
 rankBg: {
 1: "bg-amber-400 text-amber-950",
 2: "bg-slate-300 text-slate-900",
 3: "bg-orange-400 text-orange-950",
 other: "bg-primary/20 text-primary",
 },
 },
 green: {
 headerBg: "from-emerald-500 via-teal-600 to-emerald-700",
 accent: "text-emerald-200",
 badge: "bg-emerald-100 text-emerald-900",
 rankBg: {
 1: "bg-amber-400 text-amber-950",
 2: "bg-slate-300 text-slate-900",
 3: "bg-orange-400 text-orange-950",
 other: "bg-emerald-200 text-emerald-900",
 },
 },
} as const

export function RaceCard({
 title,
 period,
 daysRemaining,
 variant,
 prize,
 requirements,
 ranking,
 metricSuffix,
 highlightUserId,
}: RaceCardProps) {
 const v = VARIANT[variant]

 const rankColor = (rank: number): string => {
 if (rank === 1) return v.rankBg[1]
 if (rank === 2) return v.rankBg[2]
 if (rank === 3) return v.rankBg[3]
 return v.rankBg.other
 }

 return (
 <div className="rounded-lg overflow-hidden border border-border shadow-sm bg-card">
 {/* Gradient header */}
 <div
 className={cn("bg-gradient-to-r px-4 py-3 text-white flex items-center justify-between",
 v.headerBg,
 )}
 >
 <div className="flex items-center gap-2">
 <Trophy className="h-5 w-5" />
 <div>
 <div className="font-semibold text-lg leading-tight">
 {title}
 </div>
 <div className="text-xs text-white/70">{period}</div>
 </div>
 </div>
 <div className="flex items-center gap-1.5 text-amber-200">
 <Clock className="h-4 w-4" />
 <span className="font-semibold text-xl leading-none">
 {daysRemaining}
 </span>
 <span className="text-white/60 text-[10px] uppercase">dni</span>
 </div>
 </div>

 {/* Prize + requirements */}
 <div className="divide-y divide-border">
 <div className="px-4 py-2.5 flex items-center gap-2 text-sm text-foreground">
 <Gift className="h-4 w-4 text-primary shrink-0" />
 <span className="font-medium">{prize.name}</span>
 </div>
 {requirements.map((req, idx) => (
 <div
 key={idx}
 className="px-4 py-2 flex items-start gap-2 text-xs text-muted-foreground"
 >
 <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
 <span>{req}</span>
 </div>
 ))}
 </div>

 {/* Ranking */}
 <div className="divide-y divide-border">
 {ranking.length === 0 && (
 <div className="px-4 py-6 text-center text-sm text-muted-foreground">
 Brak zakwalifikowanych osób w tym miesiącu.
 </div>
 )}
 {ranking.slice(0, 5).map((entry) => {
 const isMe = highlightUserId === entry.user_id
 return (
 <div
 key={entry.user_id}
 className={cn("px-4 py-2.5 flex items-center gap-3 text-sm",
 isMe &&"bg-primary/10/40 font-semibold",
 entry.excluded &&"opacity-60",
 )}
 >
 <span
 className={cn("inline-flex items-center justify-center h-7 w-7 rounded-full font-bold text-xs shrink-0",
 rankColor(entry.rank),
 )}
 >
 {entry.rank}
 </span>
 <div className="flex-1 min-w-0">
 <div className="text-foreground truncate">
 {entry.name}
 {entry.excluded && (
 <span className="ml-2 text-[10px] uppercase text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded">
 lider Q — bez nagrody
 </span>
 )}
 </div>
 {entry.role && (
 <div className="text-[10px] uppercase text-muted-foreground tracking-wide">
 {entry.role}
 </div>
 )}
 </div>
 <div className="text-right tabular-nums">
 <span className="font-bold text-foreground">
 {entry.metric_value}
 </span>
 <span className="text-muted-foreground text-xs ml-1">
 {metricSuffix}
 </span>
 </div>
 </div>
 )
 })}
 </div>
 </div>
 )
}
