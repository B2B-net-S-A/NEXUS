"use client";

import * as React from"react";
import { AlertTriangle, ShieldCheck, ShieldAlert } from"lucide-react";

import { Badge } from"@/components/ui/badge";
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from"@/components/ui/tooltip";
import { cn } from"@/lib/utils";
import type {
 CandidateRiskProfile,
 RiskEvent,
 RiskLevel,
} from"@/types/candidate-risk";

interface RiskBadgeProps {
 profile: CandidateRiskProfile;
 /**
 * Hide entirely when level ==="low". Set this for list/table views to
 * reduce visual noise — only flag medium/high candidates there.
 */
 hideLow?: boolean;
 /**
 * Hide for medium too. Use for high-density list views where only the worst
 * cases should stand out.
 */
 highOnly?: boolean;
 className?: string;
}

const LEVEL_COPY: Record<RiskLevel, { label: string; variant: "success" |"warning" |"danger" }> = {
 low: { label: "Niskie ryzyko", variant: "success" },
 medium: { label: "Średnie ryzyko", variant: "warning" },
 high: { label: "Wysokie ryzyko", variant: "danger" },
};

const CATEGORY_LABEL: Record<string, string> = {
 early: "Wycofania na początku procesu",
 interview: "Wycofania po interview",
 post_accept: "Wycofania po akceptacji oferty",
};

const REASON_LABEL: Record<string, string> = {
 accepted_other_offer: "Zaakceptował inną ofertę",
 counter_offer: "Counter-offer obecnego pracodawcy",
 personal_reasons: "Powody osobiste",
 lost_interest: "Stracił zainteresowanie",
 salary_mismatch: "Niedopasowanie wynagrodzenia",
 process_too_long: "Proces za długi",
 legacy_unknown: "Nieznany (legacy)",
};

function formatDate(iso: string): string {
 const d = new Date(iso);
 if (Number.isNaN(d.getTime())) return iso;
 return d.toLocaleDateString("pl-PL", {
 day: "2-digit",
 month: "2-digit",
 year: "numeric",
 });
}

function reasonLabel(reason: string): string {
 return REASON_LABEL[reason] ?? reason;
}

export function RiskBadge({
 profile,
 hideLow = false,
 highOnly = false,
 className,
}: RiskBadgeProps) {
 if (highOnly && profile.level !=="high") return null;
 if (hideLow && profile.level ==="low") return null;

 const { label, variant } = LEVEL_COPY[profile.level];
 const Icon =
 profile.level ==="high"
 ? ShieldAlert
 : profile.level ==="medium"
 ? AlertTriangle
 : ShieldCheck;

 const totalDropouts =
 profile.breakdown.early +
 profile.breakdown.interview +
 profile.breakdown.post_accept;

 return (
 <TooltipProvider delayDuration={200}>
 <Tooltip>
 <TooltipTrigger asChild>
 <span
 className={cn("inline-flex", className)}
 data-testid="risk-badge"
 >
 <Badge variant={variant} size="md">
 <Icon className="h-3 w-3" />
 {label}
 {totalDropouts > 0 && (
 <span className="ml-1 opacity-80">· {totalDropouts}</span>
 )}
 </Badge>
 </span>
 </TooltipTrigger>
 <TooltipContent side="bottom" align="start" className="max-w-xs p-0">
 <RiskTooltipBody profile={profile} />
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 );
}

function RiskTooltipBody({ profile }: { profile: CandidateRiskProfile }) {
 const total =
 profile.breakdown.early +
 profile.breakdown.interview +
 profile.breakdown.post_accept;

 return (
 <div className="space-y-2 p-3 text-xs">
 <div className="font-semibold text-foreground">
 Risk score: {profile.score}
 </div>

 {total === 0 ? (
 <div className="text-muted-foreground">
 Brak wycofań w ostatnich 24 miesiącach.
 </div>
 ) : (
 <>
 <div className="text-muted-foreground">
 {total} wycofań w 24mc:
 </div>
 <ul className="space-y-0.5">
 {profile.breakdown.post_accept > 0 && (
 <li>
 <strong>{profile.breakdown.post_accept}×</strong>{""}
 {CATEGORY_LABEL.post_accept}{""}
 <span className="text-muted-foreground">
 (10 pt każda)
 </span>
 </li>
 )}
 {profile.breakdown.interview > 0 && (
 <li>
 <strong>{profile.breakdown.interview}×</strong>{""}
 {CATEGORY_LABEL.interview}{""}
 <span className="text-muted-foreground">
 (3 pt każda)
 </span>
 </li>
 )}
 {profile.breakdown.early > 0 && (
 <li>
 <strong>{profile.breakdown.early}×</strong>{""}
 {CATEGORY_LABEL.early}{""}
 <span className="text-muted-foreground">
 (1 pt każda)
 </span>
 </li>
 )}
 </ul>
 </>
 )}

 {profile.recent_events.length > 0 && (
 <>
 <div className="pt-1 border-t border-border text-muted-foreground">
 Ostatnie wycofania:
 </div>
 <ul className="space-y-1">
 {profile.recent_events.slice(0, 5).map((e: RiskEvent, idx) => (
 <li key={idx} className="leading-snug">
 <span className="text-muted-foreground">
 {formatDate(e.moved_at)}
 </span>{""}
 · {e.job_title ?? `Job #${e.job_id}`} · {reasonLabel(e.reason)}
 </li>
 ))}
 </ul>
 </>
 )}
 </div>
 );
}

/**
 * Convenience hook — fetches risk profile via React Query.
 * Caller passes their own `useQuery` typing to avoid coupling here.
 */
export const RISK_QUERY_KEY = (candidateId: number | string | undefined) =>
 ["candidate-risk", candidateId] as const;
