"use client";

import * as React from"react";
import { useState } from"react";
import { useMutation, useQuery, useQueryClient } from"@tanstack/react-query";
import { Plus, UserCog, UserPlus, X } from"lucide-react";
import api from"@/lib/api";
import { Button } from"@/components/ui/button";
import {
 Popover,
 PopoverContent,
 PopoverTrigger,
} from"@/components/ui/popover";
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from"@/components/ui/select";
import { useAuthStore, ROLE_LABELS, hasMinRole, hasRole } from"@/store/auth";
import { OwnerBadge } from"./OwnerBadge";
import { ReassignOwnerV2 } from"@/components/v2/modals/ReassignOwnerV2";
import type { UserBrief } from"./ownership-types";

interface JobOwnershipPanelProps {
 jobId: number;
 jobTitle: string;
 primaryOwner: UserBrief | null;
 collaborators: UserBrief[];
}

/**
 * Header panel for /jobs/[id] showing the primary owner + collaborators, with
 * inline Claim / Reassign / Add-collaborator actions gated by the current
 * user's role. Backend remains authoritative on all guards — UI only hides
 * disallowed actions.
 */
export function JobOwnershipPanel({
 jobId,
 jobTitle,
 primaryOwner,
 collaborators,
}: JobOwnershipPanelProps) {
 const queryClient = useQueryClient();
 const currentUser = useAuthStore((s) => s.user);
 const [reassignOpen, setReassignOpen] = useState(false);
 const [addOpen, setAddOpen] = useState(false);
 const [error, setError] = useState<string | null>(null);

 const canReassign = hasMinRole(currentUser, "delivery_lead");
 const canClaim =
 primaryOwner === null && !!currentUser && !hasRole(currentUser, "user");
 const isPrimary = !!currentUser && primaryOwner?.id === currentUser.id;
 const canManageCollaborators = canReassign || isPrimary;

 const invalidate = () => {
 queryClient.invalidateQueries({ queryKey: ["job", jobId] });
 queryClient.invalidateQueries({ queryKey: ["job", String(jobId)] });
 queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
 queryClient.invalidateQueries({ queryKey: ["dashboard","my-jobs"] });
 };

 const claimMutation = useMutation({
 mutationFn: () => api.post(`/api/jobs/${jobId}/claim`),
 onSuccess: () => {
 setError(null);
 invalidate();
 },
 onError: (err: unknown) => setError(extractDetail(err) ??"Nie udało się przejąć projektu."),
 });

 const removeCollaboratorMutation = useMutation({
 mutationFn: (userId: number) =>
 api.delete(`/api/jobs/${jobId}/collaborators/${userId}`),
 onSuccess: invalidate,
 });

 const { data: directory } = useQuery<UserBrief[]>({
 queryKey: ["users","directory","ownership"],
 queryFn: () => api.get("/api/users").then((r) => r.data as UserBrief[]),
 staleTime: 5 * 60 * 1000,
 enabled: canManageCollaborators,
 });

 return (
 <div className="flex items-start justify-between gap-3 flex-wrap">
 <div className="min-w-0 flex-1">
 <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">
 Właściciel projektu
 </div>
 <div className="flex items-center gap-2 flex-wrap">
 <OwnerBadge user={primaryOwner} size="md" showRole />
 {canReassign ? (
 <Button
 type="button"
 variant="ghost"
 size="sm"
 onClick={() => setReassignOpen(true)}
 >
 <UserCog className="h-3.5 w-3.5" /> Zmień
 </Button>
 ) : null}
 {canClaim ? (
 <Button
 type="button"
 variant="primary"
 size="sm"
 onClick={() => claimMutation.mutate()}
 loading={claimMutation.isPending}
 >
 <UserPlus className="h-3.5 w-3.5" /> Claim this job
 </Button>
 ) : null}
 </div>

 <div className="mt-3">
 <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">
 Współpracownicy ({collaborators.length})
 </div>
 <div className="flex items-center gap-1.5 flex-wrap">
 {collaborators.length === 0 ? (
 <span className="text-xs text-muted-foreground">Brak.</span>
 ) : (
 collaborators.map((c) => (
 <span
 key={c.id}
 className="inline-flex items-center gap-1 pl-1 pr-2 h-6 rounded-full bg-card border border-border text-[11px]"
 title={`${c.name} · ${ROLE_LABELS[c.role]}`}
 >
 <OwnerBadge user={c} size="sm" />
 {canManageCollaborators ? (
 <button
 type="button"
 aria-label={`Usuń ${c.name} ze współpracowników`}
 className="text-muted-foreground hover:text-primary"
 onClick={() => removeCollaboratorMutation.mutate(c.id)}
 >
 <X className="h-3 w-3" />
 </button>
 ) : null}
 </span>
 ))
 )}
 {canManageCollaborators ? (
 <Popover open={addOpen} onOpenChange={setAddOpen}>
 <PopoverTrigger asChild>
 <Button type="button" variant="ghost" size="sm">
 <Plus className="h-3.5 w-3.5" /> Dodaj
 </Button>
 </PopoverTrigger>
 <PopoverContent className="w-72 p-3">
 <AddCollaboratorInner
 jobId={jobId}
 existingIds={
 new Set([
 ...collaborators.map((c) => c.id),
 primaryOwner?.id ?? -1,
 ])
 }
 directory={directory ?? []}
 onDone={() => {
 setAddOpen(false);
 invalidate();
 }}
 />
 </PopoverContent>
 </Popover>
 ) : null}
 </div>
 </div>

 {error ? (
 <div className="mt-2 text-xs text-primary">{error}</div>
 ) : null}
 </div>

 <ReassignOwnerV2
 open={reassignOpen}
 onOpenChange={setReassignOpen}
 jobId={jobId}
 jobTitle={jobTitle}
 currentOwner={primaryOwner}
 onAssigned={() => invalidate()}
 />
 </div>
 );
}

interface AddCollaboratorInnerProps {
 jobId: number;
 existingIds: Set<number>;
 directory: UserBrief[];
 onDone: () => void;
}

function AddCollaboratorInner({
 jobId,
 existingIds,
 directory,
 onDone,
}: AddCollaboratorInnerProps) {
 const [selected, setSelected] = useState<number | null>(null);
 const [error, setError] = useState<string | null>(null);

 const addMutation = useMutation({
 mutationFn: (userId: number) =>
 api.post(`/api/jobs/${jobId}/collaborators`, { user_id: userId }),
 onSuccess: () => {
 setError(null);
 onDone();
 },
 onError: (err: unknown) =>
 setError(extractDetail(err) ??"Nie udało się dodać współpracownika."),
 });

 const options = directory.filter((u) => !existingIds.has(u.id));

 return (
 <div className="space-y-2">
 <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
 Dodaj współpracownika
 </div>
 <Select
 value={selected != null ? String(selected) : ""}
 onValueChange={(v) => setSelected(v ? Number(v) : null)}
 >
 <SelectTrigger>
 <SelectValue placeholder="Wybierz osobę…" />
 </SelectTrigger>
 <SelectContent>
 {options.length === 0 ? (
 <SelectItem value="__none__" disabled>
 Wszyscy już dodani
 </SelectItem>
 ) : (
 options.map((u) => (
 <SelectItem key={u.id} value={String(u.id)}>
 {u.name}
 <span className="ml-2 text-xs text-muted-foreground">
 {ROLE_LABELS[u.role]}
 </span>
 </SelectItem>
 ))
 )}
 </SelectContent>
 </Select>
 {error ? (
 <div className="text-xs text-primary">{error}</div>
 ) : null}
 <div className="flex justify-end gap-2 pt-1">
 <Button
 type="button"
 variant="ghost"
 size="sm"
 onClick={onDone}
 >
 Anuluj
 </Button>
 <Button
 type="button"
 variant="primary"
 size="sm"
 disabled={selected == null}
 loading={addMutation.isPending}
 onClick={() => selected != null && addMutation.mutate(selected)}
 >
 Dodaj
 </Button>
 </div>
 </div>
 );
}

function extractDetail(err: unknown): string | null {
 if (err && typeof err === "object" &&"response" in err) {
 const resp = (err as { response?: { data?: { detail?: string } } }).response;
 if (resp?.data?.detail) return resp.data.detail;
 }
 return null;
}
