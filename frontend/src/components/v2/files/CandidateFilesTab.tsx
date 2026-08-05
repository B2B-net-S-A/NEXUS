"use client";

// Zakładka „Pliki" profilu kandydata — lista załączników + upload nowych.
// Wydzielona z `CandidateDetailV2.tsx` (plik ~4,7 tys. linii) przy dodawaniu
// write-pathu, żeby dało się ją renderować i testować w izolacji.

import * as React from "react";
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Eye, Loader2, Upload } from "lucide-react";

import api, { extractErrorMsg } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { hasRole, useAuthStore } from "@/store/auth";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import {
  FilePreviewModal,
  previewKind,
  downloadDocumentBlob,
  formatFileSize,
  fileIcon,
  type CandidateDocument,
} from "@/components/v2/files/FilePreviewModal";
import { OrderDocumentsSection } from "@/components/OrderDocumentsSection";

export function CandidateFilesTab({ candidateId }: { candidateId: number }) {
 const { showError, showToast } = useToast();
 const queryClient = useQueryClient();
 const currentUser = useAuthStore((state) => state.user);
 const canEditDocuments = hasRole(
 currentUser,
 "admin",
 "delivery_lead",
 "tac",
 "recruiter",
 "sourcer",
 );
 const [previewDoc, setPreviewDoc] = useState<CandidateDocument | null>(null);
 const [uploadKind, setUploadKind] =
 useState<CandidateDocument["document_kind"]>("other");
 const fileInputRef = useRef<HTMLInputElement>(null);
 const { data: documents, isLoading, error } = useQuery<CandidateDocument[]>({
 queryKey: candidateQueryKeys.documents(candidateId),
 queryFn: async () => {
 const res = await api.get<CandidateDocument[]>(
 `/api/candidates/${candidateId}/documents`,
 );
 return res.data;
 },
 staleTime: 30_000,
 });
 const metadataMutation = useMutation({
 mutationFn: ({
 docId,
 documentKind,
 isPrimary,
 }: {
 docId: number;
 documentKind?: CandidateDocument["document_kind"];
 isPrimary?: boolean;
 }) =>
 api.patch(`/api/candidates/${candidateId}/documents/${docId}`, {
 ...(documentKind ? { document_kind: documentKind } : {}),
 ...(isPrimary !== undefined ? { is_primary: isPrimary } : {}),
 }),
 onSuccess: () => {
 void queryClient.invalidateQueries({
 queryKey: candidateQueryKeys.documents(candidateId),
 });
 void queryClient.invalidateQueries({
 queryKey: candidateQueryKeys.cvDocuments(candidateId),
 });
 void queryClient.invalidateQueries({
 queryKey: candidateQueryKeys.quickView(candidateId),
 });
 showToast("Metadane dokumentu zaktualizowane.", "success");
 },
 onError: (mutationError) =>
 showError(
 extractErrorMsg(mutationError) ||
 "Nie udało się zaktualizować metadanych dokumentu.",
 ),
 });

 const uploadMutation = useMutation({
 // Sekwencyjnie, nie Promise.all — backend dedupikuje po SHA i przy CV
 // przestawia flagę primary, więc równoległe zapisy tego samego kandydata
 // ścigałyby się o ten sam wiersz.
 mutationFn: async (files: File[]) => {
 for (const file of files) {
 const fd = new FormData();
 fd.append("file", file);
 fd.append("document_kind", uploadKind);
 await api.post(`/api/candidates/${candidateId}/documents`, fd, {
 headers: { "Content-Type": "multipart/form-data" },
 });
 }
 return files.length;
 },
 // Odświeżamy w onSettled, nie w onSuccess: przy wielu plikach błąd na
 // trzecim nie unieważnia faktu, że dwa pierwsze już się zapisały — lista
 // musi je pokazać, inaczej wyglądają na utracone.
 onSettled: () => {
 for (const queryKey of [
 candidateQueryKeys.documents(candidateId),
 candidateQueryKeys.cvDocuments(candidateId),
 candidateQueryKeys.quickView(candidateId),
 candidateQueryKeys.detail(candidateId),
 ]) {
 void queryClient.invalidateQueries({ queryKey });
 }
 },
 onSuccess: (count: number) =>
 showToast(
 count === 1 ? "Plik dodany." : `Dodano pliki: ${count}.`,
 "success",
 ),
 onError: (mutationError) =>
 showError(
 extractErrorMsg(mutationError) || "Nie udało się dodać pliku.",
 ),
 });

 function handleFilesPicked(event: React.ChangeEvent<HTMLInputElement>) {
 const files = Array.from(event.target.files ?? []);
 // Reset od razu — inaczej wybranie tego samego pliku po nieudanym
 // uploadzie nie odpaliłoby `onChange` drugi raz.
 event.target.value = "";
 if (files.length === 0) return;
 uploadMutation.mutate(files);
 }

 function handlePreview(doc: CandidateDocument) {
 // DOCX nie renderuje się natywnie w przeglądarce — `window.open` na blobie
 // DOCX wymusza download (to był zgłoszony bug: „Podgląd" pobierał CV).
 // Otwieramy in-app modal (PDF/obraz/DOCX). Formaty bez podglądu (legacy
 // .doc, xlsx, odt, pages…) pobieramy od razu.
 if (previewKind(doc) === "unsupported") {
 showToast(
 "Podgląd niedostępny dla tego formatu — pobieram plik.",
 "success",
 );
 handleDownload(doc);
 return;
 }
 setPreviewDoc(doc);
 }

 async function handleDownload(doc: CandidateDocument) {
 try {
 await downloadDocumentBlob(candidateId, doc);
 } catch {
 showError("Nie udało się pobrać pliku.");
 }
 }

 const docs = documents ?? [];

 // Uploader renderuje się w każdym stanie listy (ładowanie, błąd, pusto) —
 // pusty profil to dokładnie ten moment, w którym trzeba dodać pierwszy plik.
 const uploader = canEditDocuments ? (
 <div className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-border bg-background/30 p-3">
 <label
 htmlFor="candidate-document-kind"
 className="text-xs font-medium text-muted-foreground"
 >
 Rodzaj
 </label>
 <select
 id="candidate-document-kind"
 value={uploadKind}
 onChange={(event) =>
 setUploadKind(
 event.target.value as CandidateDocument["document_kind"],
 )
 }
 disabled={uploadMutation.isPending}
 className="rounded-md border border-border bg-card px-2 py-1 text-xs text-foreground"
 >
 <option value="other">Inny</option>
 <option value="cv">CV</option>
 <option value="cover_letter">List motywacyjny</option>
 <option value="certificate">Certyfikat</option>
 </select>
 <input
 ref={fileInputRef}
 type="file"
 multiple
 className="sr-only"
 onChange={handleFilesPicked}
 data-testid="candidate-document-upload-input"
 />
 <button
 type="button"
 onClick={() => fileInputRef.current?.click()}
 disabled={uploadMutation.isPending}
 className="inline-flex items-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--primary-foreground))] hover:opacity-90 disabled:opacity-50"
 >
 {uploadMutation.isPending ? (
 <Loader2 className="h-3.5 w-3.5 animate-spin" />
 ) : (
 <Upload className="h-3.5 w-3.5" />
 )}
 {uploadMutation.isPending ? "Wysyłanie…" : "Dodaj plik"}
 </button>
 <span className="text-xs text-muted-foreground">
 PDF, DOC(X), ODT, RTF, TXT, XLS(X), CSV, PPT(X), obrazy, ZIP
 </span>
 </div>
 ) : null;

 if (isLoading) {
 return (
 <div className="space-y-3">
 {uploader}
 <div className="text-sm text-muted-foreground py-6 text-center">
 Ładowanie plików…
 </div>
 </div>
 );
 }

 if (error) {
 return (
 <div className="space-y-3">
 {uploader}
 <div className="text-sm text-[hsl(var(--accent-error))] py-6 text-center">
 Błąd ładowania plików.
 </div>
 </div>
 );
 }

 if (docs.length === 0) {
 return (
 <div className="space-y-3">
 {uploader}
 <div className="text-sm text-muted-foreground py-6 text-center">
 {canEditDocuments
 ? "Brak plików. Dodaj CV, certyfikat lub inny dokument."
 : "Brak plików."}
 </div>
 <OrderDocumentsSection candidateId={candidateId} />
 </div>
 );
 }

 return (
 <>
 <div className="space-y-3">
 {uploader}
 <div className="space-y-2">
 {docs.map((doc) => (
 <div
 key={doc.id}
 className="flex items-center gap-3 rounded-lg bg-background/40 border border-border p-3 hover:bg-background/60 transition-colors"
 >
 {fileIcon(doc.content_type)}
 <div className="flex-1 min-w-0">
 <div className="flex items-baseline gap-2 flex-wrap">
 <span className="font-medium text-sm text-foreground truncate">
 {doc.filename}
 </span>
 {doc.is_primary && (
 <Badge size="sm" variant="success">
 primary
 </Badge>
 )}
 <Badge size="sm" variant="neutral">
 {doc.document_kind === "cv"
 ? "CV"
 : doc.document_kind === "cover_letter"
 ? "list motywacyjny"
 : doc.document_kind === "certificate"
 ? "certyfikat"
 : "inny"}
 </Badge>
 {doc.external_source === "traffit" && (
 <Badge size="sm" variant="info">
 z Traffita
 </Badge>
 )}
 </div>
 <div className="text-xs text-muted-foreground mt-0.5">
 {formatFileSize(doc.size_bytes)}
 {doc.uploaded_at && (
 <>
 <span className="mx-1.5">·</span>
 <span>
 {new Date(doc.uploaded_at).toLocaleDateString("pl-PL")}
 </span>
 </>
 )}
 {doc.content_type && (
 <>
 <span className="mx-1.5">·</span>
 <span>{doc.content_type}</span>
 </>
 )}
 </div>
 </div>
 <div className="flex items-center gap-3 shrink-0">
 {canEditDocuments ? (
 <select
 value={doc.document_kind}
 onChange={(event) =>
 metadataMutation.mutate({
 docId: doc.id,
 documentKind: event.target
 .value as CandidateDocument["document_kind"],
 })
 }
 disabled={metadataMutation.isPending}
 aria-label={`Rodzaj dokumentu ${doc.filename}`}
 className="rounded-md border border-border bg-card px-2 py-1 text-xs text-foreground"
 >
 <option value="cv">CV</option>
 <option value="cover_letter">List motywacyjny</option>
 <option value="certificate">Certyfikat</option>
 <option value="other">Inny</option>
 </select>
 ) : null}
 {canEditDocuments && doc.document_kind === "cv" && !doc.is_primary ? (
 <button
 type="button"
 onClick={() =>
 metadataMutation.mutate({ docId: doc.id, isPrimary: true })
 }
 disabled={metadataMutation.isPending}
 className="text-xs font-medium text-[hsl(var(--accent-primary))] hover:underline disabled:opacity-50"
 >
 Ustaw jako primary
 </button>
 ) : null}
 <button
 type="button"
 onClick={() => handlePreview(doc)}
 className="inline-flex items-center gap-1 text-sm text-[hsl(var(--accent-primary))] hover:underline"
 title="Otwórz podgląd pliku"
 >
 <Eye className="h-3.5 w-3.5" />
 Podgląd
 </button>
 <button
 type="button"
 onClick={() => handleDownload(doc)}
 className="inline-flex items-center gap-1 text-sm text-[hsl(var(--accent-primary))] hover:underline"
 title="Pobierz plik na dysk"
 >
 <Download className="h-3.5 w-3.5" />
 Pobierz
 </button>
 </div>
 </div>
 ))}
 </div>
 <OrderDocumentsSection candidateId={candidateId} />
 </div>
 <FilePreviewModal
 doc={previewDoc?.document_kind === "cv" ? undefined : previewDoc}
 documents={
 previewDoc?.document_kind === "cv"
 ? docs.filter((document) => document.document_kind === "cv")
 : undefined
 }
 initialDocumentId={
 previewDoc?.document_kind === "cv" ? previewDoc.id : null
 }
 candidateId={candidateId}
 onClose={() => setPreviewDoc(null)}
 onDownload={handleDownload}
 />
 </>
 );
}
