"use client"

import { CheckCircle2, Info, Phone, XCircle } from"lucide-react"

import { cn } from"@/lib/utils"

interface PowerCallingEntry {
 user_id: number
 name: string
 role: string
 primary_category: { id: number; slug: string; name_pl: string } | null
 verifications_week: number
 per_day: number
 workdays: number
 meets_target: boolean
 progress_pct: number
}

interface PowerCallingSectionProps {
 weekLabel: string
 requirementText: string
 entries: PowerCallingEntry[]
 targetPerDay: number
 meetsTargetCount: number
 totalCount: number
 highlightUserId?: number | null
}

const ROLE_COLOR: Record<string, string> = {
 sourcer:"bg-sky-100 text-sky-900",
 tac:"bg-teal-100 text-teal-900",
 recruiter:"bg-purple-100 text-purple-900",
}

export function PowerCallingSection({
 weekLabel,
 requirementText,
 entries,
 targetPerDay,
 meetsTargetCount,
 totalCount,
 highlightUserId,
}: PowerCallingSectionProps) {
 return (
 <div className="rounded-lg overflow-hidden border border-border shadow-sm bg-card">
 {/* Orange gradient header */}
 <div className="bg-gradient-to-r from-orange-500 via-amber-500 to-orange-600 px-4 py-3 text-white">
 <div className="flex items-center justify-between flex-wrap gap-2">
 <div className="flex items-center gap-2">
 <Phone className="h-5 w-5" />
 <div>
 <div className="font-semibold text-lg leading-tight">
 Power Calling
 </div>
 <div className="text-xs text-white/80">{weekLabel}</div>
 </div>
 </div>
 <div className="text-xs text-white/90 flex items-center gap-1.5">
 <Info className="h-3.5 w-3.5" />
 <span>{requirementText}</span>
 </div>
 <div className="text-sm font-semibold bg-card/20 px-2.5 py-1 rounded-md">
 {meetsTargetCount}/{totalCount} spełnia wymóg
 </div>
 </div>
 </div>

 {/* List */}
 <div className="divide-y divide-[hsl(var(--border-subtle))]">
 {entries.length === 0 && (
 <div className="px-4 py-6 text-center text-sm text-muted-foreground">
 Brak aktywności w tym tygodniu.
 </div>
 )}
 {entries.map((e) => {
 const isMe = highlightUserId === e.user_id
 return (
 <div
 key={e.user_id}
 className={cn("px-4 py-2.5 flex items-center gap-3 text-sm",
 isMe &&"bg-primary/10/40 font-semibold",
 )}
 >
 <span
 className={cn("inline-flex items-center justify-center h-8 w-8 rounded-full text-xs font-bold shrink-0",
 e.meets_target
 ?"bg-emerald-100 text-emerald-700"
 :"bg-amber-100 text-amber-700",
 )}
 title={e.meets_target ?"Spełnia wymóg" :"Poniżej progu"}
 >
 {e.meets_target ? (
 <CheckCircle2 className="h-4 w-4" />
 ) : (
 <XCircle className="h-4 w-4" />
 )}
 </span>
 <div className="flex-1 min-w-0">
 <div className="flex items-center gap-2 flex-wrap">
 <span className="text-foreground font-medium truncate">
 {e.name}
 </span>
 <span
 className={cn("inline-block px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide",
 ROLE_COLOR[e.role] ??"bg-slate-100 text-slate-900",
 )}
 >
 {e.role.toUpperCase()}
 </span>
 {e.primary_category && (
 <span className="text-[10px] text-muted-foreground italic truncate">
 {e.primary_category.name_pl}
 </span>
 )}
 </div>
 <div className="mt-1 flex items-center gap-2">
 <div className="flex-1 h-1.5 rounded-full bg-[hsl(var(--border-subtle))] overflow-hidden max-w-xs">
 <div
 className={cn("h-full rounded-full transition-all",
 e.meets_target
 ?"bg-emerald-500"
 :"bg-amber-500",
 )}
 style={{ width: `${e.progress_pct}%` }}
 />
 </div>
 <span className="text-[10px] text-muted-foreground">
 cel: {targetPerDay}/dzień
 </span>
 </div>
 </div>
 <div className="text-right shrink-0">
 <div
 className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold",
 e.meets_target
 ?"bg-emerald-50 text-emerald-700"
 :"bg-amber-50 text-amber-800",
 )}
 >
 {e.per_day} / dzień
 </div>
 <div className="text-[10px] text-muted-foreground mt-0.5">
 ({e.verifications_week} wer. / {e.workdays} dni)
 </div>
 </div>
 </div>
 )
 })}
 </div>
 </div>
 )
}
