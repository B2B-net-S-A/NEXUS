"use client";

// Zakładka „Pliki" profilu kandydata — lista załączników + upload nowych.
// 04.10.2026: klik w nazwę otwiera podgląd, reszta akcji (pobierz, rodzaj,
// główne CV, nieaktualne) w menu „⋯” wiersza; CV dla klientów (pliki
// „…B2B…” i CV z generatora) stoją osobno, zwinięte (decyzja D4).
// Wydzielona z `CandidateDetailV2.tsx` (plik ~4,7 tys. linii) przy dodawaniu
// write-pathu, żeby dało się ją renderować i testować w izolacji.

import * as React from "react";
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Loader2, MoreHorizontal, Upload } from "lucide-react";

import api, { extractErrorMsg } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { useCapability } from "@/hooks/useCapability";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import {
  FilePreviewModal,
  previewKind,
  downloadDocumentBlob,
  formatFileSize,
  fileIcon,
  fileTypeLabel,
  type CandidateDocument,
} from "@/components/v2/files/FilePreviewModal";
import { OrderDocumentsSection } from "@/components/OrderDocumentsSection";
import {
  fileAddedLabel,
  formatFileDate,
  sortCandidateFiles,
  splitClientCvFiles,
} from "@/lib/candidate-files";
import type { GeneratedCvItem } from "@/lib/api";
import { downloadGeneratedCv } from "@/components/v2/cv-generator/cv-generated-files";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

export function CandidateFilesTab({ candidateId }: { candidateId: number }) {
 const { showError, showToast } = useToast();
 const queryClient = useQueryClient();
 // POST /api/candidates/{id}/documents + PATCH .../documents/{doc_id} stoją na
 // CandidateWriteAccess. Ręczna lista ról gubiła tu `finance` (tier recruitera
 // od 19.08) — rejestr trzyma zbiór w jednym miejscu razem z nazwą guardu.
 // HoR ZOSTAJE poza: teczkę czyta (szerszy CandidateDocumentAccess), ale
 // upload dostałby 403.
 const canEditDocuments = useCapability("candidate.document.manage");
 const [previewDoc, setPreviewDoc] = useState<CandidateDocument | null>(null);
 const [uploadKind, setUploadKind] =
 useState<CandidateDocument["document_kind"]>("cv");
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
 outdated,
 }: {
 docId: number;
 documentKind?: CandidateDocument["document_kind"];
 isPrimary?: boolean;
 outdated?: boolean;
 }) =>
 api.patch(`/api/candidates/${candidateId}/documents/${docId}`, {
 ...(documentKind ? { document_kind: documentKind } : {}),
 ...(isPrimary !== undefined ? { is_primary: isPrimary } : {}),
 ...(outdated !== undefined ? { outdated } : {}),
 }),
 onSuccess: (_response, variables) => {
 void queryClient.invalidateQueries({
 queryKey: candidateQueryKeys.documents(candidateId),
 });
 void queryClient.invalidateQueries({
 queryKey: candidateQueryKeys.cvDocuments(candidateId),
 });
 void queryClient.invalidateQueries({
 queryKey: candidateQueryKeys.quickView(candidateId),
 });
 showToast(
 variables.outdated === true
 ? "Oznaczono jako nieaktualne."
 : variables.outdated === false
 ? "Cofnięto oznaczenie „nieaktualne”."
 : "Metadane dokumentu zaktualizowane.",
 "success",
 );
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

 // Główne CV pierwsze, potem najnowsze — także zaraz po zmianie, zanim
 // lista wróci z serwera.
 const docs = sortCandidateFiles(documents ?? []);

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
 <option value="cv">CV</option>
 <option value="cover_letter">List motywacyjny</option>
 <option value="certificate">Certyfikat</option>
 <option value="other">Inny</option>
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
 <ClientCvGroup candidateId={candidateId} files={[]} renderRow={() => null} />
 <OrderDocumentsSection candidateId={candidateId} />
 </div>
 );
 }

 const { own: ownDocs, client: clientDocs } = splitClientCvFiles(docs);
 const renderRow = (doc: CandidateDocument) => (
 <FileRow
 key={doc.id}
 doc={doc}
 canEdit={canEditDocuments}
 busy={metadataMutation.isPending}
 onPreview={() => handlePreview(doc)}
 onDownload={() => handleDownload(doc)}
 onChangeKind={(documentKind) =>
 metadataMutation.mutate({ docId: doc.id, documentKind })
 }
 onSetPrimary={() => metadataMutation.mutate({ docId: doc.id, isPrimary: true })}
 onToggleOutdated={() =>
 metadataMutation.mutate({ docId: doc.id, outdated: !doc.outdated_at })
 }
 />
 );

 return (
 <>
 <div className="space-y-3">
 {uploader}
 {ownDocs.length > 0 ? (
 <div className="divide-y divide-border rounded-lg border border-border">
 {ownDocs.map(renderRow)}
 </div>
 ) : (
 <p className="text-sm text-muted-foreground">
 Kandydat nie ma własnych plików — poniżej są tylko CV przygotowane dla klientów.
 </p>
 )}
 <ClientCvGroup candidateId={candidateId} files={clientDocs} renderRow={renderRow} />
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

const KIND_LABEL: Record<CandidateDocument["document_kind"], string> = {
 cv: "CV",
 cover_letter: "list motywacyjny",
 certificate: "certyfikat",
 other: "inny",
};

const KIND_OPTIONS: { value: CandidateDocument["document_kind"]; label: string }[] = [
 { value: "cv", label: "CV" },
 { value: "cover_letter", label: "List motywacyjny" },
 { value: "certificate", label: "Certyfikat" },
 { value: "other", label: "Inny" },
];

function FileRow({
 doc,
 canEdit,
 busy,
 onPreview,
 onDownload,
 onChangeKind,
 onSetPrimary,
 onToggleOutdated,
}: {
 doc: CandidateDocument;
 canEdit: boolean;
 busy: boolean;
 onPreview: () => void;
 onDownload: () => void;
 onChangeKind: (kind: CandidateDocument["document_kind"]) => void;
 onSetPrimary: () => void;
 onToggleOutdated: () => void;
}) {
 // Radix: akcja z menu po zamknięciu menu (issue 533 — fokus i okna).
 const later = (fn: () => void) => () => window.setTimeout(fn, 0);
 const typeLabel = fileTypeLabel(doc.content_type, doc.filename);
 const size = formatFileSize(doc.size_bytes);
 return (
 <div className="flex items-center gap-3 px-3 py-2.5" data-testid="candidate-file-row">
 {fileIcon(doc.content_type)}
 <div className="min-w-0 flex-1">
 <div className="flex flex-wrap items-baseline gap-2">
 <button
 type="button"
 onClick={onPreview}
 title="Otwórz podgląd pliku"
 className="min-w-0 truncate text-left text-sm font-medium text-foreground hover:text-primary hover:underline"
 >
 {doc.filename}
 </button>
 {doc.is_primary ? (
 <Badge size="sm" variant="success">
 główne CV
 </Badge>
 ) : null}
 {doc.outdated_at ? (
 <Badge
 size="sm"
 variant="neutral"
 title={[
 "Oznaczone jako nieaktualne",
 formatFileDate(doc.outdated_at),
 doc.outdated_by_name,
 ]
 .filter(Boolean)
 .join(" · ")}
 >
 nieaktualne
 </Badge>
 ) : null}
 <Badge size="sm" variant="neutral">
 {KIND_LABEL[doc.document_kind] ?? "inny"}
 </Badge>
 </div>
 <div className="mt-0.5 text-xs text-muted-foreground">
 <span>{fileAddedLabel(doc)}</span>
 {size ? (
 <>
 <span className="mx-1.5">·</span>
 <span>{size}</span>
 </>
 ) : null}
 {typeLabel ? (
 <>
 <span className="mx-1.5">·</span>
 <span>{typeLabel}</span>
 </>
 ) : null}
 </div>
 </div>
 <DropdownMenu modal={false}>
 <DropdownMenuTrigger asChild>
 <Button
 size="icon"
 variant="ghost"
 aria-label={`Akcje pliku ${doc.filename}`}
 disabled={busy}
 >
 <MoreHorizontal className="size-4" />
 </Button>
 </DropdownMenuTrigger>
 <DropdownMenuContent align="end" className="w-60">
 <DropdownMenuItem onSelect={later(onPreview)}>Podgląd</DropdownMenuItem>
 <DropdownMenuItem onSelect={later(onDownload)}>Pobierz</DropdownMenuItem>
 {canEdit ? (
 <>
 <DropdownMenuSeparator />
 <DropdownMenuLabel className="text-xs text-muted-foreground">Rodzaj</DropdownMenuLabel>
 <DropdownMenuRadioGroup
 value={doc.document_kind}
 onValueChange={(value) =>
 onChangeKind(value as CandidateDocument["document_kind"])
 }
 >
 {KIND_OPTIONS.map((option) => (
 <DropdownMenuRadioItem key={option.value} value={option.value}>
 {option.label}
 </DropdownMenuRadioItem>
 ))}
 </DropdownMenuRadioGroup>
 {doc.document_kind === "cv" && !doc.is_primary && !doc.outdated_at ? (
 <>
 <DropdownMenuSeparator />
 <DropdownMenuItem onSelect={later(onSetPrimary)}>
 Ustaw jako główne CV
 </DropdownMenuItem>
 </>
 ) : null}
 {!doc.is_primary ? (
 <DropdownMenuItem onSelect={later(onToggleOutdated)}>
 {doc.outdated_at
 ? "Cofnij oznaczenie „nieaktualne”"
 : "Oznacz jako nieaktualne"}
 </DropdownMenuItem>
 ) : null}
 </>
 ) : null}
 </DropdownMenuContent>
 </DropdownMenu>
 </div>
 );
}

/**
 * „CV dla klientów” (D4): pliki „…B2B…” z listy kandydata i CV wygenerowane
 * w NEXUSIE. Zwinięte z licznikiem — to dokumenty dla klienta, nie od
 * kandydata. Awaria listy z generatora nie chowa plików z teczki.
 */
function ClientCvGroup({
 candidateId,
 files,
 renderRow,
}: {
 candidateId: number;
 files: CandidateDocument[];
 renderRow: (doc: CandidateDocument) => React.ReactNode;
}) {
 const { showError } = useToast();
 const [open, setOpen] = useState(false);
 const generatedQuery = useQuery<GeneratedCvItem[]>({
 queryKey: ["candidate-generated-cvs", candidateId],
 queryFn: () =>
 api
 .get<GeneratedCvItem[]>("/api/cv-generator/generated", {
 params: { candidate_id: candidateId, limit: 50 },
 })
 .then((r) => (Array.isArray(r.data) ? r.data : [])),
 enabled: candidateId > 0,
 staleTime: 60_000,
 retry: false,
 });
 const generated = (generatedQuery.data ?? []).filter((item) => item.status === "ready");
 const total = files.length + generated.length;
 if (generatedQuery.isPending && files.length === 0) return null;
 if (total === 0 && !generatedQuery.isError) return null;

 return (
 <section aria-labelledby="candidate-client-cv-heading" className="rounded-lg border border-border">
 <button
 type="button"
 aria-expanded={open}
 aria-controls="candidate-client-cv-body"
 onClick={() => setOpen((value) => !value)}
 className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left"
 >
 <span id="candidate-client-cv-heading" className="text-sm font-medium text-foreground">
 CV dla klientów{" "}
 <span className="ml-0.5 tabular-nums text-muted-foreground">· {total}</span>
 </span>
 <ChevronDown
 className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")}
 aria-hidden
 />
 </button>
 {open ? (
 <div id="candidate-client-cv-body" className="border-t border-border">
 {files.length > 0 ? (
 <div className="divide-y divide-border">{files.map(renderRow)}</div>
 ) : null}
 {generatedQuery.isError ? (
 <p role="alert" className="px-3 py-2.5 text-sm text-destructive">
 Nie udało się wczytać CV z generatora.{" "}
 <button
 type="button"
 className="font-medium underline"
 onClick={() => void generatedQuery.refetch()}
 >
 Ponów
 </button>
 </p>
 ) : null}
 {generated.length > 0 ? (
 <ul className="divide-y divide-border border-t border-border" aria-label="CV z generatora">
 {generated.map((item) => (
 <li key={item.id} className="flex items-center gap-3 px-3 py-2.5 text-sm">
 <div className="min-w-0 flex-1">
 <p className="truncate font-medium text-foreground">{item.filename}</p>
 <p className="text-xs text-muted-foreground">
 {[
 "z generatora",
 item.job_title ?? item.client_name ?? null,
 item.language?.toUpperCase() ?? null,
 formatFileDate(item.created_at ?? null),
 item.created_by_name ?? null,
 ]
 .filter(Boolean)
 .join(" · ")}
 </p>
 </div>
 {item.can_download ? (
 <Button
 size="sm"
 variant="outline"
 onClick={async () => {
 const problem = await downloadGeneratedCv(item);
 if (problem) showError(problem);
 }}
 >
 Pobierz
 </Button>
 ) : null}
 </li>
 ))}
 </ul>
 ) : null}
 </div>
 ) : null}
 </section>
 );
}
