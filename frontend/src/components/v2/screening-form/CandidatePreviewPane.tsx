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
 * Ładowany za `next/dynamic` (pdf.js i `docx-preview` nie mogą wejść do
 * chunku Tablicy). Odwiedzone zakładki zostają zamontowane (`hidden`): powrót
 * do CV nie pobiera pliku drugi raz, a przeglądarka PDF dopasowuje szerokość
 * sama, gdy zakładka znów się pokaże.
 */

import { useCallback, useMemo, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Pencil, Replace } from "lucide-react";

import { TabbedNav } from "@/components/ds";
import { Button } from "@/components/ui/button";
import { JobRequirementsSummary } from "@/components/champion/JobRequirementsSummary";
import { PlainBriefBlock } from "@/components/champion/plain/PlainBriefBlock";
import { useToast } from "@/components/Toast";
import {
  FilePreviewContent,
  downloadDocumentBlob,
  fetchDocumentBlob,
  type CandidateDocument,
} from "@/components/v2/files/FilePreviewModal";
import { DockCallCheatsheet } from "@/components/v2/jobs/DockCallCheatsheet";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { StageCvPreview } from "@/components/v2/person/StageCvPreview";
import {
  StageCvPicker,
  useChooseStageCv,
  useStageCvOptions,
} from "@/components/v2/screening-form/StageCvPicker";
import { useStageBrandedCv } from "@/hooks/useStageBrandedCv";
import api, { candidateStageCvApi, type CVOriginalSnapshot } from "@/lib/api";
import { downloadAuthenticatedFile, fetchAuthenticatedBlob } from "@/lib/authenticated-files";
import { stageBrandedQueryKey, stageCvStatus } from "@/lib/cv-to-client";
import { dockOriginalCv, primaryProfileCv, type DockProfileCvDoc } from "@/lib/dock-cv-summary";
import type { fetchStageCvFile } from "@/lib/stage-cv-file";
import type { StageCvOption } from "@/lib/stage-cv-options";
import { useElementWidth } from "@/lib/use-element-width";
import { cn, formatDate } from "@/lib/utils";

export type PreviewTab = "cv" | "requirements" | "plain" | "extra";
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

const defaultOriginalLoader: OriginalBlobLoader = (stageId) =>
  fetchAuthenticatedBlob(originalDownloadPath(stageId));

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
  searchRequest: { text: string; nonce: number } | null;
  loadDocumentBlob: typeof fetchDocumentBlob;
  loadOriginalBlob: OriginalBlobLoader;
  /** Które źródła pokazać w przełączniku (przegląd DL ma CV firmowe osobno). */
  sources?: ReadonlyArray<PreviewCvSource>;
  cvActions?: PreviewCvActions;
  loadStageCvFile?: typeof fetchStageCvFile;
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
  loadStageCvFile,
}: CvTabProps) {
  const { showError } = useToast();
  const queryClient = useQueryClient();
  const { askConfirm, confirmDialog } = useConfirmV2();
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

  const original = dockOriginalCv({
    snapshot: snapshotQuery.data,
    snapshotLoading: stageId != null && snapshotQuery.isLoading,
    profileDocs: docsQuery.data as DockProfileCvDoc[] | undefined,
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
  const profileDoc = original.kind === "profile" ? (docsQuery.data ?? []).find((d) => d.id === original.doc.id) ?? null : null;

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
      body = (
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
              fill
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
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div role="group" aria-label="Które CV pokazać" className="inline-flex w-fit flex-wrap rounded-md border border-border bg-muted/30 p-0.5">
        {SOURCES.filter((option) => !sources || sources.includes(option.value)).map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={source === option.value}
            onClick={() => onSourceChange(option.value)}
            className={cn(
              "rounded px-2.5 py-1 text-xs font-medium transition-colors pointer-coarse:py-2",
              source === option.value
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
      {body}
      {confirmDialog}
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
    </div>
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
}: CandidateCvPreviewProps) {
  const [source, setSource] = useState<PreviewCvSource>(defaultSource);
  return (
    <CvTab
      candidateId={candidateId}
      jobId={jobId}
      stageId={stageId}
      source={source}
      onSourceChange={setSource}
      searchRequest={null}
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
  /** Harness: bajty plików bez sieci. */
  loadDocumentBlob?: typeof fetchDocumentBlob;
  loadOriginalBlob?: OriginalBlobLoader;
  loadStageCvFile?: typeof fetchStageCvFile;
  className?: string;
}

function PaneHeading({ children }: { children: string }) {
  return <h3 className="text-sm font-semibold text-foreground">{children}</h3>;
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
  loadDocumentBlob = fetchDocumentBlob,
  loadOriginalBlob = defaultOriginalLoader,
  loadStageCvFile,
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

  const [searchRequest, setSearchRequest] = useState<{ text: string; nonce: number } | null>(null);
  const [visited, setVisited] = useState<ReadonlySet<PreviewTab>>(() => new Set([tab]));
  if (!visited.has(tab)) setVisited(new Set([...visited, tab]));

  const [root, setRoot] = useState<HTMLElement | null>(null);
  const dual = useElementWidth(root) >= DUAL_MIN_WIDTH;
  // Dwa podglądy naraz zamontowały już wszystko; po zwężeniu okna do zakładek
  // nic nie odmontowujemy, żeby CV nie pobierało się drugi raz.
  const [everDual, setEverDual] = useState(false);
  if (dual && !everDual) setEverDual(true);
  const shown = (value: PreviewTab) => dual || everDual || visited.has(value);
  const panelHidden = (value: PreviewTab) => !dual && tab !== value;

  // „Szukaj w CV” przy wymaganiu. CV firmowe nie ma paska wyszukiwania, więc
  // przełączamy na oryginał.
  const pickRequirement = useCallback(
    (name: string) => {
      setPickedSource((current) => {
        const effective = current ?? (companyReady ? "company" : "original");
        return effective === "company" ? "original" : current;
      });
      setSearchRequest({ text: name, nonce: Date.now() });
      changeTab("cv");
    },
    [changeTab, companyReady],
  );

  const tabs = extraTab ? [...TABS, { value: "extra" as const, label: extraTab.label }] : TABS;
  const panelRole = dual ? "region" : "tabpanel";

  return (
    <section
      ref={setRoot}
      aria-label="Podgląd kandydata"
      data-testid="candidate-preview-pane"
      data-dual={dual || undefined}
      className={cn("flex min-h-0 flex-col", className)}
    >
      <div hidden={dual} className="flex-none border-b border-border bg-background px-3 pt-2">
        <TabbedNav
          ariaLabel="Podgląd: CV, wymagania, po ludzku"
          tabs={tabs.map(({ value, label }) => ({ value, label }))}
          value={tab}
          onValueChange={(next) => changeTab(next as PreviewTab)}
          overflow="scroll"
        />
      </div>
      <div className="flex min-h-0 flex-1">
        {shown("cv") ? (
          <div
            role={panelRole}
            aria-label="CV"
            hidden={panelHidden("cv")}
            className="flex min-h-0 min-w-0 flex-1 flex-col p-3"
          >
            <CvTab
              candidateId={candidateId}
              jobId={jobId}
              stageId={stageId}
              source={source}
              onSourceChange={setPickedSource}
              searchRequest={searchRequest}
              loadDocumentBlob={loadDocumentBlob}
              loadOriginalBlob={loadOriginalBlob}
              cvActions={cvActions}
              loadStageCvFile={loadStageCvFile}
            />
          </div>
        ) : null}
        <div
          hidden={!dual && tab === "cv"}
          data-testid="candidate-preview-info"
          className={cn(
            "min-h-0 overflow-y-auto bg-background p-4",
            dual ? "w-[440px] flex-none space-y-6 border-l border-border" : "min-w-0 flex-1",
          )}
        >
          {shown("requirements") ? (
            <div
              role={panelRole}
              aria-label="Wymagania"
              hidden={panelHidden("requirements")}
              className="mx-auto max-w-4xl space-y-3"
            >
              {dual ? <PaneHeading>Wymagania</PaneHeading> : null}
              <JobRequirementsSummary jobId={jobId} budgetHourly={budgetHourly} onPickRequirement={pickRequirement} />
            </div>
          ) : null}
          {shown("plain") ? (
            <div
              role={panelRole}
              aria-label="Po ludzku"
              hidden={panelHidden("plain")}
              className="mx-auto max-w-3xl space-y-4"
            >
              {dual ? <PaneHeading>Po ludzku</PaneHeading> : null}
              <PlainBriefBlock jobId={jobId} parts="summary" compact={dual} />
              <DockCallCheatsheet jobId={jobId} roomy={!dual} />
            </div>
          ) : null}
          {extraTab && shown("extra") ? (
            <div
              role={panelRole}
              aria-label={extraTab.label}
              hidden={panelHidden("extra")}
              className="mx-auto max-w-3xl space-y-3"
            >
              {dual ? <PaneHeading>{extraTab.label}</PaneHeading> : null}
              {extraTab.content}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
