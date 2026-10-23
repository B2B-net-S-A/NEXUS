"use client";

/**
 * Podgląd kandydata w panelu osoby (0424, D3 „od razu z boku”, 07.10.2026;
 * duża lewa strefa od 09.10.2026).
 *
 * Do tej pory CV i wymagania otwierały się w oknach NAD formularzem — rekruter
 * w trakcie rozmowy zamykał arkusz, żeby sprawdzić, co kandydat napisał
 * o Kafce. Podgląd ma trzy zakładki:
 * - „CV” — oryginał (kopia ze zgłoszenia albo główne CV z profilu; DOCX też
 *   się renderuje), CV firmowe pary i pozostałe pliki CV z profilu; z
 *   `cvActions` (screening) CV firmowe da się wybrać z gotowych CV w profilu,
 *   zmienić i edytować,
 * - „Wymagania” — must/nice z Profilu Championa ze zdaniem „po ludzku”
 *   i warunki rekrutacji („Szukaj w CV” zaznacza technologię w CV),
 * - „Po ludzku” — jednym zdaniem o roli i ściąga do rozmowy.
 * Sekcje „CV do klienta” i „Rozmowy” dokładają własną zakładkę (`extraTab`).
 *
 * Gdy podgląd ma co najmniej `DUAL_MIN_WIDTH` px (okno ok. 1700 px), zakładek
 * nie ma: CV stoi po lewej, a wymagania i opis „po ludzku” w kolumnie obok —
 * rekruter widzi wszystko naraz. CV zostaje w tym samym miejscu drzewa
 * w obu układach, więc zmiana szerokości nie pobiera pliku drugi raz.
 *
 * W powłoce panelu (`collapsible`, 13.10.2026, zgłoszenie rekrutera) CV
 * i kolumnę z wymaganiami da się zwinąć — stan i szerokości kolumn trzyma
 * strefa (`usePersonPreviewCollapse`), pamięć jest per osoba:
 * - zwinięte CV = listwa przy lewej krawędzi; wymagania, „Po ludzku”
 *   i zakładka sekcji stoją wtedy naraz w jednej przewijanej kolumnie,
 * - zwinięte wymagania = pasek nad CV (`JobRequirementsStrip`); ten sam pasek
 *   stoi nad CV w zakładkach (laptop), bo tam wymagań przy CV nie widać,
 * - „Szukaj w CV” i „Historia osoby” przy zwiniętym CV najpierw je rozwijają.
 *
 * Ładowany za `next/dynamic` (pdf.js i `docx-preview` nie mogą wejść do
 * chunku Tablicy). Raz pokazane części zostają zamontowane (`hidden`): powrót
 * do CV i rozwinięcie nie pobierają pliku drugi raz, a przeglądarka PDF
 * dopasowuje szerokość sama, gdy CV znów się pokaże. CV zwinięte od początku
 * nie pobiera pliku wcale, dopóki ktoś go nie rozwinie.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Download,
  FileDown,
  History,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Pencil,
  Replace,
  Upload,
  type LucideIcon,
} from "lucide-react";

import { TabbedNav } from "@/components/ds";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { JobRequirementsStrip } from "@/components/champion/JobRequirementsStrip";
import { JobRequirementsSummary } from "@/components/champion/JobRequirementsSummary";
import { PlainBriefBlock } from "@/components/champion/plain/PlainBriefBlock";
import { useToast } from "@/components/Toast";
import {
  FilePreviewContent,
  downloadDocumentBlob,
  fetchDocumentBlob,
  type CandidateDocument,
  type DocumentSearchRequest,
} from "@/components/v2/files/FilePreviewModal";
import { DockCallCheatsheet } from "@/components/v2/jobs/DockCallCheatsheet";
import { DockCvFreshness } from "@/components/v2/jobs/DockCvFreshness";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { candidateNoteItems, useCandidateNotes } from "@/components/v2/pages/candidate-notes-query";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { PersonNotesHistory } from "@/components/v2/person/PersonNotesHistory";
import {
  usePersonPanelSideSectionActive,
  usePersonPreviewCollapse,
} from "@/components/v2/person/PersonPanelSide";
import { StageCvPreview } from "@/components/v2/person/StageCvPreview";
import {
  CvFileDropTarget,
  STAGE_CV_ACCEPT,
  StageCvUploadTile,
  cvFileProblem,
  useStageCvUpload,
  type PreviewCvUpload,
} from "@/components/v2/person/StageCvUpload";
import {
  StageCvPicker,
  useChooseStageCv,
  useStageCvOptions,
} from "@/components/v2/screening-form/StageCvPicker";
import { useStageBrandedCv } from "@/hooks/useStageBrandedCv";
import api, { candidateStageCvApi, candidatesApi, type CVOriginalSnapshot } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadAuthenticatedFile, downloadBlob, fetchAuthenticatedBlob } from "@/lib/authenticated-files";
import { humanNoteCount } from "@/lib/candidate-notes-view";
import { stageBrandedQueryKey, stageCvStatus } from "@/lib/cv-to-client";
import {
  dockOriginalCv,
  originalCvSentence,
  primaryProfileCv,
  withoutQuarantinedCv,
  type DockProfileCvDoc,
} from "@/lib/dock-cv-summary";
import { fetchStageCvFile, fetchStageCvPdf } from "@/lib/stage-cv-file";
import type { StageCvOption } from "@/lib/stage-cv-options";
import { useElementWidth } from "@/lib/use-element-width";
import { cn, formatDate } from "@/lib/utils";

export type PreviewTab = "cv" | "requirements" | "plain" | "extra";
const PREVIEW_TABS: ReadonlyArray<PreviewTab> = ["cv", "requirements", "plain", "extra"];
export type PreviewCvSource = "original" | "company" | "files";

const TABS: ReadonlyArray<{ value: PreviewTab; label: string }> = [
  { value: "cv", label: "CV" },
  { value: "requirements", label: "Wymagania" },
  { value: "plain", label: "Po ludzku" },
];

/**
 * Od tej szerokości podglądu (px) CV i wymagania stoją obok siebie. Przy
 * prawej kolumnie panelu 520 px odpowiada to oknu ok. 1700 px.
 */
const DUAL_MIN_WIDTH = 1150;

const SOURCES: ReadonlyArray<{ value: PreviewCvSource; label: string }> = [
  { value: "original", label: "CV oryginalne" },
  { value: "company", label: "CV firmowe" },
  { value: "files", label: "Inne pliki" },
];

/** Źródło bajtów kopii CV ze zgłoszenia (harness podaje plik statyczny). */
export type OriginalBlobLoader = (stageId: number) => Promise<Blob>;

/**
 * Wybór i edycja CV firmowego w podglądzie (screening). Bez tego obiektu
 * podgląd jest tylko do odczytu, jak w przeglądzie DL i zakładce Rozmowy.
 */
export interface PreviewCvActions {
  candidateName: string;
  jobTitle?: string;
}

// Edytor CV to TipTap — za granicą `dynamic()`, jak w doku kanbana.
const CVBrandedEditModal = dynamic(
  () => import("@/components/v2/modals/CVBrandedEditModal").then((m) => m.CVBrandedEditModal),
  { ssr: false },
);

function originalDownloadPath(stageId: number): string {
  return `/api/candidates/stages/${stageId}/cv/original/download`;
}

// Podgląd = `inline` w dzienniku dostępu; tylko „Pobierz CV” liczy się alarmowi
// masowego przeglądania CV jako zapis na dysk (audyt 22.10, F25).
const defaultOriginalLoader: OriginalBlobLoader = (stageId) =>
  fetchAuthenticatedBlob(`${originalDownloadPath(stageId)}?disposition=inline`);

function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-40 flex-1 items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 px-4 py-6 text-center text-xs text-muted-foreground">
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function Loading({ text }: { text: string }) {
  return (
    <p className="flex flex-1 items-center justify-center gap-1.5 py-8 text-xs text-muted-foreground" role="status">
      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> {text}
    </p>
  );
}

// ── CV ───────────────────────────────────────────────────────────────────

interface CvTabProps {
  candidateId: number;
  jobId: number;
  stageId: number | null;
  source: PreviewCvSource;
  onSourceChange: (source: PreviewCvSource) => void;
  searchRequest: DocumentSearchRequest | null;
  loadDocumentBlob: typeof fetchDocumentBlob;
  loadOriginalBlob: OriginalBlobLoader;
  /** Które źródła pokazać w przełączniku (przegląd DL ma CV firmowe osobno). */
  sources?: ReadonlyArray<PreviewCvSource>;
  cvActions?: PreviewCvActions;
  cvUpload?: PreviewCvUpload;
  loadStageCvFile?: typeof fetchStageCvFile;
  /**
   * „Historia osoby” obok źródeł CV. To nie czwarte źródło: CV zostaje
   * zamontowane pod spodem, żeby powrót nie pobierał pliku drugi raz.
   */
  history?: PreviewHistory;
  /** „Zwiń CV” na końcu paska źródeł (tylko w powłoce panelu). */
  onCollapse?: () => void;
}

interface PreviewHistory {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Notatki ludzi o tej osobie; 0 = przycisk bez liczby. */
  count: number;
  content: ReactNode;
}

function CvTab({
  candidateId,
  jobId,
  stageId,
  source,
  onSourceChange,
  searchRequest,
  loadDocumentBlob,
  loadOriginalBlob,
  sources,
  cvActions,
  cvUpload,
  loadStageCvFile,
  history,
  onCollapse,
}: CvTabProps) {
  // Treść historii montuje się przy pierwszym otwarciu i potem zostaje
  // (wybrany filtr), tak jak odwiedzone zakładki podglądu.
  const [historyMounted, setHistoryMounted] = useState(false);
  if (history?.open && !historyMounted) setHistoryMounted(true);
  const historyOpen = history?.open === true;
  const { showError } = useToast();
  const queryClient = useQueryClient();
  const { askConfirm, confirmDialog } = useConfirmV2();
  // „Wgraj CV”: plik staje się głównym CV i kopią CV tej rekrutacji; po
  // wgraniu podgląd pokazuje „CV oryginalne”, czyli właśnie ten plik. Plik
  // „B2B_…” staje się CV do klienta (15.10.2026) — wtedy „CV firmowe”.
  const canUpload = cvUpload != null && stageId != null;
  const upload = useStageCvUpload({
    candidateId,
    stageId: stageId ?? 0,
    jobId,
    onUploaded: (kind) => {
      history?.onOpenChange(false);
      onSourceChange(kind === "client_cv" ? "company" : "original");
    },
  });
  const uploadInputRef = useRef<HTMLInputElement>(null);
  // Te same klucze co dok osoby i karta CV na profilu — odpowiedź jest wspólna.
  const snapshotQuery = useQuery<CVOriginalSnapshot>({
    queryKey: ["cv-original", stageId],
    queryFn: () => candidateStageCvApi.original.get(stageId as number).then((r) => r.data),
    enabled: stageId != null,
  });
  const docsQuery = useQuery<CandidateDocument[]>({
    queryKey: candidateQueryKeys.cvDocuments(candidateId),
    queryFn: () =>
      api
        .get<CandidateDocument[]>(`/api/candidates/${candidateId}/documents?kind=cv`)
        .then((r) => (Array.isArray(r.data) ? r.data : [])),
    staleTime: 30_000,
  });
  const branded = useStageBrandedCv(stageId);
  // Plik z kwarantanny tożsamości (CV innej osoby) nie jest oryginałem — ta sama
  // reguła co dok. Znacznik bierzemy z danych kandydata, które w panelu czyta
  // dok: tylko z pamięci zapytań (`enabled: false`), bez drugiego żądania
  // (harnessy `/preview/*` nie pytają sieci). `queryFn` jak w doku (#1789).
  const candidateQuery = useQuery<{ cv_extracted_data?: unknown }>({
    queryKey: candidateQueryKeys.detail(candidateId),
    queryFn: () => candidatesApi.get(candidateId).then((r) => r.data as { cv_extracted_data?: unknown }),
    enabled: false,
  });
  const ownProfileDocs = withoutQuarantinedCv(docsQuery.data, candidateQuery.data?.cv_extracted_data);

  const original = dockOriginalCv({
    snapshot: snapshotQuery.data,
    snapshotLoading: stageId != null && snapshotQuery.isLoading,
    profileDocs: ownProfileDocs as DockProfileCvDoc[] | undefined,
    profileDocsFailed: docsQuery.isError,
  });

  // Dokument „kopia ze zgłoszenia” nie ma wiersza w teczce kandydata — budujemy
  // opis pliku z migawki, a bajty idą z trasy etapu (`…/cv/original/download`).
  const snapshotDoc = useMemo<CandidateDocument | null>(() => {
    const snap = snapshotQuery.data;
    if (!snap?.has_snapshot || stageId == null) return null;
    return {
      id: stageId,
      filename: snap.original_cv_filename ?? "CV",
      content_type: null,
      size_bytes: null,
      document_kind: "cv",
      is_primary: false,
      uploaded_at: snap.original_snapshot_at ?? null,
      external_source: null,
      created_at: snap.original_snapshot_at ?? "",
    };
  }, [snapshotQuery.data, stageId]);
  const snapshotLoader = useCallback<typeof fetchDocumentBlob>(
    (_candidateId, docId) => loadOriginalBlob(docId),
    [loadOriginalBlob],
  );
  const profileDoc = original.kind === "profile" ? (ownProfileDocs ?? []).find((d) => d.id === original.doc.id) ?? null : null;

  const docs = docsQuery.data ?? [];
  const [fileId, setFileId] = useState<number | null>(null);
  const selectedFile = docs.find((d) => d.id === fileId) ?? primaryProfileCv(docs) ?? null;

  const download = (doc: CandidateDocument, fromSnapshot: boolean) => {
    const run = fromSnapshot && stageId != null
      ? downloadAuthenticatedFile(originalDownloadPath(stageId), doc.filename || "CV")
      : downloadDocumentBlob(candidateId, doc);
    run.catch(() => showError("Nie udało się pobrać pliku."));
  };

  const brandedStatus = stageCvStatus(branded.query.data);
  const brandedMissing =
    branded.query.isError &&
    (branded.query.error as { response?: { status?: number } } | null)?.response?.status === 404;
  const profileHref = `/candidates/${candidateId}?tab=documents`;

  // Wybór gotowego CV z profilu i edycja (screening). CV pary może leżeć na
  // wcześniejszym wierszu etapu — tam idą zmiana i edycja.
  const noCompanyCv = brandedMissing || (branded.query.isSuccess && brandedStatus === "none");
  const canAct = cvActions != null && stageId != null;
  const cvStageId = branded.cvStageId ?? stageId;
  const picker = useStageCvOptions({
    candidateId,
    jobId,
    stageId,
    documents: docsQuery.data,
    enabled: canAct,
  });
  const [changing, setChanging] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const chooser = useChooseStageCv({
    candidateId,
    jobId,
    stageId: stageId ?? 0,
    targetStageId: cvStageId ?? 0,
    revision: brandedMissing ? 0 : (branded.query.data?.edit_revision ?? 0),
    onChosen: () => setChanging(false),
  });
  const chooseCv = async (option: StageCvOption) => {
    if (!noCompanyCv) {
      const confirmed = await askConfirm({
        title: "Zastąpić CV firmowe?",
        description:
          "Obecny szkic zostanie zastąpiony wybranym CV. Zatwierdzone wersje i wysłane linki zostają bez zmian.",
        confirmLabel: "Zastąp",
      });
      if (!confirmed) return;
    }
    chooser.choose(option);
  };
  const previewDocument = (documentId: number) => {
    setFileId(documentId);
    onSourceChange("files");
  };

  // „Pobierz” w pasku źródeł (15.10.2026, D1–D5) pobiera to, co widać.
  // CV firmowe: ten sam plik co „Pobierz Word / PDF” w doku — CV etapu
  // z poprawkami, z wiersza, na którym leży (`cvStageId`), wpis `surface=preview`.
  // Oryginał i pliki z profilu idą bez wpisu pobrania, jak dotąd wszędzie.
  const companyDownloadable =
    stageId != null && branded.query.isSuccess && brandedStatus === "ready" && !(canAct && changing);
  const companyConsentMissing = companyDownloadable && branded.query.data?.consent_missing === true;
  const [downloadingCv, setDownloadingCv] = useState<"docx" | "pdf" | null>(null);
  const downloadCompanyCv = async (format: "docx" | "pdf") => {
    if (cvStageId == null) return;
    setDownloadingCv(format);
    try {
      const file =
        format === "docx"
          ? await (loadStageCvFile ?? fetchStageCvFile)(cvStageId, { download: "preview" })
          : await fetchStageCvPdf(cvStageId, { download: "preview" });
      downloadBlob(file.blob, file.filename || (format === "docx" ? "CV.docx" : "CV.pdf"));
    } catch (error) {
      showError(
        apiErrorMessage(
          error,
          format === "pdf"
            ? "Nie udało się pobrać PDF. Spróbuj za chwilę albo pobierz plik Word."
            : "Nie udało się pobrać CV.",
        ),
      );
    } finally {
      setDownloadingCv(null);
    }
  };
  // Plik pod „Pobierz CV”: oryginał (kopia ze zgłoszenia albo CV z profilu)
  // albo plik zaznaczony w „Innych plikach”; `hint` = skąd jest (dymek, D2).
  let fileDownload: { doc: CandidateDocument; fromSnapshot: boolean; hint: string } | "pending" | null = null;
  if (source === "original") {
    const hint = originalCvSentence(original).replace(/^Oryginał CV: /, "");
    if (original.kind === "loading") fileDownload = "pending";
    else if (original.kind === "snapshot" && snapshotDoc) fileDownload = { doc: snapshotDoc, fromSnapshot: true, hint };
    else if (original.kind === "profile" && profileDoc) fileDownload = { doc: profileDoc, fromSnapshot: false, hint };
  } else if (source === "files" && selectedFile) {
    fileDownload = {
      doc: selectedFile,
      fromSnapshot: false,
      hint: `${formatDate(selectedFile.uploaded_at ?? selectedFile.created_at)}${selectedFile.is_primary ? " · główne CV" : ""}`,
    };
  }

  let body: ReactNode;
  if (source === "original") {
    if (original.kind === "loading") body = <Loading text="Wczytywanie CV…" />;
    else if (original.kind === "snapshot" && snapshotDoc) {
      body = (
        <FilePreviewContent
          doc={snapshotDoc}
          candidateId={candidateId}
          onDownload={(doc) => download(doc, true)}
          loadDocumentBlob={snapshotLoader}
          searchRequest={searchRequest}
          pdfFit="auto"
          className="min-h-0 flex-1 rounded-lg border border-border"
        />
      );
    } else if (original.kind === "profile" && profileDoc) {
      body = (
        <FilePreviewContent
          doc={profileDoc}
          candidateId={candidateId}
          onDownload={(doc) => download(doc, false)}
          loadDocumentBlob={loadDocumentBlob}
          searchRequest={searchRequest}
          pdfFit="auto"
          className="min-h-0 flex-1 rounded-lg border border-border"
        />
      );
    } else if (original.kind === "none") {
      body = canUpload ? (
        <div className="flex min-h-40 flex-1 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-muted/20 px-4 py-6 text-center text-xs text-muted-foreground">
          <p>Kandydat nie ma CV ani w zgłoszeniu, ani w profilu.</p>
          <StageCvUploadTile upload={upload} label="Wgraj CV" className="w-full max-w-sm text-left" />
        </div>
      ) : (
        <Notice>
          <p>Kandydat nie ma CV ani w zgłoszeniu, ani w profilu.</p>
          <Link href={profileHref} target="_blank" rel="noopener" className="font-medium text-primary hover:underline">
            Dodaj CV w profilu kandydata ↗
          </Link>
        </Notice>
      );
    } else {
      body = (
        <Notice>
          <p role="alert">Nie udało się sprawdzić CV kandydata.</p>
          <button
            type="button"
            className="font-medium text-primary hover:underline"
            onClick={() => {
              void snapshotQuery.refetch();
              void docsQuery.refetch();
            }}
          >
            Ponów
          </button>
        </Notice>
      );
    }
  } else if (source === "company") {
    if (stageId == null) {
      body = <Notice>Ta osoba nie ma etapu w tej rekrutacji — CV firmowego jeszcze nie ma.</Notice>;
    } else if (branded.query.isLoading) {
      body = <Loading text="Sprawdzam CV firmowe…" />;
    } else if (branded.query.isError && !brandedMissing) {
      body = (
        <Notice>
          <p role="alert">Nie udało się sprawdzić CV firmowego.</p>
          <button type="button" className="font-medium text-primary hover:underline" onClick={() => void branded.query.refetch()}>
            Ponów
          </button>
        </Notice>
      );
    } else if (brandedMissing || brandedStatus === "none") {
      body =
        canAct && (picker.options.total > 0 || picker.isPending) ? (
          <StageCvPicker
            options={picker.options}
            isPending={picker.isPending}
            busyKey={chooser.busyKey}
            onChoose={(option) => void chooseCv(option)}
            onPreviewDocument={previewDocument}
            intro="CV firmowe tej rekrutacji jeszcze nie powstało. Możesz wybrać gotowe CV z profilu i je poprawić — albo poczekać: po przekazaniu osoby na „Zweryfikowany” wygeneruje się samo."
          />
        ) : (
          <Notice>
            CV firmowe jeszcze nie powstało — generuje się po przekazaniu osoby na „Zweryfikowany”. Wtedy zobaczysz
            je tutaj.
          </Notice>
        );
    } else if (canAct && changing) {
      body = (
        <>
          {/* Nad listą: lista rozciąga się na całą wysokość podglądu. */}
          <Button size="sm" variant="outline" className="self-start" onClick={() => setChanging(false)}>
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
            Zostaw obecne CV
          </Button>
          <StageCvPicker
            options={picker.options}
            isPending={picker.isPending}
            busyKey={chooser.busyKey}
            onChoose={(option) => void chooseCv(option)}
            onPreviewDocument={previewDocument}
            intro="Wybrane CV zastąpi obecny szkic CV firmowego tej rekrutacji."
          />
        </>
      );
    } else {
      body = (
        <>
          {canAct ? (
            <div className="flex flex-wrap items-center gap-2" data-testid="stage-cv-actions">
              {brandedStatus === "ready" ? (
                <Button size="sm" onClick={() => setEditorOpen(true)}>
                  <Pencil className="h-3.5 w-3.5" aria-hidden />
                  Edytuj
                </Button>
              ) : null}
              {picker.options.total > 0 ? (
                <Button size="sm" variant="outline" onClick={() => setChanging(true)}>
                  <Replace className="h-3.5 w-3.5" aria-hidden />
                  Zmień CV
                </Button>
              ) : null}
              {branded.query.data?.source === "document" ? (
                <p className="text-xs text-muted-foreground">
                  Wczytane z pliku Word — sprawdź układ przed wysłaniem.
                </p>
              ) : null}
            </div>
          ) : null}
          <div className="min-h-0 flex-1 overflow-y-auto">
            <StageCvPreview
              candidateId={candidateId}
              jobId={jobId}
              cvStageId={branded.cvStageId}
              revision={branded.query.data?.edit_revision}
              loadStageCvFile={loadStageCvFile}
              hideDownload
              fill
              searchable
              searchRequest={searchRequest}
            />
          </div>
        </>
      );
    }
  } else if (docsQuery.isLoading) {
    body = <Loading text="Wczytywanie plików…" />;
  } else if (docsQuery.isError) {
    body = (
      <Notice>
        <p role="alert">Nie udało się wczytać plików kandydata.</p>
        <button type="button" className="font-medium text-primary hover:underline" onClick={() => void docsQuery.refetch()}>
          Ponów
        </button>
      </Notice>
    );
  } else if (docs.length === 0) {
    body = <Notice>W profilu kandydata nie ma plików CV.</Notice>;
  } else {
    body = (
      <>
        <ul className="flex flex-wrap gap-1.5" aria-label="Pliki CV kandydata">
          {docs.map((doc) => (
            <li key={doc.id}>
              <button
                type="button"
                aria-pressed={selectedFile?.id === doc.id}
                onClick={() => setFileId(doc.id)}
                title={doc.filename}
                className={cn(
                  "inline-flex max-w-[16rem] items-center gap-1 truncate rounded-md border px-2 py-1 text-[11px] transition-colors",
                  selectedFile?.id === doc.id
                    ? "border-primary bg-primary/10 font-medium text-primary"
                    : "border-border bg-background text-muted-foreground hover:bg-muted",
                )}
              >
                <span className="truncate">{doc.filename}</span>
                <span className="shrink-0 text-muted-foreground">
                  {formatDate(doc.uploaded_at ?? doc.created_at)}
                  {doc.is_primary ? " · główne" : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
        {selectedFile ? (
          <FilePreviewContent
            doc={selectedFile}
            candidateId={candidateId}
            onDownload={(doc) => download(doc, false)}
            loadDocumentBlob={loadDocumentBlob}
            searchRequest={searchRequest}
            pdfFit="auto"
            className="min-h-0 flex-1 rounded-lg border border-border"
          />
        ) : null}
      </>
    );
  }

  return (
    <CvFileDropTarget
      enabled={canUpload}
      upload={upload}
      title={[cvUpload?.candidateName, cvUpload?.jobTitle].filter(Boolean).join(" · ")}
      className="@container/cvsources flex min-h-0 flex-1 flex-col gap-2"
    >
      {/* Zakładka jest kontenerem (`cvsources`): na laptopie 1280 px strefa ma ok.
          750 px i z „Historią osoby”, „Pobierz” i „Wgraj CV” rząd by się zawijał —
          poniżej 56 rem „Zwiń CV” zostaje ikoną, przy CV firmowym znika słowo
          „Pobierz” i ikona przy „PDF”, a odstępy maleją (15.10.2026). */}
      <div className="flex flex-wrap items-center gap-1.5 @min-[56rem]/cvsources:gap-2">
        <div role="group" aria-label="Które CV pokazać" className="inline-flex w-fit flex-wrap rounded-md border border-border bg-muted/30 p-0.5">
          {SOURCES.filter((option) => !sources || sources.includes(option.value)).map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={!historyOpen && source === option.value}
              onClick={() => {
                history?.onOpenChange(false);
                onSourceChange(option.value);
              }}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium transition-colors pointer-coarse:py-2",
                !historyOpen && source === option.value
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {option.label}
              {option.value === "files" && docsQuery.isSuccess ? ` (${docs.length})` : ""}
              {option.value === "company" && canAct && noCompanyCv && picker.options.total > 0
                ? ` · wybierz (${picker.options.total})`
                : ""}
            </button>
          ))}
        </div>
        {history ? (
          <button
            type="button"
            aria-pressed={historyOpen}
            onClick={() => history.onOpenChange(!historyOpen)}
            className={cn(
              "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors pointer-coarse:py-2",
              historyOpen
                ? "border-primary/40 bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            Historia osoby{history.count > 0 ? ` (${history.count})` : ""}
          </button>
        ) : null}
        {historyOpen ? null : fileDownload === "pending" ? (
          <Button type="button" size="sm" variant="outline" disabled data-testid="preview-cv-download">
            <Download className="h-3.5 w-3.5" aria-hidden />
            Pobierz CV
          </Button>
        ) : fileDownload ? (
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  data-testid="preview-cv-download"
                  onClick={() => download(fileDownload.doc, fileDownload.fromSnapshot)}
                >
                  <Download className="h-3.5 w-3.5" aria-hidden />
                  Pobierz CV
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom" align="start" className="space-y-0.5 border border-border">
                <p className="break-all font-semibold">{fileDownload.doc.filename}</p>
                <p className="font-normal text-muted-foreground">{fileDownload.hint}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : source === "company" && companyDownloadable ? (
          <div
            className="flex items-center gap-1.5"
            data-testid="preview-cv-download"
            title={companyConsentMissing ? "Bez zrzutu zgody RODO nie pobierzesz CV — dołącz go w karcie „CV do klienta”." : undefined}
          >
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-label="Pobierz Word"
              onClick={() => void downloadCompanyCv("docx")}
              disabled={downloadingCv != null || companyConsentMissing}
              loading={downloadingCv === "docx"}
            >
              <Download className="h-3.5 w-3.5" aria-hidden />
              <span>
                <span className="hidden @min-[56rem]/cvsources:inline">Pobierz </span>Word
              </span>
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-label="Pobierz PDF"
              onClick={() => void downloadCompanyCv("pdf")}
              disabled={downloadingCv != null || companyConsentMissing}
              loading={downloadingCv === "pdf"}
            >
              <FileDown className="hidden h-3.5 w-3.5 @min-[56rem]/cvsources:block" aria-hidden />
              PDF
            </Button>
          </div>
        ) : null}
        {canUpload ? (
          <>
            <input
              ref={uploadInputRef}
              type="file"
              accept={STAGE_CV_ACCEPT}
              className="sr-only"
              tabIndex={-1}
              aria-hidden
              data-testid="preview-cv-upload-input"
              onChange={(event) => {
                const file = event.target.files?.[0];
                // Reset od razu — ten sam plik po błędzie musi dać się wybrać ponownie.
                event.target.value = "";
                if (!file) return;
                const problem = cvFileProblem(file);
                if (problem) showError(problem);
                else upload.upload(file);
              }}
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              loading={upload.isPending}
              onClick={() => uploadInputRef.current?.click()}
            >
              <Upload className="h-3.5 w-3.5" aria-hidden />
              Wgraj CV
            </Button>
          </>
        ) : null}
        {onCollapse ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="ml-auto"
            aria-label="Zwiń CV"
            title="Zwiń CV"
            onClick={onCollapse}
          >
            <PanelLeftClose className="h-3.5 w-3.5" aria-hidden />
            <span className="hidden @min-[56rem]/cvsources:inline">Zwiń CV</span>
          </Button>
        ) : null}
      </div>
      {/* Stałe opakowanie: `contents` nie zmienia układu, a `hidden` chowa CV
          bez odmontowania — plik nie pobiera się drugi raz po powrocie. */}
      <div hidden={historyOpen} className="contents">
        {/* D4 (15.10.2026): „Pobierz CV” daje kopię tej rekrutacji — gdy w profilu
            jest nowsze CV, ramka mówi to od razu. Podmiana tylko z prawem wgrania. */}
        {source === "original" && stageId != null ? (
          <DockCvFreshness
            stageId={stageId}
            original={original}
            profileDocs={ownProfileDocs}
            candidate={null}
            uploadedAt={null}
            onShowProfileCv={previewDocument}
            canRefresh={canUpload}
          />
        ) : null}
        {body}
      </div>
      {history && historyMounted ? (
        <div
          role="region"
          aria-label="Historia osoby"
          hidden={!historyOpen}
          className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-border bg-background p-3"
        >
          {history.content}
        </div>
      ) : null}
      {confirmDialog}
      {upload.confirmDialog}
      {canAct && editorOpen && cvStageId != null ? (
        <CVBrandedEditModal
          open
          onOpenChange={(open) => {
            setEditorOpen(open);
            if (!open) void queryClient.invalidateQueries({ queryKey: stageBrandedQueryKey(cvStageId) });
          }}
          stageId={cvStageId}
          jobTitle={cvActions.jobTitle}
          candidateName={cvActions.candidateName}
        />
      ) : null}
    </CvFileDropTarget>
  );
}

// ── Samo CV (przegląd Delivery Leada, D9) ────────────────────────────────

export interface CandidateCvPreviewProps {
  candidateId: number;
  jobId: number;
  stageId: number | null;
  defaultSource?: PreviewCvSource;
  sources?: ReadonlyArray<PreviewCvSource>;
  loadDocumentBlob?: typeof fetchDocumentBlob;
  loadOriginalBlob?: OriginalBlobLoader;
  /** Klik w wymaganie w przeglądzie DL (23.10.2026). */
  searchRequest?: DocumentSearchRequest | null;
}

/** Zakładka CV bez reszty podglądu — kolumna CV w przeglądzie DL (08.10.2026). */
export function CandidateCvPreview({
  candidateId,
  jobId,
  stageId,
  defaultSource = "original",
  sources,
  loadDocumentBlob = fetchDocumentBlob,
  loadOriginalBlob = defaultOriginalLoader,
  searchRequest = null,
}: CandidateCvPreviewProps) {
  const [source, setSource] = useState<PreviewCvSource>(defaultSource);
  return (
    <CvTab
      candidateId={candidateId}
      jobId={jobId}
      stageId={stageId}
      source={source}
      onSourceChange={setSource}
      searchRequest={searchRequest}
      loadDocumentBlob={loadDocumentBlob}
      loadOriginalBlob={loadOriginalBlob}
      sources={sources}
    />
  );
}

// ── Całość ───────────────────────────────────────────────────────────────

export interface CandidatePreviewPaneProps {
  candidateId: number;
  jobId: number;
  /** Najnowszy wiersz etapu pary — kopia CV ze zgłoszenia i CV firmowe. */
  stageId: number | null;
  /** Zakładka sterowana z zewnątrz (formularz screeningu); bez niej podgląd pamięta ją sam. */
  tab?: PreviewTab;
  onTabChange?: (tab: PreviewTab) => void;
  /** Zakładka na start, gdy `tab` nie jest podany. */
  defaultTab?: PreviewTab;
  /**
   * Zacznij od CV firmowego, gdy para już je ma („CV do klienta”, „Rozmowy”)
   * — do pierwszego wyboru źródła przez użytkownika.
   */
  preferCompanyCv?: boolean;
  /** Dodatkowa zakładka sekcji (np. „Pytania klienta” przy rozmowach). */
  extraTab?: { label: string; content: ReactNode };
  /** Górny budżet PLN/h z Tablicy — gdy rekrutacji nie ma w cache strony. */
  budgetHourly?: number | null;
  /** Screening: wybór gotowego CV z profilu, zmiana i edycja CV firmowego. */
  cvActions?: PreviewCvActions;
  /** „Wgraj CV” w pasku źródeł, upuszczanie pliku na podgląd i kafelek przy braku CV. */
  cvUpload?: PreviewCvUpload;
  /**
   * Które źródła CV pokazać w przełączniku. Edytor CV podaje oryginał i pliki:
   * CV firmowe to dokument, który właśnie edytuje.
   */
  cvSources?: ReadonlyArray<PreviewCvSource>;
  /**
   * „Historia osoby (N)” obok źródeł CV — wszystkie notatki osoby w dużej
   * strefie, w każdej zakładce panelu. Edytor CV jej nie pokazuje (ma własne
   * „Notatki” tej rekrutacji).
   */
  showHistory?: boolean;
  /** Historia sterowana z zewnątrz („Pokaż” w profilu przed telefonem). */
  historyOpen?: boolean;
  onHistoryOpenChange?: (open: boolean) => void;
  /**
   * „Szukaj w CV” zlecone z zewnątrz (edytor CV: „Pokaż w oryginale” przy
   * cytacie źródła). Nowy `nonce` = nowe wyszukanie, także tego samego tekstu.
   */
  searchRequest?: DocumentSearchRequest | null;
  /**
   * Zwijanie CV i wymagań — podglądy w lewej strefie panelu osoby. Edytor CV
   * i przegląd DL go nie mają, także gdy otwierają się z wnętrza panelu.
   */
  collapsible?: boolean;
  /** Harness: bajty plików bez sieci. */
  loadDocumentBlob?: typeof fetchDocumentBlob;
  loadOriginalBlob?: OriginalBlobLoader;
  loadStageCvFile?: typeof fetchStageCvFile;
  className?: string;
}

function PaneHeading({ children }: { children: string }) {
  return <h3 className="text-sm font-semibold text-foreground">{children}</h3>;
}

/** Zwinięta część podglądu: przycisk rozwijania i pionowy podpis. */
function PreviewRail({
  label,
  detail,
  expandLabel,
  icon: Icon,
  onExpand,
  children,
}: {
  label: string;
  detail?: string;
  expandLabel: string;
  icon: LucideIcon;
  onExpand: () => void;
  children?: ReactNode;
}) {
  return (
    <div
      role="group"
      aria-label={`${label} — zwinięte`}
      className="flex w-11 flex-none flex-col items-center gap-3 border-r border-border bg-muted/30 py-3"
    >
      <Button type="button" size="icon" variant="outline" className="h-8 w-8" aria-label={expandLabel} title={expandLabel} onClick={onExpand}>
        <Icon className="h-4 w-4" aria-hidden />
      </Button>
      <span aria-hidden className="rotate-180 whitespace-nowrap text-xs font-semibold text-foreground [writing-mode:vertical-rl]">
        {label}
        {detail ? <span className="font-normal text-muted-foreground"> · {detail}</span> : null}
      </span>
      {children}
    </div>
  );
}

export function CandidatePreviewPane({
  candidateId,
  jobId,
  stageId,
  tab: controlledTab,
  onTabChange,
  defaultTab = "cv",
  preferCompanyCv = false,
  extraTab,
  budgetHourly = null,
  cvActions,
  cvUpload,
  cvSources,
  showHistory = true,
  historyOpen: controlledHistoryOpen,
  onHistoryOpenChange,
  searchRequest: requestedSearch = null,
  loadDocumentBlob = fetchDocumentBlob,
  loadOriginalBlob = defaultOriginalLoader,
  loadStageCvFile,
  collapsible = false,
  className,
}: CandidatePreviewPaneProps) {
  const [ownTab, setOwnTab] = useState<PreviewTab>(defaultTab);
  const requestedTab = controlledTab ?? ownTab;
  // Zakładka sekcji zniknęła (inna sekcja panelu) — wracamy do CV.
  const tab: PreviewTab = requestedTab === "extra" && !extraTab ? "cv" : requestedTab;
  const changeTab = onTabChange ?? setOwnTab;

  // `null` = użytkownik jeszcze nie wybrał źródła. Ten sam klucz zapytania co
  // w zakładce CV, więc drugiego żądania nie ma.
  const [pickedSource, setPickedSource] = useState<PreviewCvSource | null>(null);
  const branded = useStageBrandedCv(preferCompanyCv ? stageId : null);
  const companyReady =
    preferCompanyCv && branded.query.isSuccess && stageCvStatus(branded.query.data) !== "none";
  const source: PreviewCvSource = pickedSource ?? (companyReady ? "company" : "original");

  // Historia osoby: ten sam klucz notatek co dok i zakładka panelu, więc bez
  // drugiego pobrania. Bez notatek przycisku nie ma; przy awarii odczytu
  // zostaje (bez liczby), a czytnik pokazuje błąd z „Ponów” — awaria nie może
  // wyglądać jak osoba bez historii.
  const [ownHistoryOpen, setOwnHistoryOpen] = useState(false);
  const historyOpen = controlledHistoryOpen ?? ownHistoryOpen;
  const changeHistoryOpen = onHistoryOpenChange ?? setOwnHistoryOpen;
  const notesQuery = useCandidateNotes(candidateId, showHistory);
  const noteItems = candidateNoteItems(notesQuery.data);
  const history =
    showHistory && (noteItems.length > 0 || notesQuery.isError)
      ? {
          open: historyOpen,
          onOpenChange: changeHistoryOpen,
          count: humanNoteCount(noteItems),
          // Czytnik: bez edycji, przypinania i odpowiedzi — te są w zakładce „Notatki”.
          content: <PersonNotesHistory variant="reader" candidateId={candidateId} jobId={jobId} readOnly />,
        }
      : undefined;

  const [searchRequest, setSearchRequest] = useState<DocumentSearchRequest | null>(null);

  const [root, setRoot] = useState<HTMLElement | null>(null);
  const dual = useElementWidth(root) >= DUAL_MIN_WIDTH;

  // Zwijanie tylko w powłoce panelu; bez niej układ jak dotąd.
  const collapse = usePersonPreviewCollapse();
  const canCollapse = collapsible && collapse != null;
  const setLayout = collapse?.setLayout;
  const cvCollapsed = canCollapse && collapse.layout.cvCollapsed;
  const infoCollapsed = canCollapse && collapse.layout.infoCollapsed;
  // Wszystkie sekcje informacji naraz: obok CV w szerokiej strefie albo
  // w miejscu zwiniętego CV. Zakładki tylko, gdy nic nie jest zwinięte.
  const stacked = !infoCollapsed && (dual || cvCollapsed);
  const tabbed = !dual && !cvCollapsed && !infoCollapsed;
  const cvVisible = !cvCollapsed && (infoCollapsed || dual || tab === "cv");
  const infoVisible = !infoCollapsed && (stacked || tab !== "cv");
  const sectionVisible = (value: PreviewTab) => !infoCollapsed && (stacked || tab === value);
  const visibleNow: Record<PreviewTab, boolean> = {
    cv: cvVisible,
    requirements: sectionVisible("requirements"),
    plain: sectionVisible("plain"),
    extra: extraTab != null && sectionVisible("extra"),
  };
  // Raz pokazana część zostaje zamontowana (`hidden`): powrót, rozwinięcie
  // i zwężenie okna nie pobierają CV drugi raz. Podgląd ukrytej sekcji panelu
  // (układ jest wspólny dla sekcji) nie montuje nic nowego, dopóki nie wróci.
  const sectionActive = usePersonPanelSideSectionActive();
  const [seen, setSeen] = useState<ReadonlySet<PreviewTab>>(() => new Set());
  const newlySeen = sectionActive ? PREVIEW_TABS.filter((value) => visibleNow[value] && !seen.has(value)) : [];
  if (newlySeen.length > 0) setSeen(new Set([...seen, ...newlySeen]));
  const shown = (value: PreviewTab) => seen.has(value) || (sectionActive && visibleNow[value]);
  // Pasek wymagań: zamiast zwiniętej kolumny, a w zakładkach nad CV (D3).
  const stripVisible = canCollapse && cvVisible && (infoCollapsed || !dual);

  const expandCv = useCallback(() => {
    if (cvCollapsed) setLayout?.({ cvCollapsed: false });
    changeTab("cv");
  }, [changeTab, cvCollapsed, setLayout]);

  // „Szukaj w CV” przy wymaganiu szuka w CV, które jest na ekranie — od
  // 23.10.2026 także w CV firmowym (wcześniej przełączało na oryginał, bo CV
  // firmowe nie miało paska). Zlecenie z zewnątrz (cytat z edytora CV —
  // „Pokaż w oryginale”) dalej idzie do oryginału.
  // Otwarta historia osoby ustępuje CV, a zwinięte CV się rozwija. Lupa szuka
  // słów wymagania z serwera („.NET lub C#” → „.NET”, „C#”), a pole pokazuje
  // jego nazwę (16.10.2026).
  const searchCv = useCallback(
    (name: string, words: readonly string[], toOriginal: boolean) => {
      if (toOriginal) {
        setPickedSource((current) => {
          const effective = current ?? (companyReady ? "company" : "original");
          return effective === "company" ? "original" : current;
        });
      }
      setSearchRequest({ text: name, nonce: Date.now(), terms: words });
      changeHistoryOpen(false);
      expandCv();
    },
    [changeHistoryOpen, companyReady, expandCv],
  );
  const pickRequirement = useCallback(
    (name: string, words: readonly string[] = []) => searchCv(name, words, false),
    [searchCv],
  );

  const showAllRequirements = useCallback(() => {
    if (infoCollapsed) setLayout?.({ infoCollapsed: false });
    changeTab("requirements");
  }, [changeTab, infoCollapsed, setLayout]);

  // Historia osoby żyje w części CV. Zwinięcie CV ją zamyka (w każdym
  // podglądzie panelu — układ jest wspólny), więc „Pokaż” z zewnątrz (profil
  // przed telefonem) zawsze ją otwiera i najpierw rozwija CV.
  useEffect(() => {
    if (cvCollapsed && historyOpen) changeHistoryOpen(false);
    // Reaguje na zwinięcie CV, nie na otwieranie historii.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cvCollapsed]);
  useEffect(() => {
    if (historyOpen && cvCollapsed) expandCv();
    // Reaguje na otwarcie historii, nie na zwinięcie CV przy otwartej historii.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyOpen]);

  // Wyszukanie zlecone z zewnątrz: zakładka CV, oryginał zamiast CV firmowego
  // (cytat pochodzi z oryginału), historia osoby ustępuje.
  const requestedNonce = requestedSearch?.nonce;
  const requestedText = requestedSearch?.text;
  useEffect(() => {
    if (requestedNonce != null && requestedText) searchCv(requestedText, [], true);
    // Reaguje na NOWE zlecenie (`nonce`), nie na zmianę stanu zakładek.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedNonce]);

  const tabs = extraTab ? [...TABS, { value: "extra" as const, label: extraTab.label }] : TABS;
  const panelRole = tabbed ? "tabpanel" : "region";

  return (
    <section
      ref={setRoot}
      aria-label="Podgląd kandydata"
      data-testid="candidate-preview-pane"
      data-dual={dual || undefined}
      data-cv-collapsed={cvCollapsed || undefined}
      data-info-collapsed={infoCollapsed || undefined}
      className={cn("flex min-h-0 flex-col", className)}
    >
      <div hidden={!tabbed} className="flex-none border-b border-border bg-background px-3 pt-2">
        <TabbedNav
          ariaLabel="Podgląd: CV, wymagania, po ludzku"
          tabs={tabs.map(({ value, label }) => ({ value, label }))}
          value={tab}
          onValueChange={(next) => changeTab(next as PreviewTab)}
          overflow="scroll"
        />
      </div>
      <div className="flex min-h-0 flex-1">
        {cvCollapsed ? (
          <PreviewRail
            label="CV"
            detail={SOURCES.find((option) => option.value === source)?.label}
            expandLabel="Rozwiń CV"
            icon={PanelLeftOpen}
            onExpand={expandCv}
          >
            {history ? (
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="h-8 w-8"
                aria-label="Pokaż historię osoby"
                title="Pokaż historię osoby"
                onClick={() => {
                  expandCv();
                  changeHistoryOpen(true);
                }}
              >
                <History className="h-4 w-4" aria-hidden />
              </Button>
            ) : null}
          </PreviewRail>
        ) : null}
        {cvCollapsed && infoCollapsed ? (
          <PreviewRail
            label="Wymagania"
            expandLabel="Rozwiń wymagania"
            icon={PanelRightOpen}
            onExpand={() => setLayout?.({ infoCollapsed: false })}
          />
        ) : null}
        {shown("cv") ? (
          <div
            role={panelRole}
            aria-label="CV"
            hidden={!cvVisible}
            className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 p-3"
          >
            {stripVisible ? (
              <JobRequirementsStrip
                jobId={jobId}
                budgetHourly={budgetHourly}
                onPickRequirement={pickRequirement}
                onShowAll={showAllRequirements}
              />
            ) : null}
            <CvTab
              candidateId={candidateId}
              jobId={jobId}
              stageId={stageId}
              source={source}
              onSourceChange={setPickedSource}
              searchRequest={searchRequest}
              loadDocumentBlob={loadDocumentBlob}
              loadOriginalBlob={loadOriginalBlob}
              sources={cvSources}
              cvActions={cvActions}
              cvUpload={cvUpload}
              loadStageCvFile={loadStageCvFile}
              history={history}
              onCollapse={canCollapse ? () => setLayout?.({ cvCollapsed: true }) : undefined}
            />
          </div>
        ) : null}
        <div
          hidden={!infoVisible}
          data-testid="candidate-preview-info"
          className={cn(
            "min-h-0 overflow-y-auto bg-background p-4",
            stacked ? "space-y-6" : "space-y-3",
            stacked && !cvCollapsed ? "w-[440px] flex-none border-l border-border" : "min-w-0 flex-1",
          )}
        >
          {canCollapse ? (
            <div className={cn("flex items-center justify-between gap-2", stacked && "mx-auto w-full max-w-4xl")}>
              {stacked ? <PaneHeading>Wymagania</PaneHeading> : <span />}
              <Button type="button" size="sm" variant="ghost" onClick={() => setLayout?.({ infoCollapsed: true })}>
                <PanelRightClose className="h-3.5 w-3.5" aria-hidden />
                Zwiń wymagania
              </Button>
            </div>
          ) : null}
          {shown("requirements") ? (
            <div
              role={panelRole}
              aria-label="Wymagania"
              hidden={!sectionVisible("requirements")}
              className="mx-auto max-w-4xl space-y-3"
            >
              {stacked && !canCollapse ? <PaneHeading>Wymagania</PaneHeading> : null}
              <JobRequirementsSummary jobId={jobId} budgetHourly={budgetHourly} onPickRequirement={pickRequirement} />
            </div>
          ) : null}
          {shown("plain") ? (
            <div
              role={panelRole}
              aria-label="Po ludzku"
              hidden={!sectionVisible("plain")}
              className="mx-auto max-w-3xl space-y-4"
            >
              {stacked ? <PaneHeading>Po ludzku</PaneHeading> : null}
              <PlainBriefBlock jobId={jobId} parts="summary" compact={dual && !cvCollapsed} />
              <DockCallCheatsheet jobId={jobId} roomy={!dual || cvCollapsed} />
            </div>
          ) : null}
          {extraTab && shown("extra") ? (
            <div
              role={panelRole}
              aria-label={extraTab.label}
              hidden={!sectionVisible("extra")}
              className="mx-auto max-w-3xl space-y-3"
            >
              {stacked ? <PaneHeading>{extraTab.label}</PaneHeading> : null}
              {extraTab.content}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
