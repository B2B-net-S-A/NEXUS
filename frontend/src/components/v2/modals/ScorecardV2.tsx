"use client";

import * as React from"react";
import { useEffect } from"react";
import { useForm } from"react-hook-form";
import { useMutation, useQuery, useQueryClient } from"@tanstack/react-query";
import { Save, Sparkles } from"lucide-react";
import {
 phase3Api,
 type ScorecardAnswer,
 type ScorecardQuestion,
 type ScorecardSchema,
} from"@/lib/api";
import {
 Sheet,
 SheetBody,
 SheetContent,
 SheetDescription,
 SheetFooter,
 SheetHeader,
 SheetTitle,
} from"@/components/ui/sheet";
import { Button } from"@/components/ui/button";
import { Checkbox } from"@/components/ui/checkbox";
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from"@/components/ui/select";
import { Form, FormField, TextareaField } from"@/components/v2/forms";
import { RatingField } from"@/components/v2/forms/fields/RatingField";
import { FormProvider } from"react-hook-form";

interface Props {
 open: boolean;
 onOpenChange: (open: boolean) => void;
 candidateStageId: number;
 stageId: number;
 stageDefId: number;
 stageName: string;
 onSaved?: () => void;
}

interface FormValues {
 answers: Record<string, unknown>;
 overall_rating: number;
 notes: string;
}

export function ScorecardV2({
 open,
 onOpenChange,
 candidateStageId,
 stageId,
 stageDefId,
 stageName,
 onSaved,
}: Props) {
 const queryClient = useQueryClient();

 const { data: schemaRes, isLoading } = useQuery({
 queryKey: ["scorecard-schema-v2", stageDefId],
 queryFn: () => phase3Api.getScorecardSchema(stageDefId).then((r) => r.data),
 enabled: open,
 });

 const schema: ScorecardSchema = schemaRes?.schema ?? { questions: [] };

 const methods = useForm<FormValues>({
 defaultValues: {
 answers: {},
 overall_rating: 0,
 notes: "",
 },
 });

 // Reset form when schema arrives
 useEffect(() => {
 if (!schema.questions.length) return;
 const defaults: Record<string, unknown> = {};
 for (const q of schema.questions) {
 if (q.type ==="rating") defaults[q.id] = 0;
 else if (q.type ==="checkbox") defaults[q.id] = false;
 else defaults[q.id] ="";
 }
 methods.reset({ answers: defaults, overall_rating: 0, notes: "" });
 }, [schema.questions.length]); // eslint-disable-line react-hooks/exhaustive-deps

 const submitMut = useMutation({
 mutationFn: () => {
 const values = methods.getValues();
 const answers: ScorecardAnswer[] = Object.entries(values.answers).map(
 ([question_id, value]) => ({ question_id, value })
 );
 return phase3Api.submitAnswers(candidateStageId, {
 stage_id: stageId,
 stage_def_id: stageDefId,
 answers,
 overall_rating: values.overall_rating || undefined,
 notes: values.notes || undefined,
 });
 },
 onSuccess: () => {
 queryClient.invalidateQueries({ queryKey: ["candidate"] });
 queryClient.invalidateQueries({ queryKey: ["kanban"] });
 onSaved?.();
 onOpenChange(false);
 },
 });

 const renderField = (q: ScorecardQuestion) => {
 const fieldName = `answers.${q.id}` as const;
 const error = methods.formState.errors.answers?.[q.id]?.message as
 | string
 | undefined;

 const descId = `${fieldName}-desc`;

 switch (q.type) {
 case"rating":
 return <RatingField name={fieldName} size="md" />;
 case"checkbox":
 return (
 <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
 <Checkbox
 checked={!!methods.watch(fieldName)}
 onCheckedChange={(v) => methods.setValue(fieldName, !!v)}
 />
 <span>{q.description ??"Potwierdzam"}</span>
 </label>
 );
 case"select": {
 const value = (methods.watch(fieldName) as string) ??"";
 return (
 <Select
 value={value}
 onValueChange={(v) => methods.setValue(fieldName, v)}
 >
 <SelectTrigger id={fieldName}>
 <SelectValue placeholder="Wybierz…" />
 </SelectTrigger>
 <SelectContent>
 {(q.options ?? []).map((opt) => (
 <SelectItem key={opt} value={opt}>
 {opt}
 </SelectItem>
 ))}
 </SelectContent>
 </Select>
 );
 }
 default:
 return (
 <textarea
 id={fieldName}
 rows={3}
 aria-describedby={descId}
 aria-invalid={!!error || undefined}
 className="w-full min-h-[80px] px-3 py-2 text-sm bg-card text-foreground border border-border rounded-lg placeholder:text-muted-foreground focus:outline-none focus:border-primary"
 placeholder="Wpisz ocenę…"
 value={(methods.watch(fieldName) as string) ??""}
 onChange={(e) => methods.setValue(fieldName, e.target.value)}
 />
 );
 }
 };

 return (
 <Sheet open={open} onOpenChange={onOpenChange}>
 <SheetContent side="right" size="lg">
 <SheetHeader>
 <div className="flex items-center gap-2">
 <Sparkles className="h-4 w-4 text-primary" />
 <SheetTitle>Scorecard — {schemaRes?.stage_name ?? stageName}</SheetTitle>
 </div>
 <SheetDescription>
 Ocena kandydata na etapie. Zapisane oceny wpływają na rating w pipeline.
 </SheetDescription>
 </SheetHeader>

 {isLoading ? (
 <SheetBody>
 <div className="text-sm text-muted-foreground py-8 text-center">
 Ładowanie schematu scorecardu…
 </div>
 </SheetBody>
 ) : schema.questions.length === 0 ? (
 <SheetBody>
 <div className="py-8 text-center text-sm text-muted-foreground">
 Ten etap nie ma skonfigurowanego scorecardu.
 </div>
 </SheetBody>
 ) : (
 <FormProvider {...methods}>
 <form
 className="flex flex-col h-full overflow-hidden"
 onSubmit={(e) => {
 e.preventDefault();
 submitMut.mutate();
 }}
 >
 <SheetBody>
 <div className="space-y-4">
 {schema.questions.map((q) => (
 <FormField
 key={q.id}
 name={`answers.${q.id}`}
 label={q.label}
 description={q.description}
 required={q.required}
 >
 {renderField(q)}
 </FormField>
 ))}

 <div className="pt-3 border-t border-border">
 <FormField
 name="overall_rating"
 label="Ocena ogólna"
 description="Ogólna ocena kandydata na tym etapie (1-5 gwiazdek)."
 >
 <RatingField name="overall_rating" size="lg" />
 </FormField>
 </div>

 <FormField name="notes" label="Notatki">
 <TextareaField
 name="notes"
 rows={3}
 placeholder="Dodatkowe obserwacje…"
 />
 </FormField>
 </div>
 </SheetBody>

 <SheetFooter>
 <Button
 type="button"
 variant="ghost"
 onClick={() => onOpenChange(false)}
 disabled={submitMut.isPending}
 >
 Anuluj
 </Button>
 <Button type="submit" variant="primary" loading={submitMut.isPending}>
 <Save className="h-4 w-4" />
 Zapisz scorecard
 </Button>
 </SheetFooter>
 </form>
 </FormProvider>
 )}
 </SheetContent>
 </Sheet>
 );
}
