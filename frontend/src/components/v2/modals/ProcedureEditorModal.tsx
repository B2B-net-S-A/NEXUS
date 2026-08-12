"use client";

import { useEffect, useMemo, useState } from"react";
import { useForm } from"react-hook-form";
import { zodResolver } from"@hookform/resolvers/zod";
import { useMutation, useQueryClient } from"@tanstack/react-query";
import { z } from"zod";
import ReactMarkdown from"react-markdown";
import remarkGfm from"remark-gfm";

import {
 Dialog,
 DialogBody,
 DialogContent,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from"@/components/ui/dialog";
import { Button } from"@/components/ui/button";
import { Input } from"@/components/ui/input";
import { Textarea } from"@/components/ui/textarea";
import {
 Procedure,
 ProcedureCreateInput,
 ProcedureUpdateInput,
 proceduresApi,
} from"@/lib/api/procedures";

const procedureSchema = z.object({
 title: z.string().min(3, "Tytuł jest za krótki").max(255, "Tytuł za długi"),
 content: z.string().min(1, "Treść jest wymagana"),
 sort_order: z.coerce.number().int(),
 is_published: z.boolean(),
});

// zod 4: z.coerce.number() ma wejście `unknown` — stąd osobny typ input/output.
type ProcedureFormInput = z.input<typeof procedureSchema>;
type ProcedureFormData = z.output<typeof procedureSchema>;

interface Props {
 procedure: Procedure | null;
 open: boolean;
 onOpenChange: (open: boolean) => void;
 onSaved: (saved: Procedure) => void;
}

export function ProcedureEditorModal({ procedure, open, onOpenChange, onSaved }: Props) {
 const editing = procedure !== null;
 const queryClient = useQueryClient();
 const [apiError, setApiError] = useState<string | null>(null);

 const {
 register,
 handleSubmit,
 watch,
 reset,
 formState: { errors, isSubmitting },
 } = useForm<ProcedureFormInput, unknown, ProcedureFormData>({
 resolver: zodResolver(procedureSchema),
 defaultValues: {
 title: procedure?.title ??"",
 content: procedure?.content ??"",
 sort_order: procedure?.sort_order ?? 0,
 is_published: procedure?.is_published ?? true,
 },
 });

 // Reset when switching between create/edit
 useEffect(() => {
 reset({
 title: procedure?.title ??"",
 content: procedure?.content ??"",
 sort_order: procedure?.sort_order ?? 0,
 is_published: procedure?.is_published ?? true,
 });
 setApiError(null);
 }, [procedure, reset]);

 const previewContent = watch("content");

 const mutation = useMutation({
 mutationFn: async (values: ProcedureFormData) => {
 const payload: ProcedureCreateInput | ProcedureUpdateInput = {
 title: values.title,
 content: values.content,
 sort_order: values.sort_order ?? 0,
 is_published: values.is_published,
 };
 if (editing && procedure) {
 return proceduresApi.update(procedure.id, payload);
 }
 return proceduresApi.create(payload as ProcedureCreateInput);
 },
 onSuccess: (saved) => {
 queryClient.invalidateQueries({ queryKey: ["procedures"] });
 queryClient.invalidateQueries({ queryKey: ["procedure", saved.id] });
 onSaved(saved);
 },
 onError: (err: unknown) => {
 const msg =
 err instanceof Error ? err.message : "Nie udało się zapisać procedury.";
 setApiError(msg);
 },
 });

 const onSubmit = handleSubmit((values) => {
 setApiError(null);
 mutation.mutate(values);
 });

 const title = useMemo(() => (editing ?"Edytuj procedurę" :"Nowa procedura"), [editing]);

 return (
 <Dialog open={open} onOpenChange={onOpenChange}>
 <DialogContent size="2xl" className="flex flex-col max-h-[90vh]">
 <DialogHeader>
 <DialogTitle>{title}</DialogTitle>
 </DialogHeader>

 <form onSubmit={onSubmit} className="contents">
 <DialogBody className="space-y-4 flex-1">
 <div>
 <label className="block text-sm font-medium text-foreground mb-1.5">
 Tytuł
 </label>
 <Input
 placeholder="Np. Jak prowadzić rozmowę z kandydatem"
 {...register("title")}
 invalid={!!errors.title}
 aria-describedby={errors.title ?"title-error" : undefined}
 />
 {errors.title && (
 <p id="title-error" className="text-xs text-primary mt-1">
 {errors.title.message}
 </p>
 )}
 </div>

 <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
 <div className="space-y-2">
 <label className="block text-sm font-medium text-foreground">
 Treść (Markdown)
 </label>
 <Textarea
 rows={16}
 placeholder={"# Krok 1\n- opis\n\n# Krok 2\n- opis"}
 {...register("content")}
 invalid={!!errors.content}
 className="font-mono text-xs"
 aria-describedby={errors.content ?"content-error" : undefined}
 />
 {errors.content && (
 <p id="content-error" className="text-xs text-primary">
 {errors.content.message}
 </p>
 )}
 </div>

 <div className="space-y-2">
 <span className="block text-sm font-medium text-foreground">
 Podgląd
 </span>
 <div
 className="rounded-lg border border-border bg-background p-4 min-h-[280px] max-h-[400px] overflow-y-auto prose prose-sm max-w-none prose-headings:font-semibold prose-headings:text-foreground prose-a:text-primary"
 aria-live="polite"
 >
 {previewContent ? (
 <ReactMarkdown remarkPlugins={[remarkGfm]}>
 {previewContent}
 </ReactMarkdown>
 ) : (
 <p className="text-xs text-muted-foreground">
 Zacznij pisać, żeby zobaczyć podgląd.
 </p>
 )}
 </div>
 </div>
 </div>

 <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
 <div>
 <label className="block text-sm font-medium text-foreground mb-1.5">
 Kolejność (sort_order)
 </label>
 <Input
 type="number"
 step={1}
 {...register("sort_order")}
 />
 <p className="text-xs text-muted-foreground mt-1">
 Wyższa wartość = wyżej na liście. Domyślnie 0.
 </p>
 </div>
 <div className="flex items-end">
 <label className="inline-flex items-center gap-2 text-sm">
 <input
 type="checkbox"
 className="h-4 w-4 rounded border-border accent-[hsl(var(--primary))]"
 {...register("is_published")}
 />
 <span>Opublikowane (widoczne dla zespołu)</span>
 </label>
 </div>
 </div>

 {apiError && (
 <p className="text-sm text-primary">{apiError}</p>
 )}
 </DialogBody>

 <DialogFooter>
 <Button
 type="button"
 variant="outline"
 onClick={() => onOpenChange(false)}
 disabled={isSubmitting}
 >
 Anuluj
 </Button>
 <Button type="submit" variant="primary" loading={isSubmitting}>
 {editing ?"Zapisz zmiany" :"Dodaj procedurę"}
 </Button>
 </DialogFooter>
 </form>
 </DialogContent>
 </Dialog>
 );
}
