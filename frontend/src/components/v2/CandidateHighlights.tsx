"use client";

import { AlertTriangle, Circle, RefreshCw, Sparkles } from"lucide-react";
import { Badge } from"@/components/ui/badge";
import { cn } from"@/lib/utils";

export type EmploymentState =
 |"employed_at_client"
 |"on_bench"
 |"external"
 |"unknown";

export type AvailabilityStatus =
 |"actively_looking"
 |"open_to_offers"
 |"not_looking"
 |"unknown";

export type CandidateStatus ="active" |"passive" |"blacklisted";

export interface EmploymentInfo {
 state: EmploymentState;
 client_id?: number | null;
 client_name?: string | null;
 contract_end_date?: string | null;
 source?:"contract" |"conflict" |"none";
}

export interface HighlightableCandidate {
 status?: CandidateStatus;
 availability_status?: AvailabilityStatus;
 employment?: EmploymentInfo;
 /** ISO datetime of last detected employer change — populated by Proxycurl sync. */
 linkedin_employment_changed_at?: string | null;
 /** Engagement openness flags (Phase „Otwartość na dodatkowe projekty"). */
 open_to_side_projects?: boolean;
 open_to_sales_support?: boolean;
 open_to_expert_consult?: boolean;
}

/**
 * Render"Nowa praca X" badge when a LinkedIn sync detected a new employer in
 * the last 90 days. Color intensity follows recency (warning within a month,
 * info within two, neutral within three).
 */
function formatLinkedinJobChange(days: number): {
 label: string;
 variant: "warning" |"info" |"neutral";
} {
 const variant: "warning" |"info" |"neutral" =
 days < 30 ?"warning" : days < 60 ?"info" :"neutral";
 let label: string;
 if (days < 7) {
 label ="Nowa praca (ten tydzień)";
 } else if (days < 30) {
 const weeks = Math.max(1, Math.round(days / 7));
 label = `Nowa praca ${weeks} tyg`;
 } else {
 const months = Math.max(1, Math.round(days / 30));
 label = `Nowa praca ${months} mies`;
 }
 return { label, variant };
}

interface Props {
 candidate: HighlightableCandidate;
 /**
 * compact — only tier 1/2 highlights (for dense lists).
 * full — every applicable tier plus"not_looking" pill (for profile cards).
 */
 variant?:"compact" |"full";
 className?: string;
}

/**
 * Central renderer for consultant status highlights.
 *
 * Covers the 6 scenarios from the brief by combining two orthogonal axes
 * (employment / availability). Tier 1 badges are the"must-see" alerts that
 * should make the recruiter pause before acting.
 */
export function CandidateHighlights({
 candidate,
 variant ="compact",
 className,
}: Props) {
 const { status, availability_status, employment } = candidate;
 const employmentState = employment?.state ??"unknown";
 const isEmployedAtClient = employmentState === "employed_at_client";
 const isBlacklisted = status === "blacklisted";

 // LinkedIn job-change badge: show for changes detected within the last 90d.
 let linkedinJobChange: { label: string; variant: "warning" |"info" |"neutral" } | null = null;
 if (candidate.linkedin_employment_changed_at) {
 const changedAt = new Date(candidate.linkedin_employment_changed_at);
 if (!Number.isNaN(changedAt.getTime())) {
 const days = Math.floor(
 (Date.now() - changedAt.getTime()) / (1000 * 60 * 60 * 24)
 );
 if (days >= 0 && days < 90) {
 linkedinJobChange = formatLinkedinJobChange(days);
 }
 }
 }

 return (
 <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
 {/* ── Tier 1: must-see alerts ─────────────────────────────────── */}
 {isEmployedAtClient && (
 <Badge
 variant="alert"
 size="sm"
 uppercase
 title={
 employment?.source === "conflict"
 ?"Oznaczone ręcznie jako zatrudniony u tego klienta"
 :"Aktywny kontrakt z naszym klientem"
 }
 >
 <AlertTriangle className="h-3 w-3" />
 U KLIENTA{employment?.client_name ? `: ${employment.client_name}` :""}
 </Badge>
 )}

 {isBlacklisted && (
 <Badge variant="alert-dark" size="sm" uppercase>
 Black list
 </Badge>
 )}

 {/* ── Tier 2: employment state (informational) ─────────────────── */}
 {employmentState === "on_bench" && (
 <Badge variant="success" size="sm">
 Bez projektu
 </Badge>
 )}
 {variant === "full" && employmentState === "external" && (
 <Badge variant="soft" size="sm">
 Zewnętrzny
 </Badge>
 )}

 {/* ── Tier 2.5: LinkedIn-detected employer change ───────────────── */}
 {linkedinJobChange && (
 <Badge
 variant={linkedinJobChange.variant}
 size="sm"
 title="Wykryto zmianę pracodawcy na podstawie profilu LinkedIn"
 >
 <RefreshCw className="h-3 w-3" />
 {linkedinJobChange.label}
 </Badge>
 )}

 {/* ── Tier 2.6: otwartość na dodatkowe zaangażowanie ─────────────── */}
 {(() => {
 const flags = [
 candidate.open_to_side_projects &&"Side-projekty",
 candidate.open_to_sales_support &&"Wsparcie sprzedaży",
 candidate.open_to_expert_consult &&"Konsultacje eksperckie",
 ].filter(Boolean) as string[];
 if (!flags.length) return null;
 return (
 <Badge
 variant="info"
 size="sm"
 title={`Zadeklarowana otwartość: ${flags.join(",")}`}
 >
 <Sparkles className="h-3 w-3" />
 Otwarty na extra
 </Badge>
 );
 })()}

 {/* ── Tier 3: availability (postawa) ───────────────────────────── */}
 {availability_status === "actively_looking" && (
 <Badge variant="success" size="sm">
 <Circle className="h-1.5 w-1.5 fill-current" />
 {isEmployedAtClient ?"Rozgląda się" :"Aktywnie szuka"}
 </Badge>
 )}
 {availability_status === "open_to_offers" && (
 <Badge variant="info" size="sm">
 {isEmployedAtClient ?"Otwarty na dodatkowe" :"Otwarty na projekty"}
 </Badge>
 )}
 {variant === "full" && availability_status === "not_looking" && (
 <Badge variant="neutral" size="sm">
 Nie szuka
 </Badge>
 )}
 </div>
 );
}

/** Polish label for a raw availability value. Used by filter dropdowns + edit form. */
export const AVAILABILITY_LABELS: Record<AvailabilityStatus, string> = {
 actively_looking: "Aktywnie szuka",
 open_to_offers: "Otwarty na projekty",
 not_looking: "Nie szuka",
 unknown: "Nie wiemy",
};

export const AVAILABILITY_OPTIONS: { value: AvailabilityStatus; label: string }[] =
 [
 { value: "actively_looking", label: "Aktywnie szuka" },
 { value: "open_to_offers", label: "Otwarty na projekty" },
 { value: "not_looking", label: "Nie szuka" },
 { value: "unknown", label: "Nie wiemy" },
 ];

export const EMPLOYMENT_FILTER_OPTIONS: {
 value: "all" |"at_client" |"available";
 label: string;
}[] = [
 { value: "all", label: "Dowolne" },
 { value: "at_client", label: "U naszego klienta" },
 { value: "available", label: "Dostępni (bez projektu)" },
];

/**
 * Full-width banner shown on top of a consultant profile when they're
 * currently employed at one of our clients. Intentionally loud — this is the
 *"do not send profile to the wrong client" guardrail.
 */
export function AtOurClientBanner({
 employment,
 className,
}: {
 employment: EmploymentInfo;
 className?: string;
}) {
 if (employment.state !== "employed_at_client") return null;
 const endText = employment.contract_end_date
 ? `Kontrakt do: ${employment.contract_end_date}`
 :"Ręcznie oznaczony jako zatrudniony u klienta";
 const clientLabel = employment.client_name
 ? `: ${employment.client_name.toUpperCase()}`
 :"";
 return (
 <div
 role="alert"
 className={cn("rounded-lg border border-[hsl(var(--primary))] bg-primary text-white shadow-sm","animate-pulse-subtle px-4 py-3",
 className
 )}
 >
 <div className="flex items-start gap-3">
 <AlertTriangle className="h-5 w-5 mt-0.5 shrink-0" />
 <div className="flex-1 min-w-0">
 <p className="text-xs font-bold uppercase tracking-[0.12em]">
 Konsultant zatrudniony u naszego klienta{clientLabel}
 </p>
 <p className="text-sm text-white/90 mt-1">
 {endText} · Nie wysyłaj profilu bez konsultacji z delivery.
 </p>
 </div>
 </div>
 </div>
 );
}
