"use client";

// Sekcja „Pliki” zakładki „Dokumenty” profilu kandydata — lista plików
// i upload nowych.
// 04.10.2026: klik w nazwę otwiera podgląd, reszta akcji (pobierz, rodzaj,
// główne CV, nieaktualne) w menu „⋯” wiersza.
// 13.10.2026: „Usuń z profilu” w tym samym menu — admin i Head of Recruitment.
// 13.10.2026 (E5): pliki w trzech grupach — „CV kandydata”, „CV wysłane
// klientom” (pliki „…B2B…”, pliki z kodem rekrutacji osoby i CV
// z generatora), „Załączniki i formularze” (`groupCandidateFiles`).
// Formularz dodawania rozwija „Dodaj plik” w nagłówku; profil bez plików
// pokazuje go od razu.
// Wydzielona z `CandidateDetailV2.tsx` (plik ~4,7 tys. linii) przy dodawaniu
// write-pathu, żeby dało się ją renderować i testować w izolacji.

import * as React from "react";
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, MoreHorizontal, Upload } from "lucide-react";

import api, { extractErrorMsg } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { useCapability } from "@/hooks/useCapability";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { SectionHeading } from "@/components/v2/candidate-profile/profile-shared";
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
  groupCandidateFiles,
  sortCandidateFiles,
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
import { Checkbox } from "@/components/ui/checkbox";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";

/** Grupa z większą liczbą plików pokazuje tyle wierszy + „Pokaż wszystkie”. */
const GROUP_PREVIEW = 3;

export function CandidateFilesTab({
 candidateId,
 recruitmentCodes = [],
}: {
 candidateId: number;
 /** Kody rekrutacji osoby (`recruitmentCodes()` z `lib/candidate-files`) — plik z kodem w nazwie to CV wysłane klientowi. */
 recruitmentCodes?: readonly string[];
}) {
 const { showError, showToast } = useToast();
 const queryClient = useQueryClient();
 // POST /api/candidates/{id}/documents + PATCH .../documents/{doc_id} stoją na
 // CandidateWriteAccess. Ręczna lista ról gubiła tu `finance` (tier recruitera
 // od 19.08) — rejestr trzyma zbiór w jednym miejscu razem z nazwą guardu.
 // HoR ZOSTAJE poza: teczkę czyta (szerszy CandidateDocumentAccess), ale
 // upload dostałby 403.
 const canEditDocuments = useCapability("candidate.document.manage");
 // DELETE .../documents/{doc_id} stoi na węższym CandidateDocumentRemoveAccess
 // (admin, Head of Recruitment) — rekruter wgrywa i oznacza, ale nie usuwa.
 const canRemoveDocuments = useCapability("candidate.document.remove");
 const { askConfirm, confirmDialog } = useConfirmV2();
 const [previewDoc, setPreviewDoc] = useState<CandidateDocument | null>(null);
 const [uploadKind, setUploadKind] =
 useState<CandidateDocument["document_kind"]>("cv");
 // Nowe CV domyślnie staje się głównym (decyzja Artura, 12.10.2026): serwer
 // czyta modelem i odświeża profil wyłącznie z głównego CV — bez tego plik
 // tylko leżał na liście. Odznaczone = sam plik, np. wersja angielska obok
 // polskiej.
 const [cvAsPrimary, setCvAsPrimary] = useState(true);
 // `null` = domyślnie: formularz otwarty tylko na profilu bez plików.
 const [uploaderToggle, setUploaderToggle] = useState<boolean | null>(null);
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
 // Flaga tylko dla CV — przy innym rodzaju serwer odpowiada 422.
 const madePrimary = uploadKind === "cv" && cvAsPrimary;
 for (const [index, file] of files.entries()) {
 const fd = new FormData();
 fd.append("file", file);
 fd.append("document_kind", uploadKind);
 // Przy kilku plikach głównym zostaje ostatni: każde główne CV to osobny
 // odczyt modelem, a główne i tak jest jedno.
 if (madePrimary && index === files.length - 1) {
 fd.append("is_primary", "true");
 }
 await api.post(`/api/candidates/${candidateId}/documents`, fd, {
 headers: { "Content-Type": "multipart/form-data" },
 });
 }
 return { count: files.length, madePrimary };
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
 onSuccess: ({ count, madePrimary }: { count: number; madePrimary: boolean }) => {
 // Po udanym dodaniu formularz wraca do stanu domyślnego (zwinięty, gdy
 // lista ma już pliki).
 setUploaderToggle(null);
 const added = count === 1 ? "Plik dodany." : `Dodano pliki: ${count}.`;
 showToast(
 madePrimary
 ? `${count === 1 ? "CV dodane jako główne." : `${added} Ostatnie CV jest główne.`} AI czyta je w tle — profil odświeży się za około minutę.`
 : added,
 "success",
 );
 },
 onError: (mutationError) =>
 showError(
 extractErrorMsg(mutationError) || "Nie udało się dodać pliku.",
 ),
 });

 const removeMutation = useMutation({
 mutationFn: (docId: number) =>
 api.delete(`/api/candidates/${candidateId}/documents/${docId}`),
 onSuccess: () => {
 // `detail` też: usunięcie jedynego CV zdejmuje z profilu nazwę pliku CV.
 for (const queryKey of [
 candidateQueryKeys.documents(candidateId),
 candidateQueryKeys.cvDocuments(candidateId),
 candidateQueryKeys.quickView(candidateId),
 candidateQueryKeys.detail(candidateId),
 ]) {
 void queryClient.invalidateQueries({ queryKey });
 }
 showToast("Plik usunięty z profilu.", "success");
 },
 onError: (mutationError) =>
 showError(apiErrorMessage(mutationError, "Nie udało się usunąć pliku.")),
 });

 async function handleRemove(doc: CandidateDocument) {
 // Główne CV też wolno usunąć. Następcy serwer nie wybiera sam (nowe główne
 // CV odświeża profil odczytem AI), więc okno mówi, co zostaje.
 const confirmed = await askConfirm({
 title: "Usunąć plik z profilu?",
 description: [
 `„${doc.filename}” zniknie z profilu, podglądu i generatora CV. Kopie zapisane w rekrutacjach zostają.`,
 doc.is_primary
 ? "To główne CV — profil zostanie bez głównego CV, a dane odczytane z niego wcześniej zostają."
 : null,
 "W razie pomyłki wgraj plik ponownie.",
 ]
 .filter(Boolean)
 .join(" "),
 confirmLabel: "Usuń z profilu",
 variant: "destructive",
 });
 if (confirmed) removeMutation.mutate(doc.id);
 }

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
 // Pusty profil to dokładnie ten moment, w którym trzeba dodać pierwszy plik —
 // tam formularz stoi od razu. Przycisk w nagłówku działa w każdym stanie
 // listy (ładowanie, błąd, pusto).
 const uploaderOpen = uploaderToggle ?? (documents !== undefined && documents.length === 0);

 const header = (
 <SectionHeading
 id="candidate-files-heading"
 action={
 canEditDocuments ? (
 <Button
 size="sm"
 variant="outline"
 aria-expanded={uploaderOpen}
 aria-controls="candidate-files-uploader"
 onClick={() => setUploaderToggle(!uploaderOpen)}
 >
 <Upload className="size-3.5" />
 Dodaj plik
 </Button>
 ) : null
 }
 >
 Pliki
 </SectionHeading>
 );

 const uploader = canEditDocuments && uploaderOpen ? (
 <div
 id="candidate-files-uploader"
 className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-border bg-background/30 p-3"
 >
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
 {uploadKind === "cv" ? (
 <label
 htmlFor="candidate-document-primary"
 className="inline-flex items-center gap-1.5 text-xs text-foreground"
 >
 <Checkbox
 id="candidate-document-primary"
 checked={cvAsPrimary}
 onCheckedChange={(checked) => setCvAsPrimary(checked === true)}
 disabled={uploadMutation.isPending}
 />
 Ustaw jako główne CV (AI odświeży profil)
 </label>
 ) : null}
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
 {uploadMutation.isPending ? "Wysyłanie…" : "Wybierz pliki"}
 </button>
 <span className="text-xs text-muted-foreground">
 PDF, DOC(X), ODT, RTF, TXT, XLS(X), CSV, PPT(X), obrazy, ZIP
 </span>
 </div>
 ) : null;

 if (isLoading) {
 return (
 <div className="space-y-3">
 {header}
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
 {header}
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
 {header}
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

 const groups = groupCandidateFiles(docs, recruitmentCodes);
 const renderRow = (doc: CandidateDocument) => (
 <FileRow
 key={doc.id}
 doc={doc}
 canEdit={canEditDocuments}
 canRemove={canRemoveDocuments}
 busy={metadataMutation.isPending || removeMutation.isPending}
 onPreview={() => handlePreview(doc)}
 onDownload={() => handleDownload(doc)}
 onChangeKind={(documentKind) =>
 metadataMutation.mutate({ docId: doc.id, documentKind })
 }
 onSetPrimary={() => metadataMutation.mutate({ docId: doc.id, isPrimary: true })}
 onToggleOutdated={() =>
 metadataMutation.mutate({ docId: doc.id, outdated: !doc.outdated_at })
 }
 onRemove={() => void handleRemove(doc)}
 />
 );

 return (
 <>
 <div className="space-y-3">
 {header}
 {uploader}
 {/* Główne CV zawsze tutaj — grupa bez skracania listy. */}
 <FileGroup
 id="candidate-files-own-heading"
 title="CV kandydata"
 rows={groups.own.map(renderRow)}
 empty="Brak CV od kandydata."
 />
 <ClientCvGroup candidateId={candidateId} files={groups.client} renderRow={renderRow} />
 {groups.attachments.length > 0 ? (
 <FileGroup
 id="candidate-files-attachments-heading"
 title="Załączniki i formularze"
 rows={groups.attachments.map(renderRow)}
 limit={GROUP_PREVIEW}
 />
 ) : null}
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
 {confirmDialog}
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
 canRemove,
 busy,
 onPreview,
 onDownload,
 onChangeKind,
 onSetPrimary,
 onToggleOutdated,
 onRemove,
}: {
 doc: CandidateDocument;
 canEdit: boolean;
 canRemove: boolean;
 busy: boolean;
 onPreview: () => void;
 onDownload: () => void;
 onChangeKind: (kind: CandidateDocument["document_kind"]) => void;
 onSetPrimary: () => void;
 onToggleOutdated: () => void;
 onRemove: () => void;
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
 {canRemove ? (
 <>
 <DropdownMenuSeparator />
 <DropdownMenuItem
 onSelect={later(onRemove)}
 className="text-destructive focus:text-destructive"
 >
 Usuń z profilu
 </DropdownMenuItem>
 </>
 ) : null}
 </DropdownMenuContent>
 </DropdownMenu>
 </div>
 );
}


/**
 * Grupa plików z nagłówkiem i licznikiem. Z `limit` pokazuje tyle wierszy
 * i „Pokaż wszystkie (N)”; bez niego całą listę.
 */
function FileGroup({
 id,
 title,
 rows,
 limit,
 empty,
 notice,
}: {
 id: string;
 title: string;
 rows: React.ReactNode[];
 limit?: number;
 empty?: React.ReactNode;
 notice?: React.ReactNode;
}) {
 const [showAll, setShowAll] = useState(false);
 const canCollapse = limit !== undefined && rows.length > limit;
 const visible = canCollapse && !showAll ? rows.slice(0, limit) : rows;
 return (
 <section aria-labelledby={id} className="rounded-lg border border-border">
 <h4
 id={id}
 className="border-b border-border px-3 py-2 text-sm font-medium text-foreground"
 >
 {title}{" "}
 <span className="ml-0.5 tabular-nums text-muted-foreground">· {rows.length}</span>
 </h4>
 {rows.length > 0 ? (
 <div className="divide-y divide-border">{visible}</div>
 ) : empty ? (
 <p className="px-3 py-2.5 text-sm text-muted-foreground">{empty}</p>
 ) : null}
 {notice}
 {canCollapse ? (
 <button
 type="button"
 aria-expanded={showAll}
 onClick={() => setShowAll((value) => !value)}
 className="flex min-h-9 w-full items-center border-t border-border px-3 text-xs font-medium text-primary hover:underline"
 >
 {showAll ? "Pokaż mniej" : `Pokaż wszystkie (${rows.length})`}
 </button>
 ) : null}
 </section>
 );
}

/**
 * „CV wysłane klientom” (D4 z 04.10.2026, grupa od 13.10.2026): pliki
 * „…B2B…” i pliki z kodem rekrutacji osoby z teczki oraz CV wygenerowane
 * w NEXUSIE. Awaria listy z generatora nie chowa plików z teczki.
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
 if (generatedQuery.isPending && files.length === 0) return null;
 const rows = [
 ...files.map(renderRow),
 ...generated.map((item) => (
 <div key={`generated-${item.id}`} className="flex items-center gap-3 px-3 py-2.5 text-sm">
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
 const problem = await downloadGeneratedCv(item, "docx", "files");
 if (problem) showError(problem);
 }}
 >
 Pobierz
 </Button>
 ) : null}
 </div>
 )),
 ];
 if (rows.length === 0 && !generatedQuery.isError) return null;

 return (
 <FileGroup
 id="candidate-client-cv-heading"
 title="CV wysłane klientom"
 rows={rows}
 limit={GROUP_PREVIEW}
 notice={
 generatedQuery.isError ? (
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
 ) : null
 }
 />
 );
}
