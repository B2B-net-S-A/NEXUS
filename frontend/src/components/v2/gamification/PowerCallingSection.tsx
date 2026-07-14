"use client"

import { CheckCircle2, Info, Phone, XCircle } from"lucide-react"

import { cn } from"@/lib/utils"

interface PowerCallingEntry {
 user_id: number
 name: string
 role: string
 primary_category: { id: number; slug: string; name_pl: string } | null
 calls_week: number | null
 calls_per_day: number | null
 verifications_week: number
 verifications_per_day: number
 workdays: number
 meets_call_target: boolean | null
 meets_verification_target: boolean
 progress_pct: number | null
}

interface PowerCallingSectionProps {
 weekLabel: string
 requirementText: string
 callsAvailable: boolean
 entries: PowerCallingEntry[]
 targetPerDay: number
 verificationTargetPerDay: number
 meetsTargetCount: number | null
 totalCount: number
 highlightUserId?: number | null
}

export function PowerCallingSection({
 weekLabel,
 requirementText,
 callsAvailable,
 entries,
 targetPerDay,
 verificationTargetPerDay,
 meetsTargetCount,
 totalCount,
 highlightUserId,
}: PowerCallingSectionProps) {
 return (
 <div className="rounded-lg overflow-hidden border border-border shadow-sm bg-card">
 <div className="bg-primary px-4 py-3 text-primary-foreground">
 <div className="flex items-center justify-between flex-wrap gap-2">
 <div className="flex items-center gap-2">
 <Phone className="h-5 w-5" />
 <div>
 <div className="font-semibold text-lg leading-tight">
 Power Calling
 </div>
 <div className="text-xs text-primary-foreground/80">{weekLabel}</div>
 </div>
 </div>
 <div className="text-xs text-primary-foreground/90 flex items-center gap-1.5">
 <Info className="h-3.5 w-3.5" />
 <span>{requirementText}</span>
 </div>
 <div className="text-sm font-semibold bg-primary-foreground/15 px-2.5 py-1 rounded-md">
 {callsAvailable
 ? `${meetsTargetCount}/${totalCount} spełnia cel rozmów`
 : "CloudTalk niedostępny"}
 </div>
 </div>
 </div>

 {/* List */}
 {!callsAvailable && (
 <div className="border-b border-border bg-muted px-4 py-3 text-sm text-muted-foreground">
 Dane rozmów są niedostępne, dopóki integracja CloudTalk nie zostanie w pełni skonfigurowana. Weryfikacje są nadal liczone osobno z ATS.
 </div>
 )}
 <div className="divide-y divide-border">
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
 isMe &&"bg-primary/10 font-semibold",
 )}
 >
 <span
 className={cn("inline-flex items-center justify-center h-8 w-8 rounded-full text-xs font-bold shrink-0",
 e.meets_call_target === true
 ?"bg-primary/15 text-primary"
 :"bg-muted text-muted-foreground",
 )}
 title={
 e.meets_call_target === null
 ? "Dane rozmów niedostępne"
 : e.meets_call_target
 ? "Spełnia cel rozmów"
 : "Poniżej celu rozmów"
 }
 >
 {e.meets_call_target === true ? (
 <CheckCircle2 className="h-4 w-4" />
 ) : e.meets_call_target === null ? (
 <Info className="h-4 w-4" />
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
 "bg-muted text-muted-foreground",
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
 {callsAvailable && (
 <div className="mt-1 flex items-center gap-2">
 <div className="flex-1 h-1.5 rounded-full bg-[hsl(var(--border))] overflow-hidden max-w-xs">
 <div
 className={cn("h-full rounded-full transition-all",
 e.meets_call_target ?"bg-primary" :"bg-muted-foreground",
 )}
 style={{ width: `${e.progress_pct ?? 0}%` }}
 />
 </div>
 <span className="text-[10px] text-muted-foreground">
 cel: {targetPerDay}/dzień
 </span>
 </div>
 )}
 </div>
 <div className="text-right shrink-0">
 <div
 className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold",
 e.meets_call_target === true
 ?"bg-primary/10 text-primary"
 :"bg-muted text-muted-foreground",
 )}
 >
 {e.calls_per_day === null ? "— rozm. / dzień" : `${e.calls_per_day} rozm. / dzień`}
 </div>
 <div className="text-[10px] text-muted-foreground mt-0.5">
 {e.calls_week === null ? "dane niedostępne" : `${e.calls_week} rozm. / ${e.workdays} dni`}
 </div>
 <div
 className={cn("mt-1 text-[10px] font-medium",
 e.meets_verification_target ?"text-primary" :"text-muted-foreground",
 )}
 >
 {e.verifications_per_day} wer./dzień · cel {verificationTargetPerDay} · {e.verifications_week} w tyg.
 </div>
 </div>
 </div>
 )
 })}
 </div>
 </div>
 )
}
