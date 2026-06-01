"use client";

import * as React from"react";
import { useEffect } from"react";
import { useForm } from"react-hook-form";
import { zodResolver } from"@hookform/resolvers/zod";
import { z } from"zod";
import { useMutation, useQuery, useQueryClient } from"@tanstack/react-query";
import { AlertTriangle, Send, Sparkles, User } from"lucide-react";
import {
 screeningApi,
 type ScreeningAnswerItem,
 type ScreeningAnswers,
 type ScreeningQuestion,
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
import { Badge } from"@/components/ui/badge";
import { Checkbox } from"@/components/ui/checkbox";
import { RadioGroup, RadioGroupItem } from"@/components/ui/radio-group";
import {
 Form,
 FormField,
 TextareaField,
} from"@/components/v2/forms";

const FIT_OPTIONS = [
 { value: "fit" as const, label: "Pasuje", description: "Spełnia wszystkie kluczowe kryteria." },
 { value: "uncertain" as const, label: "Niepewne", description: "Warto dopytać lub zostawić do decyzji klienta." },
 { value: "miss" as const, label: "Nie pasuje", description: "Nie rekomenduję – deal-breaker lub brak kompetencji." },
];

interface Props {
 open: boolean;
 onOpenChange: (open: boolean) => void;
 stageId: number;
 candidateName: string;
 onSubmitted?: (matchPercent: number) => void;
}

interface FormValues {
 answers: Record<string, { response: string; deal_breaker_hit: boolean }>;
 overall_fit: "fit" |"uncertain" |"miss";
 notes: string;
}

function makeSchema(questions: ScreeningQuestion[]) {
 const answersShape = Object.fromEntries(
 questions.map((q) => [
 q.id,
 z.object({
 response: z.string().min(1, "Odpowiedź jest wymagana"),
 deal_breaker_hit: z.boolean(),
 }),
 ])
 );
 return z.object({
 answers: z.object(answersShape),
 overall_fit: z.enum(["fit","uncertain","miss"]),
 notes: z.string().optional().default(""),
 });
}

export function ScreeningSheet({
 open,
 onOpenChange,
 stageId,
 candidateName,
 onSubmitted,
}: Props) {
 const queryClient = useQueryClient();

 const { data, isLoading } = useQuery({
 queryKey: ["screening-v2", stageId],
 queryFn: () => screeningApi.getForStage(stageId).then((r) => r.data),
 enabled: open,
 });

 const questions: ScreeningQuestion[] =
 ((data?.champion_profile as any)?.screening_questions as ScreeningQuestion[]) ?? [];
 const existing = data?.screening_answers;

 const methods = useForm<FormValues>({
 resolver: zodResolver(makeSchema(questions)) as any,
 defaultValues: {
 answers: {},
 overall_fit: "uncertain",
 notes: "",
 },
 });

 // Hydrate form when data loads
 useEffect(() => {
 if (!data) return;
 const entries: Record<string, { response: string; deal_breaker_hit: boolean }> = {};
 for (const q of questions) {
 const existingAnswer = existing?.answers.find((a) => a.question_id === q.id);
 entries[q.id] = {
 response: existingAnswer?.response ??"",
 deal_breaker_hit: existingAnswer?.deal_breaker_hit ?? false,
 };
 }
 methods.reset({
 answers: entries,
 overall_fit: existing?.overall_fit ??"uncertain",
 notes: existing?.notes ??"",
 });
 }, [data, existing, questions.length]); // eslint-disable-line react-hooks/exhaustive-deps

 const submitMut = useMutation({
 mutationFn: (payload: ScreeningAnswers) => screeningApi.submit(stageId, payload),
 onSuccess: (r) => {
 queryClient.invalidateQueries({ queryKey: ["screening-v2", stageId] });
 queryClient.invalidateQueries({ queryKey: ["candidate"] });
 onSubmitted?.(r.data.match_percent);
 onOpenChange(false);
 },
 });

 const onSubmit = (values: FormValues) => {
 const answers: ScreeningAnswerItem[] = questions.map((q) => ({
 question_id: q.id,
 response: values.answers[q.id]?.response ??"",
 deal_breaker_hit: !!values.answers[q.id]?.deal_breaker_hit,
 }));
 submitMut.mutate({
 answers,
 overall_fit: values.overall_fit,
 notes: values.notes ??"",
 });
 };

 return (
 <Sheet open={open} onOpenChange={onOpenChange}>
 <SheetContent side="right" size="xl">
 <SheetHeader>
 <div className="flex items-center gap-2">
 <Sparkles className="h-4 w-4 text-primary" />
 <SheetTitle>Screening kandydata</SheetTitle>
 </div>
 <SheetDescription>
 <span className="inline-flex items-center gap-1.5">
 <User className="h-3.5 w-3.5" />
 {candidateName}
 </span>
 </SheetDescription>
 </SheetHeader>

 {isLoading ? (
 <SheetBody>
 <div className="text-sm text-muted-foreground py-8 text-center">
 Ładowanie pytań screeningowych…
 </div>
 </SheetBody>
 ) : questions.length === 0 ? (
 <SheetBody>
 <div className="py-8 text-center text-sm text-muted-foreground">
 <AlertTriangle className="h-10 w-10 mx-auto mb-2 opacity-40" />
 Ta oferta nie ma skonfigurowanego Champion Profile – poproś TAC
 o uzupełnienie pytań screeningowych.
 </div>
 </SheetBody>
 ) : (
 <Form methods={methods} onSubmit={onSubmit} className="flex flex-col h-full overflow-hidden">
 <SheetBody>
 <div className="space-y-5">
 {questions.map((q, i) => {
 const dealBreakerName = `answers.${q.id}.deal_breaker_hit` as const;
 return (
 <div
 key={q.id}
 className="rounded-lg border border-border bg-background/40 p-4 space-y-3"
 >
 <div className="flex items-start gap-2">
 <Badge variant="soft" size="sm" className="shrink-0 font-mono">
 Q{i + 1}
 </Badge>
 <div className="flex-1">
 <p className="text-sm font-semibold text-foreground">
 {q.question}
 </p>
 {q.ideal_answer && (
 <p className="text-xs text-muted-foreground mt-1 italic">
 Idealnie: {q.ideal_answer}
 </p>
 )}
 {q.deal_breaker && (
 <p className="text-xs text-primary mt-1">
 Deal-breaker: {q.deal_breaker}
 </p>
 )}
 </div>
 </div>
 <FormField name={`answers.${q.id}.response`} label="Odpowiedź">
 <TextareaField
 name={`answers.${q.id}.response`}
 rows={3}
 placeholder="Jak odpowiedział kandydat ? "
 />
 </FormField>
 <label className="inline-flex items-center gap-2 text-xs cursor-pointer">
 <Checkbox
 checked={!!methods.watch(dealBreakerName)}
 onCheckedChange={(v) =>
 methods.setValue(dealBreakerName, !!v, {
 shouldValidate: true,
 })
 }
 />
 <span>Odpowiedź narusza deal-breaker</span>
 </label>
 </div>
 );
 })}

 {/* Overall fit */}
 <div className="pt-2">
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Ogólna ocena dopasowania
 </h3>
 <RadioGroup
 value={methods.watch("overall_fit")}
 onValueChange={(v) =>
 methods.setValue("overall_fit", v as FormValues["overall_fit"])
 }
 >
 {FIT_OPTIONS.map((opt) => (
 <label
 key={opt.value}
 className="flex items-start gap-2 cursor-pointer rounded-md p-2 hover:bg-primary/10"
 >
 <RadioGroupItem value={opt.value} className="mt-0.5" />
 <div>
 <div className="text-sm font-medium text-foreground">
 {opt.label}
 </div>
 <div className="text-xs text-muted-foreground">
 {opt.description}
 </div>
 </div>
 </label>
 ))}
 </RadioGroup>
 </div>

 <FormField
 name="notes"
 label="Notatki rekrutera"
 description="Kontekst, follow-upy, deal-breakers – widoczne w share portalu klienta."
 >
 <TextareaField
 name="notes"
 rows={4}
 placeholder="Np. kandydat był gotowy zacząć w 2 tyg, rozmowa po angielsku…"
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
 <Button
 type="submit"
 variant="primary"
 loading={submitMut.isPending}
 >
 <Send className="h-4 w-4" />
 Zapisz screening
 </Button>
 </SheetFooter>
 </Form>
 )}
 </SheetContent>
 </Sheet>
 );
}
