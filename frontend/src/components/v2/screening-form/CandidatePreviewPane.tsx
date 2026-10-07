"use client";

/**
 * Podgląd obok formularza screeningu (0424, D3 „od razu z boku”, 07.10.2026).
 *
 * Do tej pory CV i wymagania otwierały się w oknach NAD formularzem — rekruter
 * w trakcie rozmowy zamykał arkusz, żeby sprawdzić, co kandydat napisał
 * o Kafce. Teraz prawa kolumna panelu osoby ma trzy zakładki:
 * - „CV” — oryginał (kopia ze zgłoszenia albo główne CV z profilu; DOCX też
 *   się renderuje), CV firmowe pary i pozostałe pliki CV z profilu,
 * - „Wymagania” — must/nice z Profilu Championa i warunki rekrutacji (klik
 *   w technologię szuka jej w CV),
 * - „Po ludzku” — jednym zdaniem o roli i ściąga do rozmowy.
 *
 * Ładowany za `next/dynamic` (pdf.js i `docx-preview` nie mogą wejść do
 * chunku Tablicy). Odwiedzone zakładki zostają zamontowane (`hidden`): powrót
 * do CV nie pobiera pliku drugi raz, a przeglądarka PDF dopasowuje szerokość
 * sama, gdy zakładka znów się pokaże.
 */

import { useCallback, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { TabbedNav } from "@/components/ds";
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
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { StageCvPreview } from "@/components/v2/person/StageCvPreview";
import { useStageBrandedCv } from "@/hooks/useStageBrandedCv";
import api, { candidateStageCvApi, type CVOriginalSnapshot } from "@/lib/api";
import { downloadAuthenticatedFile, fetchAuthenticatedBlob } from "@/lib/authenticated-files";
import { stageCvStatus } from "@/lib/cv-to-client";
import { dockOriginalCv, primaryProfileCv, type DockProfileCvDoc } from "@/lib/dock-cv-summary";
import { cn, formatDate } from "@/lib/utils";

export type PreviewTab = "cv" | "requirements" | "plain";
export type PreviewCvSource = "original" | "company" | "files";

const TABS: ReadonlyArray<{ value: PreviewTab; label: string }> = [
  { value: "cv", label: "CV" },
  { value: "requirements", label: "Wymagania" },
  { value: "plain", label: "Po ludzku" },
];

const SOURCES: ReadonlyArray<{ value: PreviewCvSource; label: string }> = [
  { value: "original", label: "CV oryginalne" },
  { value: "company", label: "CV firmowe" },
  { value: "files", label: "Inne pliki" },
];

/** Źródło bajtów kopii CV ze zgłoszenia (harness podaje plik statyczny). */
export type OriginalBlobLoader = (stageId: number) => Promise<Blob>;

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
}: CvTabProps) {
  const { showError } = useToast();
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
      body = (
        <Notice>
          CV firmowe jeszcze nie powstało — generuje się po przekazaniu osoby na „Zweryfikowany”. Wtedy zobaczysz je
          tutaj.
        </Notice>
      );
    } else {
      body = (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <StageCvPreview candidateId={candidateId} jobId={jobId} cvStageId={branded.cvStageId} fill />
        </div>
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
            className="min-h-0 flex-1 rounded-lg border border-border"
          />
        ) : null}
      </>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div role="group" aria-label="Które CV pokazać" className="inline-flex w-fit flex-wrap rounded-md border border-border bg-muted/30 p-0.5">
        {SOURCES.map((option) => (
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
          </button>
        ))}
      </div>
      {body}
    </div>
  );
}

// ── Całość ───────────────────────────────────────────────────────────────

export interface CandidatePreviewPaneProps {
  candidateId: number;
  jobId: number;
  /** Najnowszy wiersz etapu pary — kopia CV ze zgłoszenia i CV firmowe. */
  stageId: number | null;
  tab: PreviewTab;
  onTabChange: (tab: PreviewTab) => void;
  /** Górny budżet PLN/h z Tablicy — gdy rekrutacji nie ma w cache strony. */
  budgetHourly?: number | null;
  /** Harness: bajty plików bez sieci. */
  loadDocumentBlob?: typeof fetchDocumentBlob;
  loadOriginalBlob?: OriginalBlobLoader;
  className?: string;
}

export function CandidatePreviewPane({
  candidateId,
  jobId,
  stageId,
  tab,
  onTabChange,
  budgetHourly = null,
  loadDocumentBlob = fetchDocumentBlob,
  loadOriginalBlob = defaultOriginalLoader,
  className,
}: CandidatePreviewPaneProps) {
  const [source, setSource] = useState<PreviewCvSource>("original");
  const [searchRequest, setSearchRequest] = useState<{ text: string; nonce: number } | null>(null);
  const [visited, setVisited] = useState<ReadonlySet<PreviewTab>>(() => new Set([tab]));
  if (!visited.has(tab)) setVisited(new Set([...visited, tab]));

  // Klik w technologię w „Wymaganiach” — szukaj jej w CV. CV firmowe nie ma
  // paska wyszukiwania, więc przełączamy na oryginał.
  const pickRequirement = useCallback(
    (name: string) => {
      setSource((current) => (current === "company" ? "original" : current));
      setSearchRequest({ text: name, nonce: Date.now() });
      onTabChange("cv");
    },
    [onTabChange],
  );

  return (
    <section
      aria-label="Podgląd kandydata"
      data-testid="candidate-preview-pane"
      className={cn("flex min-h-0 flex-col gap-2", className)}
    >
      <TabbedNav
        ariaLabel="Podgląd: CV, wymagania, po ludzku"
        tabs={TABS.map(({ value, label }) => ({ value, label }))}
        value={tab}
        onValueChange={(next) => onTabChange(next as PreviewTab)}
        overflow="scroll"
        dense
      />
      {visited.has("cv") ? (
        <div role="tabpanel" aria-label="CV" hidden={tab !== "cv"} className="flex min-h-0 flex-1 flex-col">
          <CvTab
            candidateId={candidateId}
            jobId={jobId}
            stageId={stageId}
            source={source}
            onSourceChange={setSource}
            searchRequest={searchRequest}
            loadDocumentBlob={loadDocumentBlob}
            loadOriginalBlob={loadOriginalBlob}
          />
        </div>
      ) : null}
      {visited.has("requirements") ? (
        <div
          role="tabpanel"
          aria-label="Wymagania"
          hidden={tab !== "requirements"}
          className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1"
        >
          <p className="text-[11px] text-muted-foreground">Kliknij technologię, żeby znaleźć ją w CV kandydata.</p>
          <JobRequirementsSummary jobId={jobId} budgetHourly={budgetHourly} onPickRequirement={pickRequirement} />
        </div>
      ) : null}
      {visited.has("plain") ? (
        <div
          role="tabpanel"
          aria-label="Po ludzku"
          hidden={tab !== "plain"}
          className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1"
        >
          <PlainBriefBlock jobId={jobId} parts="summary" compact />
          <DockCallCheatsheet jobId={jobId} />
        </div>
      ) : null}
    </section>
  );
}
