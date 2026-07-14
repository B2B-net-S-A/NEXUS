"use client";

import { useEffect, useMemo, useRef, useState } from"react";
import { useVirtualizer } from"@tanstack/react-virtual";
import { Banknote, Briefcase, Clock3, MapPin, MessageSquare } from"lucide-react";
import { cn, formatRelativeTime } from"@/lib/utils";
import { Avatar, AvatarFallback } from"@/components/ui/avatar";
import { Checkbox } from"@/components/ui/checkbox";
import { Badge } from"@/components/ui/badge";
import { MatchScoreBadge } from "@/components/ds/MatchScoreBadge";
import {
 formatCandidateLocation,
 getCandidateInitials,
} from"@/components/v2/pages/candidate-list-helpers";

interface TileCandidate {
 id: number;
 name?: string;
 lastname?: string;
 position?: string;
 current_role?: string;
 location?: string;
 status?: "active" | "passive" | "blacklisted";
 availability_status?: string | null;
 last_rate?: string | null;
 last_note_preview?: string | null;
 last_rejection_reason?: string | null;
 updated_at?: string | null;
 created_at?: string | null;
 active_recruitments?: Array<{
 job_id: number;
 job_title: string;
 stage: string;
 moved_at?: string | null;
 }> | null;
 created_by_user?: { id: number; name: string } | null;
 match_stats?: {
 open_count: number;
 total_open: number;
 top_score: number;
 } | null;
 talent_pools?: Array<{ id: number; name: string }>;
}

interface CandidatesTilesProps {
 items: TileCandidate[];
 selectedIds: Set<number>;
 onToggleSelect: (id: number) => void;
 onOpenDetail: (id: number) => void;
 onQuickAssign: (candidate: { id: number; name: string }) => void;
}

const TILE_MIN_WIDTH = 300;
const TILE_GAP = 12;
const ROW_HEIGHT = 250;

const STATUS_LABELS: Record<string, string> = {
 active: "Aktywny",
 passive: "Pasywny",
 blacklisted: "Zablokowany",
};

const STATUS_VARIANTS: Record<string, "success" | "warning" | "danger"> = {
 active: "success",
 passive: "warning",
 blacklisted: "danger",
};

const AVAILABILITY_LABELS: Record<string, string> = {
 actively_looking: "Aktywnie szuka",
 open_to_offers: "Otwarty na oferty",
 not_looking: "Nie szuka",
 unknown: "Dostępność nieznana",
};

export function CandidatesTiles({
 items,
 selectedIds,
 onToggleSelect,
 onOpenDetail,
 onQuickAssign,
}: CandidatesTilesProps) {
 const parentRef = useRef<HTMLDivElement>(null);
 const [lanes, setLanes] = useState(3);

 useEffect(() => {
 const node = parentRef.current;
 if (!node) return;
 const update = () => {
 const width = node.clientWidth;
 const computed = Math.max(
 1,
 Math.floor((width + TILE_GAP) / (TILE_MIN_WIDTH + TILE_GAP))
 );
 setLanes(computed);
 };
 update();
 const ro = new ResizeObserver(update);
 ro.observe(node);
 return () => ro.disconnect();
 }, []);

 const rows = useMemo(() => {
 const out: TileCandidate[][] = [];
 for (let i = 0; i < items.length; i += lanes) {
 out.push(items.slice(i, i + lanes));
 }
 return out;
 }, [items, lanes]);

 const virtualizer = useVirtualizer({
 count: rows.length,
 getScrollElement: () => parentRef.current,
 estimateSize: () => ROW_HEIGHT,
 overscan: 4,
 });

 return (
 <div
 ref={parentRef}
 style={{ height: "calc(100vh - 340px)", minHeight: 360 }}
 className="overflow-auto p-3"
 >
 <div
 style={{
 height: `${virtualizer.getTotalSize()}px`,
 position: "relative",
 width: "100%",
 }}
 >
 {virtualizer.getVirtualItems().map((virtualRow) => {
 const row = rows[virtualRow.index];
 return (
 <div
 key={virtualRow.index}
 style={{
 position: "absolute",
 top: 0,
 left: 0,
 width: "100%",
 height: `${virtualRow.size}px`,
 transform: `translateY(${virtualRow.start}px)`,
 display: "grid",
 gridTemplateColumns: `repeat(${lanes}, minmax(0, 1fr))`,
 gap: `${TILE_GAP}px`,
 paddingBottom: `${TILE_GAP}px`,
 }}
 >
 {row.map((candidate) => {
 const fullName =
 `${candidate.name ??""} ${candidate.lastname ??""}`.trim() ||"Kandydat";
 const initials = getCandidateInitials(candidate) || "?";
 const position =
 candidate.position ?? candidate.current_role ??"";
 const isSelected = selectedIds.has(candidate.id);
 const topScore = candidate.match_stats?.top_score ?? 0;
 const showMatch = (candidate.match_stats?.open_count ?? 0) > 0;
 const activeRecruitment = candidate.active_recruitments?.find(
 (recruitment) =>
 !["rejected", "withdrawn", "hired"].includes(recruitment.stage),
 );
 const lastActivity =
 candidate.last_note_preview ?? candidate.last_rejection_reason ?? null;
 const updatedAt = candidate.updated_at ?? candidate.created_at ?? null;
 return (
 <div
 key={candidate.id}
 onClick={() => onOpenDetail(candidate.id)}
 className={cn("group relative flex cursor-pointer flex-col gap-3 rounded-lg border bg-card p-4 text-left transition-colors",
 isSelected
 ?"border-primary bg-primary/10"
 :"border-border hover:border-primary/60 hover:bg-accent/40"
 )}
 >
 <div className="absolute left-3 top-3" onClick={(event) => event.stopPropagation()}>
 <Checkbox
 checked={isSelected}
 onCheckedChange={() => onToggleSelect(candidate.id)}
 aria-label={`Zaznacz ${fullName}`}
 />
 </div>
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 onQuickAssign({ id: candidate.id, name: fullName });
 }}
 title="Przypisz do oferty"
 aria-label={`Przypisz ${fullName} do rekrutacji`}
 className="absolute right-3 top-3 flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
 >
 <Briefcase className="h-3.5 w-3.5" />
 </button>
 <button
 type="button"
 onClick={() => onOpenDetail(candidate.id)}
 className="flex min-w-0 w-full items-start gap-3 pl-7 pr-8 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
 >
 <Avatar size="md">
 <AvatarFallback>{initials}</AvatarFallback>
 </Avatar>
 <div className="min-w-0 flex-1">
 <div className="truncate text-sm font-semibold text-foreground hover:text-primary" title={fullName}>
 {fullName}
 </div>
 {position && (
 <div className="mt-0.5 truncate text-xs text-muted-foreground">
 {position}
 </div>
 )}
 {(() => {
 const loc = formatCandidateLocation(candidate.location);
 return loc ? (
 <div className="mt-1 flex truncate text-[11px] text-muted-foreground items-center gap-1">
 <MapPin className="h-3 w-3" />
 {loc}
 </div>
 ) : null;
 })()}
 </div>
 {candidate.status && (
 <Badge
 size="sm"
 variant={STATUS_VARIANTS[candidate.status] ?? "neutral"}
 className="mt-1.5"
 >
 {STATUS_LABELS[candidate.status] ?? candidate.status}
 </Badge>
 )}
 </button>
 <div className="grid grid-cols-2 gap-2 text-xs">
 <div className="min-w-0 rounded-md bg-muted/60 px-2.5 py-2">
 <span className="block text-[10px] uppercase tracking-wide text-muted-foreground">Dostępność</span>
 <span className="mt-0.5 block truncate text-foreground">
 {candidate.availability_status
 ? AVAILABILITY_LABELS[candidate.availability_status] ?? candidate.availability_status
 : "Nieznana"}
 </span>
 </div>
 <div className="min-w-0 rounded-md bg-muted/60 px-2.5 py-2">
 <span className="block text-[10px] uppercase tracking-wide text-muted-foreground">Stawka / match</span>
 <span className="mt-0.5 flex items-center gap-1 truncate text-foreground">
 {candidate.last_rate ? <Banknote className="h-3 w-3 shrink-0" /> : null}
 {candidate.last_rate ?? (showMatch ? `${Math.round(topScore)}/100` : "Brak danych")}
 </span>
 </div>
 </div>
 {activeRecruitment && (
 <div className="flex min-w-0 items-center gap-2 text-xs text-foreground">
 <Briefcase className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
 <span className="truncate" title={activeRecruitment.job_title}>
 {activeRecruitment.job_title} · {activeRecruitment.stage}
 </span>
 </div>
 )}
 <div className="mt-auto flex min-w-0 items-center justify-between gap-2 border-t border-border pt-2 text-[11px] text-muted-foreground">
 <span className="flex min-w-0 items-center gap-1.5 truncate" title={lastActivity ?? undefined}>
 {lastActivity ? (
 <MessageSquare className="h-3 w-3 shrink-0" />
 ) : (
 <Clock3 className="h-3 w-3 shrink-0" />
 )}
 <span className="truncate">{lastActivity ?? "Brak ostatniej aktywności"}</span>
 </span>
 {showMatch && (
 <MatchScoreBadge
 score={topScore}
 size="sm"
 className="shrink-0 px-1.5 py-0 text-[10px]"
 title={`Match: ${Math.round(topScore)}% — ${candidate.match_stats?.open_count ?? 0}/${candidate.match_stats?.total_open ?? 0} otwartych ofert`}
 />
 )}
 {!showMatch && updatedAt && (
 <span className="shrink-0">{formatRelativeTime(updatedAt)}</span>
 )}
 </div>
 </div>
 );
 })}
 </div>
 );
 })}
 </div>
 </div>
 );
}
