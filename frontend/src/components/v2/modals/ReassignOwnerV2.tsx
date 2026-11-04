"use client";

import * as React from"react";
import { apiErrorMessage } from "@/lib/api-error";
import { useState } from"react";
import { FormProvider, useForm } from"react-hook-form";
import { useMutation, useQueryClient } from"@tanstack/react-query";
import { UserCog } from"lucide-react";
import api from"@/lib/api";
import { invalidateJobTeam } from "@/lib/job-team-cache";
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
 /** Pierwszy rekruter, który dziś pracuje nad rekrutacją; `null` = nikt. */
 currentOwner: UserBrief | null;
 onAssigned?: () => void;
}

/**
 * Puste pole trzymamy jako "", nie `null`: `RecruiterPickerField` zamienia
 * `null` na pozycję „__none__”, której przy `allowEmpty={false}` nie ma na
 * liście — pole byłoby wtedy puste, bez podpowiedzi „Wybierz osobę…”.
 */
const NO_PERSON = "";

type FormValues = {
 user_id: number | typeof NO_PERSON;
};

/**
 * Okno „Przypisz rekrutera” / „Zmień rekrutera” (`POST /api/jobs/{id}/owner`).
 * Przydziela admin, Delivery Lead i Head of Recruitment — o widoczności
 * decyduje wołający, a serwer i tak pilnuje bramki. Nowa osoba ZASTĘPUJE
 * dotychczasowego pierwszego rekrutera; kolejne osoby dopisuje „+ Dodaj
 * osobę” w panelu, a zdejmuje „×” przy osobie (z potwierdzeniem).
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
 defaultValues: { user_id: currentOwner?.id ?? NO_PERSON },
 });

 // Keep the form in sync when the sheet is opened with a different job.
 React.useEffect(() => {
 if (open) {
 methods.reset({ user_id: currentOwner?.id ?? NO_PERSON });
 setError(null);
 }
 }, [open, currentOwner?.id, methods]);

 const assignMutation = useMutation({
 mutationFn: (userId: number) =>
 api.post(`/api/jobs/${jobId}/owner`, { user_id: userId }),
 onSuccess: () => {
 // Obsadę widać na kilku ekranach naraz — odświeżamy, zamiast wkładać
 // odpowiedź do cache'u.
 invalidateJobTeam(queryClient, jobId);
 onAssigned?.();
 onOpenChange(false);
 },
 onError: (err: unknown) => {
 setError(apiErrorMessage(err,"Nie udało się przypisać rekrutera."));
 // 409 = obsada zmieniła się gdzie indziej; pokaż stan aktualny.
 invalidateJobTeam(queryClient, jobId);
 },
 });

 const onSubmit = methods.handleSubmit((values) => {
 setError(null);
 if (typeof values.user_id !== "number") {
 setError("Wybierz osobę, która ma pracować nad rekrutacją.");
 return;
 }
 if (values.user_id === currentOwner?.id) {
 // Ta sama osoba — nie ma czego zapisywać.
 onOpenChange(false);
 return;
 }
 assignMutation.mutate(values.user_id);
 });

 const busy = assignMutation.isPending;

 return (
 <Sheet open={open} onOpenChange={onOpenChange}>
 <SheetContent side="right" size="md">
 <SheetHeader>
 <div className="flex items-center gap-2">
 <UserCog className="h-4 w-4 text-primary" />
 <SheetTitle>
 {currentOwner ?"Zmień rekrutera" :"Przypisz rekrutera"}
 </SheetTitle>
 </div>
 <SheetDescription>
 Rekrutacja: <strong>{jobTitle}</strong>
 </SheetDescription>
 </SheetHeader>

 <FormProvider {...methods}>
 <form onSubmit={onSubmit}>
 <SheetBody>
 <div className="space-y-4">
 <div>
 <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">
 Obecny rekruter
 </div>
 <OwnerBadge user={currentOwner} size="md" showRole />
 </div>

 <div>
 <label
 htmlFor="user_id"
 className="block text-xs uppercase tracking-wider text-muted-foreground mb-1"
 >
 {currentOwner ?"Nowy rekruter" :"Rekruter"}
 </label>
 <RecruiterPickerField
 name="user_id"
 placeholder="Wybierz osobę…"
 allowEmpty={false}
 />
 <p className="mt-1.5 text-xs text-muted-foreground">
 {currentOwner
 ?"Wybrana osoba zastąpi obecnego rekrutera i od razu zacznie pracować nad rekrutacją."
 :"Wybrana osoba od razu zacznie pracować nad rekrutacją — bez akceptacji."}
 </p>
 </div>

 {error ? (
 <div
 role="alert"
 className="rounded-md border border-destructive/20 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground"
 >
 {error}
 </div>
 ) : null}
 </div>
 </SheetBody>

 <SheetFooter>
 <div className="flex w-full items-center justify-end gap-2">
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
 </SheetFooter>
 </form>
 </FormProvider>
 </SheetContent>
 </Sheet>
 );
}
