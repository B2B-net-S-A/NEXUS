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

 candidateName: string;
 jobTitle?: string;
} & ({ stageId: number; generatedId?: never } | { generatedId: number; stageId?: never });

function getErrorMessage(e: unknown): string {
 const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
 return typeof detail === "string" ? detail : e instanceof Error ? e.message : "Nie udało się wykonać operacji";
}

export function CVBrandedEditModal(props: Props) {
 return <CVBrandedEditContent key={props.generatedId !== undefined ? `generated-${props.generatedId}` : `stage-${props.stageId}`} {...props} />;
}

function CVBrandedEditContent({
 open,
 onOpenChange,
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
 const [pendingTemplate, setPendingTemplate] = useState<CVTemplate | null>(
 null,
 );
 const [pendingLanguage, setPendingLanguage] = useState<CVLanguage | null>(
 null,
 );

 const { data, isLoading } = useQuery<CVBrandedState>({
 queryKey: [scopeKey, stageId],
 queryFn: () =>
 editorApi.get(stageId).then((r) => r.data),
 enabled: open,
 });

 const editor = useEditor({
 extensions: [StarterKit, CvEditorSection],
 content: "",
 editorProps: {
 attributes: {
 class: "prose prose-sm max-w-none min-h-[400px] focus:outline-hidden border border-border rounded-lg bg-card p-4",
 },
 },
 });

 const sessionRef = useRef<CvDraftSession | null>(null);
 const loadedStage = useRef<number | null>(null);
 const replacingRef = useRef(false);
 const [saveState, setSaveState] = useState<CvSaveState>("saved");

 const loadState = (state: CVBrandedState) => {
   const session = new CvDraftSession(state.content_html ?? "<p></p>", state.edit_revision,
     state.status === "finalized", {
       save: (html, revision) => editorApi.update(stageId, {
         content_html: html, expected_revision: revision,
       }).then((r) => r.data),
       finalize: (html, revision) => editorApi.finalize(stageId, {
         content_html: html, expected_revision: revision,
       }).then((r) => r.data),
     }, (status) => {
       if (sessionRef.current === session) setSaveState(status);
     });
   sessionRef.current = session;
   loadedStage.current = stageId;
   setSaveState(session.state);
   editor?.commands.setContent(session.html, false);
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
   editor?.setEditable(!replacingRef.current && saveState !== "finalized" && saveState !== "finalizing");
 }, [editor, saveState]);

 useEffect(() => {
   if (!editor) return;
   const handler = () => sessionRef.current?.edit(editor.getHTML());
   editor.on("update", handler);
   return () => { editor.off("update", handler); };
 }, [editor]);

 const saveCurrent = async () => {
   try { await sessionRef.current?.save(); }
   catch (error) { showError(getErrorMessage(error)); }
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
   if (nextOpen) { onOpenChange(true); return; }
   if (replacingRef.current || sessionRef.current?.state === "finalizing") return;
   try {
     await sessionRef.current?.settle();
     await sessionRef.current?.save();
     while (sessionRef.current?.state === "unsaved") await sessionRef.current.save();
     onOpenChange(false);
   } catch (error) { showError(getErrorMessage(error)); }
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
     await sessionRef.current.finalize();
     return editorApi.get(stageId);
   },
   onSuccess: (response) => {
     loadState(response.data);
     showSuccess("Zapisano i zatwierdzono bieżącą treść CV");
     setConfirmFinalize(false);
   },
   onError: (e) => showError(getErrorMessage(e)),
 });
 const newDraftMut = useMutation({
   mutationFn: () => editorApi.newDraft(stageId, sessionRef.current!.revision),
   onSuccess: (response) => loadState(response.data),
   onError: (e) => showError(getErrorMessage(e)),
 });

 const handleTemplateChange = (val: CVTemplate) => {
 if (data?.status === "finalized") return;
 if (val === data?.template) return;
 setPendingTemplate(val);
 };

 const handleLanguageChange = (val: CVLanguage) => {
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
 disabled={isFinalized || data?.from_generator}
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
 disabled={isFinalized || data?.from_generator}
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
    error: "Błąd zapisu — poprawki pozostają w edytorze", finalizing: "Zatwierdzanie…",
    finalized: `Zatwierdzona wersja ${data?.version ?? ""}` }[saveState]}
 </span>
 {saveState === "error" ? <Button size="sm" variant="outline" onClick={() => void saveCurrent()}>Ponów zapis</Button> : null}

 </div>
 </div>
 </div>

 <div className="flex-1 overflow-auto p-5 bg-background">
 {isLoading ? (
 <div className="text-center text-sm text-muted-foreground py-10">
 Ładowanie…
 </div>
 ) : (
 <EditorContent editor={editor} />
 )}
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
 disabled={finalizeMut.isPending}
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
