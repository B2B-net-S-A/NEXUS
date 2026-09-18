"use client";

/**
 * CVBrandedEditModal — edytor brandowanego CV per rekrutacja (Tiptap +
 * autosave + finalize). Mirror `DraftEditor` z `CandidateDetailV2.tsx:1288`.
 *
 * PR2 — Faza 5. Lazy render przez backend GET /cv/branded — pierwszy raz
 * generuje template z `_generate_cv_html()`. PATCH save / re-render. POST
 * finalize → snapshot do storage_service, status `draft → finalized`,
 * dalsze edycje 409.
 */

import { useState, useEffect, useRef } from"react";
import { useQuery, useMutation, useQueryClient } from"@tanstack/react-query";
import { useEditor, EditorContent } from"@tiptap/react";
import StarterKit from"@tiptap/starter-kit";
import { CvEditorSection } from "@/lib/cv-editor-section";
import {
 CheckCircle2,
 Loader2,
 Printer,
 Download,
 RefreshCcw,
 Sparkles,
 AlertCircle,
} from"lucide-react";

import { Dialog, DialogContent } from"@/components/ui/dialog";
import { Button } from"@/components/ui/button";
import { Badge } from"@/components/ui/badge";
import { Label } from"@/components/ui/label";
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from"@/components/ui/select";
import { CvDraftSession, type CvSaveState } from "@/lib/cv-draft-session";
import { useToast } from"@/components/Toast";
import { openAuthenticatedFile, downloadAuthenticatedFile, postAuthenticatedDownload, downloadBlob } from "@/lib/authenticated-files";
import {
 candidateStageCvApi,
 cvGeneratedEditorApi,
 type CVBrandedState,
 type CVTemplate,
 type CVLanguage,
} from"@/lib/api";

type Props = {
 open: boolean;
 onOpenChange: (open: boolean) => void;
 onRegenerate?: () => void;

 candidateName: string;
 jobTitle?: string;
} & ({ stageId: number; generatedId?: never } | { generatedId: number; stageId?: never });

function getErrorMessage(e: unknown): string {
 const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
 if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") return detail.message;
 return typeof detail === "string" ? detail : e instanceof Error ? e.message : "Nie udało się wykonać operacji";
}

export function CVBrandedEditModal(props: Props) {
 return <CVBrandedEditContent key={props.generatedId !== undefined ? `generated-${props.generatedId}` : `stage-${props.stageId}`} {...props} />;
}

function CVBrandedEditContent({
 open,
 onOpenChange,
 onRegenerate,
 stageId: pipelineStageId,
 generatedId,
 candidateName,
 jobTitle,
}: Props) {
 const stageId = (generatedId ?? pipelineStageId)!;
 const scopeKey = generatedId !== undefined ? "cv-generated-editor" : "cv-branded";
 const editorApi = generatedId !== undefined ? cvGeneratedEditorApi : candidateStageCvApi.branded;
 const basePath = generatedId !== undefined ? `/api/cv-generator/generated/${generatedId}/editor` : `/api/candidates/stages/${stageId}/cv/branded`;
 const queryClient = useQueryClient();
 const { showSuccess, showError } = useToast();
 const [confirmFinalize, setConfirmFinalize] = useState(false);
 // Werdykt niezależnej kontroli AI treści (0326). Trwały, bo to lista rzeczy
 // do sprawdzenia przed wysyłką CV do klienta — nie powiadomienie chwilowe.
 const [reviewNotice, setReviewNotice] = useState<{kind: "findings" | "unavailable"; count: number} | null>(null);
 const [approvalError, setApprovalError] = useState<{message: string; regenerate: boolean} | null>(null);
 // Trwały błąd zapisu (409 — ktoś zapisał nowszą wersję, 422 — puste CV).
 // Zamknięcie edytora = udany zapis, więc bez tej ścieżki okna nie dało się
 // zamknąć wcale: każde „Zamknij" kończyło się tym samym błędem.
 const [saveProblem, setSaveProblem] = useState<{message: string; conflict: boolean} | null>(null);
 const [confirmDiscard, setConfirmDiscard] = useState(false);
 const [reloading, setReloading] = useState(false);
 const [pendingTemplate, setPendingTemplate] = useState<CVTemplate | null>(
 null,
 );
 const [pendingLanguage, setPendingLanguage] = useState<CVLanguage | null>(
 null,
 );

 const { data, isLoading, error: loadError, refetch, isFetching } = useQuery<CVBrandedState>({
 queryKey: [scopeKey, stageId],
 queryFn: () =>
 editorApi.get(stageId).then((r) => r.data),
 enabled: open,
 });

 const editor = useEditor({
 immediatelyRender: false,
 extensions: [StarterKit, CvEditorSection],
 content: "",
 editorProps: {
 attributes: {
 class: "prose prose-sm max-w-none min-h-[400px] focus:outline-hidden border border-border rounded-lg bg-card p-4",
 },
 },
 });

 const sessionRef = useRef<CvDraftSession | null>(null);
 const approvalAbort = useRef<AbortController | null>(null);
 const cancellingRef = useRef(false);
 const [cancellingReview, setCancellingReview] = useState(false);
 const [activeReview, setActiveReview] = useState<{id: number; payload: {content_html: string; expected_revision: number}} | null>(null);
 useEffect(() => () => approvalAbort.current?.abort(), [open]);
 const loadedStage = useRef<number | null>(null);
 const replacingRef = useRef(false);
 const [saveState, setSaveState] = useState<CvSaveState>("saved");

 const loadState = (state: CVBrandedState) => {
   approvalAbort.current?.abort();
   setActiveReview(null);
   const session = new CvDraftSession(state.content_html ?? "<p></p>", state.edit_revision,
     state.status === "finalized", {
       save: (html, revision) => editorApi.update(stageId, {
         content_html: html, expected_revision: revision,
       }).then((r) => { queryClient.setQueryData([scopeKey, stageId], r.data); return r.data; }),
       finalize: (html, revision) => {
         approvalAbort.current?.abort();
         approvalAbort.current = new AbortController();
         const payload = {content_html: html, expected_revision: revision};
         setActiveReview(null);
         return editorApi.finalize(stageId, payload, approvalAbort.current.signal, state => {
           setActiveReview(state.review_id != null && (state.status === "queued" || state.status === "running")
             ? {id: state.review_id, payload} : null);
         }).then((r) => r.data);
       },
     }, (status) => {
       if (sessionRef.current === session) setSaveState(status);
     });
   sessionRef.current = session;
   loadedStage.current = stageId;
   setSaveState(session.state);
   editor?.commands.setContent(session.html, { emitUpdate: false });
   queryClient.setQueryData([scopeKey, stageId], state);
 };

 useEffect(() => {
   if (!editor || !data) return;
   if (loadedStage.current === stageId) {
     const session = sessionRef.current;
     if (!session || session.state !== "saved" || data.edit_revision <= session.revision) return;
   }
   loadState(data);
   // Remote refetches must not replace locally edited content.
   // eslint-disable-next-line react-hooks/exhaustive-deps
 }, [editor, data, stageId]);

 useEffect(() => {
   editor?.setEditable(!replacingRef.current && !cancellingReview && saveState !== "finalized" && saveState !== "finalizing");
 }, [editor, saveState, cancellingReview]);

 useEffect(() => {
   if (!editor) return;
   const handler = () => sessionRef.current?.edit(editor.getHTML());
   editor.on("update", handler);
   return () => { editor.off("update", handler); };
 }, [editor]);

 const reportSaveProblem = (error: unknown) => {
   const status = (error as {response?: {status?: unknown}} | null)?.response?.status;
   setSaveProblem({message: getErrorMessage(error), conflict: status === 409});
   showError(getErrorMessage(error));
 };
 const saveCurrent = async () => {
   try { await sessionRef.current?.save(); setSaveProblem(null); }
   catch (error) { reportSaveProblem(error); }
 };
 const reloadCurrentVersion = async () => {
   setReloading(true);
   try {
     const fresh = await refetch();
     if (!fresh.data) throw fresh.error ?? new Error("Nie udało się wczytać aktualnej wersji CV");
     loadState(fresh.data);
     setSaveProblem(null);
     showSuccess("Wczytano aktualną wersję CV");
   } catch (error) { showError(getErrorMessage(error)); }
   finally { setReloading(false); }
 };
 useEffect(() => {
   if (!open) return;
   const id = setInterval(() => {
     if (!replacingRef.current && sessionRef.current?.state === "unsaved") void saveCurrent();
   }, 2000);
   return () => clearInterval(id);
   // eslint-disable-next-line react-hooks/exhaustive-deps
 }, [open, stageId]);

 const closeEditor = async (nextOpen: boolean) => {
   if (nextOpen) { onOpenChange(true); return true; }
   if (replacingRef.current || cancellingRef.current || sessionRef.current?.state === "finalizing") return false;
   try {
     await sessionRef.current?.settle();
     await sessionRef.current?.save();
     while (sessionRef.current?.state === "unsaved") await sessionRef.current.save();
     setSaveProblem(null);
     onOpenChange(false);
     return true;
   } catch (error) { reportSaveProblem(error); return false; }
 };

 const swapMut = useMutation({
   mutationFn: async (payload: { template?: CVTemplate; language?: CVLanguage }) => {
     const session = sessionRef.current;
     if (!session) throw new Error("CV nie jest jeszcze wczytane");
     replacingRef.current = true;
     editor?.setEditable(false);
     await session.settle();
     return editorApi.update(stageId, { ...payload, expected_revision: session.revision });
   },
   onSuccess: (response) => {
     loadState(response.data);
     showSuccess("Wczytano nowy szablon");
     setPendingTemplate(null); setPendingLanguage(null);
   },
   onError: (e) => showError(getErrorMessage(e)),
   onSettled: () => {
     replacingRef.current = false;
     editor?.setEditable(sessionRef.current?.state !== "finalized");
   },
 });

 const finalizeMut = useMutation({
   mutationFn: async () => {
     if (!sessionRef.current) throw new Error("CV nie jest jeszcze wczytane");
     if (cancellingRef.current) throw new Error("Trwa anulowanie kontroli CV");
     setConfirmFinalize(false);
     const outcome = await sessionRef.current.finalize();
     const response = await editorApi.get(stageId);
     return {response, outcome};
   },
   onSuccess: ({response, outcome}) => {
     loadState(response.data);
     // Kontrola jest doradcza: zatwierdzenie SIĘ UDAŁO, więc toast zostaje
     // pozytywny, a uwagi dostają własny, trwały baner — znikający toast nie
     // jest miejscem na listę rzeczy do sprawdzenia przed wysyłką do klienta.
     const findings = outcome?.content_review_findings ?? 0;
     setReviewNotice(
       findings > 0
         ? {kind: "findings", count: findings}
         : outcome?.content_review_status === "unverified"
           ? {kind: "unavailable", count: 0}
           : null,
     );
     showSuccess(findings > 0
       ? `Zatwierdzono. Niezależna kontrola AI zgłosiła ${findings} ${findings === 1 ? "twierdzenie" : "twierdzeń"} bez pokrycia w źródłach.`
       : "Zapisano i zatwierdzono bieżącą treść CV");
     setApprovalError(null);
     setConfirmFinalize(false);
   },
   onError: (e) => {
     if (cancellingRef.current || approvalAbort.current?.signal.aborted) return;
     const detail = (e as {response?: {data?: {detail?: {code?: string}}}})?.response?.data?.detail;
     setApprovalError({message: getErrorMessage(e), regenerate: detail?.code === "cv_source_regeneration_required"});
     showError(getErrorMessage(e));
     setConfirmFinalize(false);
   },
 });
 const cancelReview = async () => {
   if (!activeReview || cancellingRef.current) return;
   const target = activeReview;
   cancellingRef.current = true;
   setCancellingReview(true);
   approvalAbort.current?.abort();
   try {
     const result = await editorApi.cancelReview(stageId, target.id, target.payload);
     // After a polling timeout the recruiter may already have edited again.
     // Persist those edits before loading the server state after cancellation.
     const session = sessionRef.current;
     await session?.settle();
     await session?.save();
     while (session?.state === "unsaved") await session.save();
     const current = await editorApi.get(stageId);
     loadState(current.data);
     setApprovalError(null);
     showSuccess(current.data.status === "finalized" ? "CV zostało już zatwierdzone."
       : result.data.status === "cancelled" ? "Anulowano kontrolę. Szkic został zachowany."
       : "Kontrola zakończona. CV pozostaje szkicem.");
   } catch (error) {
     const message = "Nie udało się potwierdzić anulowania: " + getErrorMessage(error);
     setApprovalError({message, regenerate: false});
     showError(message);
   } finally {
     cancellingRef.current = false;
     setCancellingReview(false);
   }
 };
 const newDraftMut = useMutation({
   mutationFn: () => editorApi.newDraft(stageId, sessionRef.current!.revision),
   onSuccess: (response) => loadState(response.data),
   onError: (e) => showError(getErrorMessage(e)),
 });

 const handleTemplateChange = (val: CVTemplate) => {
 if (cancellingRef.current) return;
 if (data?.status === "finalized") return;
 if (val === data?.template) return;
 setPendingTemplate(val);
 };

 const handleLanguageChange = (val: CVLanguage) => {
 if (cancellingRef.current) return;
 if (data?.status === "finalized") return;
 if (val === data?.language) return;
 setPendingLanguage(val);
 };

 const confirmSwap = () => {
 const payload: { template?: CVTemplate; language?: CVLanguage } = {};
 if (pendingTemplate) payload.template = pendingTemplate;
 if (pendingLanguage) payload.language = pendingLanguage;
 swapMut.mutate(payload);
 };

 // Print view is Bearer-guarded — a raw window.open sends no Authorization
 // header and lands on a white "Not authenticated" page. Fetch the HTML with
 // auth and open it as a same-origin blob URL (its inline window.print() runs).
 const handlePrint = async () => {
   try {
     await sessionRef.current?.settle();
     await sessionRef.current?.save();
     while (sessionRef.current?.state === "unsaved") await sessionRef.current.save();
     await openAuthenticatedFile(
       `${basePath}/render-pdf`,
       "text/html",
     );
   } catch {
     showError("Nie udało się otworzyć CV do druku.");
   }
 };

 const isFinalized = saveState === "finalized";
 const [downloadingDocx, setDownloadingDocx] = useState(false);
 const previewDocx = async () => {
   const session = sessionRef.current;
   if (!session) return;
   setDownloadingDocx(true);
   try {
     await session.settle();
     const result = await postAuthenticatedDownload(
       `${basePath}/preview-docx`,
       {content_html: session.html, expected_revision: session.revision},
     );
     downloadBlob(result.blob, result.filename || "SZKIC_CV.docx");
   } catch (error) { showError(getErrorMessage(error)); }
   finally { setDownloadingDocx(false); }
 };
 const downloadApproved = async () => {
   if (!data?.docx_available) return;
   setDownloadingDocx(true);
   try {
     await downloadAuthenticatedFile(
       `${basePath}/versions/${data.version}/docx`,
       data.docx_filename || "CV.docx",
     );
   } catch (error) { showError(getErrorMessage(error)); }
   finally { setDownloadingDocx(false); }
 };

 return (
 <>
 <Dialog open={open} onOpenChange={(value) => void closeEditor(value)}>
 <DialogContent size="2xl" className="p-0 max-h-[92vh] flex flex-col">
 {reviewNotice && <div role="status" className="px-5 py-3 border-b border-border text-sm bg-amber-50 dark:bg-amber-950/30">
   {reviewNotice.kind === "findings" ? <>
     <p className="font-medium">Niezależna kontrola AI: {reviewNotice.count}{" "}
       {reviewNotice.count === 1 ? "twierdzenie" : "twierdzeń"} bez pokrycia w źródłach.</p>
     <p className="text-muted-foreground mt-1">
       CV zostało zatwierdzone — kontrola jest doradcza. Porównaj zaznaczone treści
       z oryginalnym CV i notatkami przed wysyłką do klienta.
     </p>
   </> : <p className="text-muted-foreground">
     Niezależna kontrola AI treści nie wykonała się. CV zostało zatwierdzone; sprawdź je ręcznie z oryginałem.
   </p>}
 </div>}
 {approvalError && <div role="alert" className="px-5 py-3 border-b border-border text-sm">
   <p className="text-destructive">{approvalError.message}</p>
   {approvalError.regenerate && <>
     <ol className="list-decimal pl-5 mt-2 space-y-1">
       <li>Zapisz szkic i wróć do generatora CV.</li>
       <li>Wybierz oryginalny plik CV lub wgraj go ponownie. Sprawdź rekrutację, klienta i notatki.</li>
       <li>Wygeneruj nowe CV, sprawdź jego treść i zatwierdź nowy wynik.</li>
     </ol>
     <p className="mt-2">Nowa generacja zużyje zwykły limit AI. Obecne poprawki pozostają w szkicu; nie zostaną automatycznie przeniesione.</p>
     <Button className="mt-2" size="sm" variant="outline" onClick={async () => {
       if (await closeEditor(false)) onRegenerate?.();
     }}>{onRegenerate ? "Zapisz szkic i przejdź do generatora" : "Zapisz szkic i zamknij"}</Button>
   </>}
 </div>}
 {saveProblem && <div role="alert" className="px-5 py-3 border-b border-border text-sm space-y-2">
   <p className="text-destructive">Nie udało się zapisać CV: {saveProblem.message}</p>
   {saveProblem.conflict && <p className="text-muted-foreground">
     Ktoś zapisał nowszą wersję tego CV. Wczytanie aktualnej wersji zastąpi niezapisane poprawki w edytorze.
   </p>}
   <div className="flex flex-wrap gap-2">
     {saveProblem.conflict && <Button size="sm" variant="outline" disabled={reloading}
       onClick={() => void reloadCurrentVersion()}>
       {reloading ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <RefreshCcw className="h-3 w-3 mr-1" />}
       Wczytaj aktualną wersję
     </Button>}
     <Button size="sm" variant="outline" onClick={() => void closeEditor(false)}>Ponów zapis i zamknij</Button>
     <Button size="sm" variant="ghost" onClick={() => setConfirmDiscard(true)}>Zamknij bez zapisu</Button>
   </div>
 </div>}
 <div className="flex items-center justify-between px-5 py-3 border-b border-border">
 <div className="min-w-0">
 <div className="text-xs uppercase tracking-wider text-muted-foreground">
 Brandowane CV (per rekrutacja)
 </div>
 <div className="text-sm font-medium text-foreground truncate">
 {candidateName}
 {jobTitle ? (
 <span className="text-muted-foreground font-normal">
 {""}
 — {jobTitle}
 </span>
 ) : null}
 </div>
 </div>
 <div className="flex items-center gap-2">
 {isFinalized ? (
 <Badge variant="success" size="sm">
 <CheckCircle2 className="h-3 w-3 mr-1" />
 Sfinalizowane
 </Badge>
 ) : data?.status === "draft" ? (
 <Badge variant="info" size="sm">
 Szkic v{data?.version ?? 1}
 </Badge>
 ) : null}
 </div>
 </div>

 {data?.presentation_review?.status === "conflict" && <p role="alert" className="px-5 py-2 text-sm text-destructive">
 Reguły klienta dla zapisanego szkicu: {data.presentation_review.message}
 </p>}
 {data?.presentation_review?.status === "needs_review" && <p className="px-5 py-2 text-xs text-muted-foreground">
 {data.presentation_review.reason === "rule_snapshot_unavailable"
   ? "Brak potwierdzonej kopii reguł klienta dla tego CV. Sprawdź wymagania klienta przed zatwierdzeniem."
   : `Przed zatwierdzeniem sprawdź ręcznie: ${(data.presentation_review.manual_fields ?? []).map(field => ({
       generator_instructions: "instrukcje klienta",
       generator_instructions_en: "instrukcje klienta dla wersji angielskiej",
       notes: "uwagi klienta",
       date_format: "format dat",
       glossary: "tłumaczenia",
       highlight_policy: "zasady pogrubień",
       highlight_terms: "wyróżnione słowa",
       max_bullets_per_role: "liczbę obowiązków w opisach stanowisk",
       max_bullet_chars: "długość opisów obowiązków",
     } as Record<string, string>)[field] ?? "dodatkową regułę klienta").join(", ") || "reguły klienta"}. Automatyczna kontrola nie potwierdziła tych reguł.`}
 </p>}
 {data?.from_generator && <p className="px-5 py-2 text-xs text-muted-foreground">
 Wybrano wynik generatora {data.generated_document_id != null ? `#${data.generated_document_id}` : "(źródło usunięte)"}.
 Aby zmienić język lub szablon, wygeneruj i wybierz nowy wynik.
 </p>}
 <div className="px-5 py-3 border-b border-border bg-background">
 <div className="flex items-end gap-3 flex-wrap">
 <div>
 <Label className="text-[10px] uppercase">Szablon</Label>
 <Select
 value={pendingTemplate ?? data?.template ??"standard"}
 onValueChange={(v) => handleTemplateChange(v as CVTemplate)}
 disabled={!data || isFinalized || data?.from_generator}
 >
 <SelectTrigger className="w-36 h-8 text-xs">
 <SelectValue />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="standard">Pełny</SelectItem>
 <SelectItem value="blind">Anonimowy (blind)</SelectItem>
 </SelectContent>
 </Select>
 </div>
 <div>
 <Label className="text-[10px] uppercase">Język</Label>
 <Select
 value={pendingLanguage ?? data?.language ??"pl"}
 onValueChange={(v) => handleLanguageChange(v as CVLanguage)}
 disabled={!data || isFinalized || data?.from_generator}
 >
 <SelectTrigger className="w-24 h-8 text-xs">
 <SelectValue />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="pl">PL</SelectItem>
 <SelectItem value="en">EN</SelectItem>
 </SelectContent>
 </Select>
 </div>
 {(pendingTemplate || pendingLanguage) && !isFinalized ? (
 <div className="flex items-center gap-2 text-xs">
 <Button
 size="sm"
 onClick={confirmSwap}
 disabled={swapMut.isPending}
 >
 {swapMut.isPending ? (
 <Loader2 className="h-3 w-3 mr-1 animate-spin" />
 ) : (
 <RefreshCcw className="h-3 w-3 mr-1" />
 )}
 Wczytaj nowy szablon (nadpisze edycje)
 </Button>
 <Button
 size="sm"
 variant="ghost"
 onClick={() => {
 setPendingTemplate(null);
 setPendingLanguage(null);
 }}
 >
 Anuluj
 </Button>
 </div>
 ) : null}
 <div className="ml-auto flex items-center gap-2">
 <span className="text-[11px] text-muted-foreground" role="status">
 {{ saved: "Zapisano", unsaved: "Niezapisane zmiany", saving: "Zapisywanie…",
    error: "Błąd zapisu — poprawki pozostają w edytorze", finalizing: "Kontrola treści i zatwierdzanie…",
    finalized: `Zatwierdzona wersja ${data?.version ?? ""}` }[saveState]}
 </span>
 {activeReview && <div className="text-right">
 <Button size="sm" variant="outline" disabled={cancellingReview} onClick={() => void cancelReview()}>
 {cancellingReview ? "Anulowanie…" : "Anuluj kontrolę"}
 </Button>
 <p className="text-[10px] text-muted-foreground">Rozpoczęta kontrola może zużyć limit AI.</p>
 </div>}
 {saveState === "error" ? <Button size="sm" variant="outline" onClick={() => void saveCurrent()}>Ponów zapis</Button> : null}

 </div>
 </div>
 </div>

 <div className="flex-1 overflow-auto p-5 bg-background">
 {loadError && <div role="alert" className="mb-4 space-y-2 text-sm text-destructive">
 <p>Nie udało się wczytać CV: {getErrorMessage(loadError)}</p>
 <Button variant="outline" size="sm" disabled={isFetching} onClick={() => void refetch()}>
 Ponów wczytanie
 </Button>
 {!data && onRegenerate && (loadError as {response?: {data?: {detail?: {code?: string}}}}).response?.data?.detail?.code === "cv_editor_assets_unavailable" && (
 <Button variant="outline" size="sm" disabled={isFetching} onClick={() => { onOpenChange(false); onRegenerate(); }}>
 Przejdź do generatora
 </Button>
 )}
 </div>}
 {isLoading ? (
 <div className="text-center text-sm text-muted-foreground py-10">
 Ładowanie…
 </div>
 ) : data ? (
 <EditorContent editor={editor} />
 ) : null}
 </div>

 <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 border-t border-border">
 <Button
 variant="outline"
 size="sm"
 onClick={handlePrint}
 disabled={!data?.content_html}
 >
 <Printer className="h-3.5 w-3.5 mr-1.5" />
 Drukuj / PDF
 </Button>
 <div className="flex flex-wrap items-center gap-2">
 {!isFinalized && data?.status === "draft" && <Button size="sm" variant="outline"
 disabled={downloadingDocx || finalizeMut.isPending || swapMut.isPending} onClick={() => void previewDocx()}>
 <Download className="h-3.5 w-3.5 mr-1.5" /> Pobierz szkic DOCX
 </Button>}
 {isFinalized && data?.docx_available && <Button size="sm" variant="outline"
 disabled={downloadingDocx} onClick={() => void downloadApproved()}>
 <Download className="h-3.5 w-3.5 mr-1.5" /> Pobierz zatwierdzony DOCX v{data.version}
 </Button>}
 {isFinalized ? <Button size="sm" variant="outline" disabled={newDraftMut.isPending}
 onClick={() => newDraftMut.mutate()}>Utwórz nową wersję</Button> : null}
 <Button
 variant="ghost"
 size="sm"
 onClick={() => void closeEditor(false)}
 >
 Zamknij
 </Button>
 <Button
 size="sm"
 onClick={() => setConfirmFinalize(true)}
 disabled={
 isFinalized || !data?.content_html || finalizeMut.isPending || swapMut.isPending
 }
 >
 <Sparkles className="h-3.5 w-3.5 mr-1.5" />
 Zapisz i zatwierdź
 </Button>
 </div>
 </div>
 </DialogContent>
 </Dialog>

 {confirmDiscard ? (
 <Dialog open onOpenChange={() => setConfirmDiscard(false)}>
 <DialogContent size="md">
 <div className="p-5 space-y-3">
 <div className="flex items-start gap-3">
 <AlertCircle className="h-5 w-5 text-destructive mt-0.5" />
 <div>
 <h3 className="font-medium">Zamknąć bez zapisu?</h3>
 <p className="text-sm text-muted-foreground mt-1">
 Niezapisane poprawki z edytora przepadną. Na serwerze zostaje ostatnia zapisana wersja CV.
 </p>
 </div>
 </div>
 <div className="flex justify-end gap-2 pt-2">
 <Button variant="ghost" size="sm" onClick={() => setConfirmDiscard(false)}>Wróć do edycji</Button>
 <Button variant="destructive" size="sm" onClick={() => {
   approvalAbort.current?.abort();
   setConfirmDiscard(false);
   setSaveProblem(null);
   onOpenChange(false);
 }}>Zamknij bez zapisu</Button>
 </div>
 </div>
 </DialogContent>
 </Dialog>
 ) : null}

 {confirmFinalize ? (
 <Dialog open onOpenChange={() => setConfirmFinalize(false)}>
 <DialogContent size="md">
 <div className="p-5 space-y-3">
 <div className="flex items-start gap-3">
 <AlertCircle className="h-5 w-5 text-amber-500 mt-0.5" />
 <div>
 <h3 className="font-medium">Sfinalizować brandowane CV?</h3>
 <p className="text-sm text-muted-foreground mt-1">
 Zapiszemy i zatwierdzimy bieżącą treść. Późniejsze poprawki
 utworzą nową wersję; istniejące linki zachowają poprzednią treść.
 </p>
 </div>
 </div>
 <div className="flex justify-end gap-2 pt-2">
 <Button
 variant="ghost"
 size="sm"
 onClick={() => setConfirmFinalize(false)}
 >
 Anuluj
 </Button>
 <Button
 size="sm"
 onClick={() => finalizeMut.mutate()}
 disabled={finalizeMut.isPending || cancellingReview}
 >
 {finalizeMut.isPending ? (
 <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
 ) : null}
 Sfinalizuj
 </Button>
 </div>
 </div>
 </DialogContent>
 </Dialog>
 ) : null}
 </>
 );
}
