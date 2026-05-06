"use client";

import * as React from"react";
import { ExternalLink, RefreshCw } from"lucide-react";
import { useMutation, useQueryClient } from"@tanstack/react-query";
import api from"@/lib/api";
import { Badge } from"@/components/ui/badge";
import { Button } from"@/components/ui/button";
import { useToast } from"@/components/Toast";
import { formatDate, formatRelativeTime } from"@/lib/utils";

export type LinkedinSyncStatus =
 |"ok"
 |"not_found"
 |"error"
 |"rate_limited"
 |"disabled";

export type LinkedinChangeKind =
 |"first_snapshot"
 |"no_change"
 |"new_company"
 |"new_title_same_company";

export interface LinkedinSnapshotSummary {
 id: number;
 fetched_at: string;
 current_company: string | null;
 current_title: string | null;
 current_started_at: string | null;
 change_kind: LinkedinChangeKind;
 changed_from_previous: boolean;
}

export interface LinkedinAwareCandidate {
 id: number;
 linkedin: string | null;
 linkedin_current_company: string | null;
 linkedin_current_title: string | null;
 linkedin_current_started_at: string | null;
 linkedin_employment_changed_at: string | null;
 linkedin_synced_at: string | null;
 linkedin_sync_status: LinkedinSyncStatus;
 linkedin_sync_error: string | null;
 linkedin_snapshots?: LinkedinSnapshotSummary[] | null;
}

const STATUS_LABEL: Record<LinkedinSyncStatus, string> = {
 ok:"Zsynchronizowano",
 not_found:"Profil nie znaleziony",
 error:"Błąd synchronizacji",
 rate_limited:"Limit API — spróbujemy ponownie",
 disabled:"Synchronizacja wyłączona",
};

const STATUS_VARIANT: Record<
 LinkedinSyncStatus,"success" |"warning" |"danger" |"neutral"
> = {
 ok:"success",
 not_found:"warning",
 error:"danger",
 rate_limited:"warning",
 disabled:"neutral",
};

interface Props {
 candidate: LinkedinAwareCandidate;
}

/**
 * Detail-view section showing the most recent Proxycurl sync result +
 * detected employer-change history. The"Odśwież z LinkedIn" button calls
 * POST /api/candidates/{id}/sync-linkedin; the detail view query is
 * invalidated on success so the section refreshes in place.
 */
export function LinkedinSyncPanel({ candidate }: Props) {
 const { showSuccess, showError } = useToast();
 const queryClient = useQueryClient();

 const sync = useMutation({
 mutationFn: () =>
 api
 .post(`/api/candidates/${candidate.id}/sync-linkedin`)
 .then((r) => r.data),
 onSuccess: (data) => {
 const kind = (data?.message ??"") as string;
 if (kind ==="new_company") {
 showSuccess("Wykryto zmianę pracodawcy — profil zaktualizowany.");
 } else if (kind ==="new_title_same_company") {
 showSuccess("Wykryto zmianę stanowiska w tej samej firmie.");
 } else if (kind ==="first_snapshot") {
 showSuccess("Zapisano pierwszy snapshot profilu LinkedIn.");
 } else {
 showSuccess("Profil LinkedIn zsynchronizowany.");
 }
 queryClient.invalidateQueries({ queryKey: ["candidate", candidate.id] });
 },
 onError: (err: unknown) => {
 const message =
 err instanceof Error ? err.message :"Nie udało się odświeżyć profilu.";
 showError(message);
 },
 });

 const hasLinkedin = Boolean(candidate.linkedin);
 const status = candidate.linkedin_sync_status;
 const syncedAt = candidate.linkedin_synced_at;
 const changedAt = candidate.linkedin_employment_changed_at;
 const changeSnapshots = (candidate.linkedin_snapshots ?? []).filter(
 (s) => s.change_kind ==="new_company"
 );

 return (
 <section>
 <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground flex items-center gap-2">
 LinkedIn — stan zatrudnienia
 <Badge size="sm" variant={STATUS_VARIANT[status]}>
 {STATUS_LABEL[status]}
 </Badge>
 </h3>
 <Button
 size="sm"
 variant="outline"
 onClick={() => sync.mutate()}
 disabled={!hasLinkedin || sync.isPending}
 title={
 hasLinkedin
 ?"Odśwież profil LinkedIn przez Proxycurl"
 :"Dodaj URL LinkedIn kandydata, aby włączyć synchronizację"
 }
 >
 <RefreshCw
 className={sync.isPending ?"h-3.5 w-3.5 animate-spin" :"h-3.5 w-3.5"}
 />
 Odśwież z LinkedIn
 </Button>
 </div>

 <div className="rounded-lg border border-border bg-background/40 p-3 space-y-3">
 {!hasLinkedin && (
 <p className="text-sm text-muted-foreground">
 Kandydat nie ma wpisanego adresu profilu LinkedIn. Dodaj go w
 edycji danych podstawowych, a synchronizacja ruszy przy następnym
 cyklu.
 </p>
 )}

 {hasLinkedin && (
 <div className="flex flex-wrap gap-3 text-sm">
 <a
 href={candidate.linkedin!}
 target="_blank"
 rel="noopener noreferrer"
 className="text-primary hover:underline inline-flex items-center gap-1"
 >
 {candidate.linkedin}
 <ExternalLink className="h-3 w-3" />
 </a>
 {syncedAt && (
 <span className="text-muted-foreground">
 Ostatnia synchronizacja: {formatRelativeTime(syncedAt)}
 </span>
 )}
 </div>
 )}

 {status ==="ok" && (
 <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
 <div>
 <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
 Obecna firma (LinkedIn)
 </div>
 <div className="text-foreground mt-0.5">
 {candidate.linkedin_current_company ??"—"}
 </div>
 </div>
 <div>
 <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
 Obecne stanowisko
 </div>
 <div className="text-foreground mt-0.5">
 {candidate.linkedin_current_title ??"—"}
 </div>
 </div>
 {candidate.linkedin_current_started_at && (
 <div>
 <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
 Od
 </div>
 <div className="text-foreground mt-0.5">
 {formatDate(candidate.linkedin_current_started_at)}
 </div>
 </div>
 )}
 {changedAt && (
 <div>
 <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
 Wykryto zmianę pracodawcy
 </div>
 <div className="text-foreground mt-0.5">
 {formatRelativeTime(changedAt)}
 </div>
 </div>
 )}
 </div>
 )}

 {status ==="not_found" && (
 <p className="text-sm text-muted-foreground">
 Proxycurl nie znalazł tego profilu (prywatny / usunięty). Sprawdź
 poprawność adresu.
 </p>
 )}
 {(status ==="error" || status ==="rate_limited") &&
 candidate.linkedin_sync_error && (
 <p className="text-sm text-muted-foreground">
 Szczegóły błędu: {candidate.linkedin_sync_error}
 </p>
 )}

 {changeSnapshots.length > 0 && (
 <div>
 <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1">
 Historia zmian pracodawcy
 </div>
 <ul className="space-y-1 text-sm">
 {changeSnapshots.map((s) => (
 <li key={s.id} className="text-foreground">
 <span className="font-medium text-foreground">
 {s.current_company ??"—"}
 </span>
 {s.current_title ? ` · ${s.current_title}` :""} ·
 <span className="text-muted-foreground">
 {""}
 wykryto {formatRelativeTime(s.fetched_at)}
 </span>
 </li>
 ))}
 </ul>
 </div>
 )}
 </div>
 </section>
 );
}
