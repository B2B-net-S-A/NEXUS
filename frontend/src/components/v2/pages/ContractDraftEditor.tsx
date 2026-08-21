"use client";

/**
 * Edytor draftu umowy — WYDZIELONY, żeby TipTap/ProseMirror nie siedział
 * w bundlu trasy `/candidates/[id]`.
 *
 * Profil kandydata to najcięższa trasa w aplikacji i ekran otwierany
 * dziesiątki razy dziennie przy triażu bazy 49 tys. kandydatów. Ten edytor
 * renderuje się wyłącznie po trzech świadomych krokach (zakładka Dokumenty →
 * podwidok Umowy → istniejący kontrakt w statusie `draft`), więc zdecydowana
 * większość wizyt płaciła za pobranie i sparsowanie całego drzewa ProseMirror,
 * którego nigdy nie wykonała. Import z poziomu modułu w `CandidateDetailV2`
 * gwarantował, że koszt ponosi KAŻDE zimne otwarcie profilu.
 *
 * Konsument ładuje ten moduł przez `next/dynamic` z `ssr: false` — edytor i tak
 * montuje się dopiero po stronie klienta.
 */

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { AlertTriangle, CheckCircle2, Printer, RefreshCcw } from "lucide-react";

import { contractsApi, type ContractDraftResponse } from "@/lib/api";
import { openAuthenticatedFile } from "@/lib/authenticated-files";
import { formatRelativeTime } from "@/lib/utils";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfirmModal } from "./ConfirmModal";

export function DraftEditor({
 contractId,
 candidateName,
 contractMeta,
}: {
 contractId: number;
 candidateName: string;
 contractMeta: any;
}) {
 const queryClient = useQueryClient();
 const { showSuccess, showError } = useToast();
 const [confirmFinalize, setConfirmFinalize] = useState(false);
 const [confirmTemplateId, setConfirmTemplateId] = useState<number | null>(
 null,
 );

 const { data, isLoading } = useQuery<ContractDraftResponse>({
 queryKey: ["contract-draft", contractId],
 queryFn: () => contractsApi.draft.get(contractId).then((r) => r.data),
 });

 const editor = useEditor({
 extensions: [StarterKit],
 content: "",
 editorProps: {
 attributes: {
 class: "prose prose-sm max-w-none min-h-[400px] focus:outline-hidden border border-border rounded-lg bg-card p-4",
 },
 },
 });

 // Hydrate editor when draft is loaded the first time / after re-render swap.
 const lastLoadedSig = useRef<string | null>(null);
 useEffect(() => {
 if (!editor || !data) return;
 const sig = `${data.template_id ??""}:${data.updated_at ??""}`;
 if (sig === lastLoadedSig.current) return;
 lastLoadedSig.current = sig;
 editor.commands.setContent(data.content_html ??"<p></p>", false);
 }, [editor, data]);

 // Debounced autosave for manual edits.
 const dirtyRef = useRef(false);
 const saveMutation = useMutation({
 mutationFn: (html: string) =>
 contractsApi.draft.update(contractId, { content_html: html }),
 onSuccess: () => {
 showSuccess("Zapisano draft");
 queryClient.invalidateQueries({ queryKey: ["contract-draft", contractId] });
 },
 onError: () => showError("Nie udało się zapisać draftu"),
 });

 useEffect(() => {
 if (!editor) return;
 const handler = () => {
 dirtyRef.current = true;
 };
 editor.on("update", handler);
 return () => {
 editor.off("update", handler);
 };
 }, [editor]);

 useEffect(() => {
 if (!editor) return;
 const id = setInterval(() => {
 if (dirtyRef.current && !saveMutation.isPending) {
 dirtyRef.current = false;
 saveMutation.mutate(editor.getHTML());
 }
 }, 2000);
 return () => clearInterval(id);
 }, [editor, saveMutation]);

 const swapTemplate = useMutation({
 mutationFn: (templateId: number) =>
 contractsApi.draft.update(contractId, { template_id: templateId }),
 onSuccess: () => {
 showSuccess("Wczytano nowy szablon");
 lastLoadedSig.current = null; // force editor re-hydration
 queryClient.invalidateQueries({ queryKey: ["contract-draft", contractId] });
 },
 onError: () => showError("Nie udało się wczytać szablonu"),
 });

 const finalize = useMutation({
 mutationFn: () => contractsApi.draft.finalize(contractId),
 onSuccess: () => {
 showSuccess("Umowa sfinalizowana — status: aktywna");
 setConfirmFinalize(false);
 queryClient.invalidateQueries({
 queryKey: ["candidate-contracts"],
 });
 queryClient.invalidateQueries({
 queryKey: ["contract-draft", contractId],
 });
 },
 onError: (err: unknown) => {
 const detail =
 err && typeof err === "object" &&"response" in err
 ? (err as any).response?.data?.detail
 : null;
 if (detail && typeof detail === "object" && Array.isArray(detail.missing)) {
 showError(`Uzupełnij wymagane pola: ${detail.missing.join(",")}`);
 } else {
 showError("Nie udało się sfinalizować draftu");
 }
 },
 });

 if (isLoading || !data) {
 return (
 <Card variant="default" size="md">
 <CardContent className="py-6 text-center text-sm text-muted-foreground">
 Ładowanie draftu…
 </CardContent>
 </Card>
 );
 }

 const lastSaved = data.updated_at
 ? `zapisano ${formatRelativeTime(data.updated_at)}`
 :"jeszcze nie zapisano";

 return (
 <Card variant="default" size="md">
 <CardContent className="space-y-3">
 <div className="flex items-start justify-between gap-3 flex-wrap">
 <div className="min-w-0">
 <div className="text-sm text-muted-foreground">
 Draft umowy dla <strong>{candidateName}</strong> — kontrakt #
 {contractId}
 {contractMeta.client_name
 ? ` (${contractMeta.client_name})`
 :""}
 </div>
 <div className="text-xs text-muted-foreground">
 {lastSaved}
 {data.updated_by_name ? ` przez ${data.updated_by_name}` :""}
 </div>
 </div>
 <div className="flex items-center gap-2 flex-wrap">
 <select
 className="rounded-lg border border-border bg-card px-2 py-1 text-xs"
 value={data.template_id ??""}
 onChange={(e) => {
 const newId = Number(e.target.value);
 if (newId && newId !== data.template_id) {
 setConfirmTemplateId(newId);
 }
 }}
 >
 <option value="">— wybierz szablon —</option>
 {data.available_templates.map((t) => (
 <option key={t.id} value={t.id}>
 {t.name}
 {t.is_default ?"(domyślny)" :""}
 </option>
 ))}
 </select>
 <Button
 size="sm"
 variant="outline"
 onClick={async () => {
 // Print view is Bearer-guarded — raw window.open → white
 // "Not authenticated" page. Fetch HTML with auth → blob URL.
 try {
 await openAuthenticatedFile(
 `/api/contracts/${contractId}/draft/render-pdf`,
 "text/html",
 );
 } catch {
 showError("Nie udało się otworzyć umowy do druku.");
 }
 }}
 disabled={!data.content_html}
 title="Otwiera HTML w nowej karcie z auto-print → Save as PDF"
 >
 <Printer className="h-3.5 w-3.5" /> Drukuj / PDF
 </Button>
 <Button
 size="sm"
 onClick={() => setConfirmFinalize(true)}
 disabled={!data.content_html || finalize.isPending}
 >
 <CheckCircle2 className="h-3.5 w-3.5" /> Sfinalizuj umowę
 </Button>
 </div>
 </div>

 {data.available_templates.length === 0 && (
 <div className="flex items-center gap-1 text-xs text-warning-muted-foreground">
 <AlertTriangle className="h-3.5 w-3.5" />
 Brak szablonu dla typu <code>{contractMeta.contract_type}</code>.
 Dodaj szablon w panelu administracyjnym.
 </div>
 )}

 <EditorContent editor={editor} />

 {saveMutation.isPending && (
 <div className="text-xs text-muted-foreground flex items-center gap-1">
 <RefreshCcw className="h-3 w-3 animate-spin" /> Zapisywanie…
 </div>
 )}
 </CardContent>

 {/* Modal: confirm template swap (overwrites manual edits) */}
 {confirmTemplateId !== null && (
 <ConfirmModal
 title="Wczytać nowy szablon ? "
 message="Przełączenie szablonu nadpisze obecną treść draftu. Zapisane edycje zostaną stracone."
 confirmLabel="Wczytaj szablon"
 onConfirm={() => {
 swapTemplate.mutate(confirmTemplateId);
 setConfirmTemplateId(null);
 }}
 onCancel={() => setConfirmTemplateId(null)}
 />
 )}

 {/* Modal: confirm finalize */}
 {confirmFinalize && (
 <ConfirmModal
 title="Sfinalizować draft ? "
 message="Bieżąca treść zostanie zapisana jako dokument umowy, a status kontraktu zmieni się z draft na active. Edycja w tym widoku nie będzie już możliwa."
 confirmLabel={finalize.isPending ?"Finalizuję…" :"Tak, finalizuj"}
 onConfirm={() => finalize.mutate()}
 onCancel={() => setConfirmFinalize(false)}
 />
 )}
 </Card>
 );
}
