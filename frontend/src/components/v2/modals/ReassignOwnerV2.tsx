"use client";

import * as React from"react";
import { useState } from"react";
import { FormProvider, useForm } from"react-hook-form";
import { useMutation, useQueryClient } from"@tanstack/react-query";
import { Trash2, UserCog } from"lucide-react";
import api from"@/lib/api";
import { Button } from"@/components/ui/button";
import {
 Sheet,
 SheetBody,
 SheetContent,
 SheetDescription,
 SheetFooter,
 SheetHeader,
 SheetTitle,
} from"@/components/ui/sheet";
import { RecruiterPickerField } from"@/components/v2/forms/fields/RecruiterPickerField";
import { OwnerBadge } from"@/components/v2/jobs/OwnerBadge";
import type { UserBrief } from"@/components/v2/jobs/ownership-types";

interface ReassignOwnerV2Props {
 open: boolean;
 onOpenChange: (open: boolean) => void;
 jobId: number;
 jobTitle: string;
 currentOwner: UserBrief | null;
 onAssigned?: (owner: UserBrief | null) => void;
}

type FormValues = {
 user_id: number | null;
};

/**
 * Right-side sheet letting Admin/DL pick a new primary owner for a job, or
 * clear the owner (unassign). Caller is responsible for gating visibility
 * on role – the backend still enforces the guard.
 */
export function ReassignOwnerV2({
 open,
 onOpenChange,
 jobId,
 jobTitle,
 currentOwner,
 onAssigned,
}: ReassignOwnerV2Props) {
 const queryClient = useQueryClient();
 const [error, setError] = useState<string | null>(null);
 const methods = useForm<FormValues>({
 defaultValues: { user_id: currentOwner?.id ?? null },
 });

 // Keep the form in sync when the sheet is opened with a different job.
 React.useEffect(() => {
 if (open) {
 methods.reset({ user_id: currentOwner?.id ?? null });
 setError(null);
 }
 }, [open, currentOwner?.id, methods]);

 const invalidate = () => {
 queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
 queryClient.invalidateQueries({ queryKey: ["job", jobId] });
 };

 const assignMutation = useMutation({
 mutationFn: async (userId: number) => {
 const resp = await api.post(`/api/jobs/${jobId}/owner`, {
 user_id: userId,
 });
 return resp.data as { primary_owner: UserBrief | null };
 },
 onSuccess: (data) => {
 invalidate();
 onAssigned?.(data.primary_owner ?? null);
 onOpenChange(false);
 },
 onError: (err: unknown) => {
 setError(extractDetail(err) ??"Nie udało się przypisać rekrutera.");
 },
 });

 const releaseMutation = useMutation({
 mutationFn: async () => {
 const resp = await api.delete(`/api/jobs/${jobId}/owner`);
 return resp.data as { primary_owner: UserBrief | null };
 },
 onSuccess: () => {
 invalidate();
 onAssigned?.(null);
 onOpenChange(false);
 },
 onError: (err: unknown) => {
 setError(extractDetail(err) ??"Nie udało się zwolnić właściciela.");
 },
 });

 const onSubmit = methods.handleSubmit((values) => {
 setError(null);
 if (values.user_id == null) {
 releaseMutation.mutate();
 return;
 }
 assignMutation.mutate(values.user_id);
 });

 const busy = assignMutation.isPending || releaseMutation.isPending;

 return (
 <Sheet open={open} onOpenChange={onOpenChange}>
 <SheetContent side="right" size="md">
 <SheetHeader>
 <div className="flex items-center gap-2">
 <UserCog className="h-4 w-4 text-primary" />
 <SheetTitle>Zmień właściciela projektu</SheetTitle>
 </div>
 <SheetDescription>
 Oferta: <strong>{jobTitle}</strong>
 </SheetDescription>
 </SheetHeader>

 <FormProvider {...methods}>
 <form onSubmit={onSubmit}>
 <SheetBody>
 <div className="space-y-4">
 <div>
 <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">
 Obecny właściciel
 </div>
 <OwnerBadge user={currentOwner} size="md" showRole />
 </div>

 <div>
 <label
 htmlFor="user_id"
 className="block text-xs uppercase tracking-wider text-muted-foreground mb-1"
 >
 Nowy właściciel
 </label>
 <RecruiterPickerField
 name="user_id"
 placeholder="Wybierz nowego rekrutera…"
 allowEmpty
 />
 </div>

 {error ? (
 <div
 role="alert"
 className="text-sm text-primary bg-primary/10 px-3 py-2 rounded-md"
 >
 {error}
 </div>
 ) : null}
 </div>
 </SheetBody>

 <SheetFooter>
 <div className="flex w-full items-center justify-between gap-2">
 {currentOwner ? (
 <Button
 type="button"
 variant="ghost"
 size="sm"
 onClick={() => {
 setError(null);
 releaseMutation.mutate();
 }}
 disabled={busy}
 >
 <Trash2 className="h-3.5 w-3.5" /> Usuń właściciela
 </Button>
 ) : (
 <span />
 )}
 <div className="flex gap-2">
 <Button
 type="button"
 variant="ghost"
 onClick={() => onOpenChange(false)}
 disabled={busy}
 >
 Anuluj
 </Button>
 <Button type="submit" variant="primary" loading={busy}>
 Zapisz
 </Button>
 </div>
 </div>
 </SheetFooter>
 </form>
 </FormProvider>
 </SheetContent>
 </Sheet>
 );
}

function extractDetail(err: unknown): string | null {
 if (err && typeof err === "object" &&"response" in err) {
 const resp = (err as { response?: { data?: { detail?: string } } }).response;
 if (resp?.data?.detail) return resp.data.detail;
 }
 return null;
}
