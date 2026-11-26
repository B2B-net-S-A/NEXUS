"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, Eye, Loader2, Pencil, RotateCcw, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import api, { candidateStageCvApi, cvGeneratorApi, type GeneratedCvItem } from "@/lib/api";
import { useStageBrandedCv } from "@/hooks/useStageBrandedCv";
import { stageBrandedQueryKey } from "@/lib/cv-to-client";
import { apiErrorMessage } from "@/lib/api-error";
import { contentModeLabel, downloadBlob, stageLabel } from "@/lib/cv-generator";
import { CV_FILE_FORMAT_LABEL, cvFileFormat, type CvFileFormat } from "@/lib/cv-file-format";
import { fetchStageCvFile, fetchStageCvPdf } from "@/lib/stage-cv-file";

import { ConsentAttachButton } from "./ConsentAttachButton";
import { CvWarnings } from "./CvWarnings";
import { useClientCvRule } from "./ClientCvRuleBanner";
import { downloadGeneratedCv, downloadGeneratedCvPdf } from "./cv-generated-files";
import { GeneratedCvPreviewModal } from "./GeneratedCvPreviewModal";
import { StatusChip } from "./GeneratorParts";

// Edytor (TipTap + podgląd) tylko po kliknięciu „Edytuj”.
const CVBrandedEditModal = dynamic(
  () => import("@/components/v2/modals/CVBrandedEditModal").then((mod) => mod.CVBrandedEditModal),
  { ssr: false },
);

/**
 * Etap, którego CV jest w „Nowym CV” (26.11.2026). Wtedy wynik generatora
 * pokazuje i pobiera CV z karty etapu, bo surowy plik generacji jest klasyczny.
 */
export function newLayoutStageId(doc: GeneratedCvItem): number | null {
  return doc.stage_cv_layout === "new" && doc.stage_cv_stage_id != null ? doc.stage_cv_stage_id : null;
}

/** Dokumenty jednej generacji: główny + drugi język z tego samego pakietu. */
export function packageDocuments(items: readonly GeneratedCvItem[], mainId: number): GeneratedCvItem[] {
  const docs = items.filter((item) => item.id === mainId || item.package_id === mainId);
  return [...docs].sort((a, b) => (a.id === mainId ? -1 : b.id === mainId ? 1 : a.language.localeCompare(b.language)));
}

export interface CvResultViewProps {
  mainId: number;
  documents: readonly GeneratedCvItem[];
  /** Dane z formularza — zanim lista dojdzie z serwera. */
  fallbackTitle?: { candidateName: string; jobTitle: string | null; clientName: string | null };
  /** Etap, do którego CV trafi jako „CV do klienta” (ręczna generacja z procesu). */
  attachedStage?: string | null;
  jobHref?: string | null;
  loading?: boolean;
  error?: boolean;
  canWrite: boolean;
  onPreview: (doc: GeneratedCvItem) => void;
  onEdit: (doc: GeneratedCvItem) => void;
  onDownload: (doc: GeneratedCvItem) => void;
  /** Plik, którego chce klient (reguła CV, 25.11.2026); `null` = bez wymagań (sam DOCX). */
  fileFormat?: CvFileFormat | null;
  onDownloadPdf?: (doc: GeneratedCvItem) => void;
  onRegenerate?: () => void;
  onRetryPackage?: () => void;
  onDelete?: (doc: GeneratedCvItem) => void;
  onNew?: () => void;
  /**
   * Etap miał już inne CV, więc ta generacja nie trafiła do rekrutacji
   * (26.11.2026, wybór Artura): ekran mówi to wprost i daje podmianę.
   */
  stageConflict?: StageConflict | null;
}

export interface StageConflict {
  /** Kiedy ostatnio zmieniono CV etapu (ISO). */
  since: string | null;
  busy: boolean;
  onUse: () => void;
  onKeep: () => void;
}

function dayMonth(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : ` z ${d.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", timeZone: "Europe/Warsaw" })}`;
}

/** Widok po generacji w oknie generatora (profil kandydata, panel osoby). */
export function CvResultView(props: CvResultViewProps) {
  const main = props.documents.find((doc) => doc.id === props.mainId) ?? props.documents[0] ?? null;
  const processing = !main || props.documents.some((doc) => doc.status === "processing");
  const failed = props.documents.filter((doc) => doc.status === "failed");
  const ready = props.documents.filter((doc) => doc.status === "ready");
  // Generacja urwana w trakcie (zwykle deploy): serwer wznawia to samo zadanie.
  const interrupted = main?.status === "failed" && main.job_status === "interrupted";
  const name = main?.candidate_name || props.fallbackTitle?.candidateName || "";
  const jobTitle = main?.job_title ?? main?.position ?? props.fallbackTitle?.jobTitle ?? null;
  const clientName = main?.client_name ?? props.fallbackTitle?.clientName ?? null;
  const consentMissing = props.documents.some((doc) => doc.consent_missing);
  const consentRequired = props.documents.some((doc) => doc.consent_required);
  const warnings = [...new Set(props.documents.flatMap((doc) => doc.warnings ?? []))];
  // Format z reguły klienta: PDF na pierwszym miejscu albo obok DOCX; bez wymagań — sam DOCX.
  // Generacja w „Nowym CV”: plik wyniku jest klasyczny. Gdy CV trafiło już do etapu
  // w Nowym CV (26.11.2026), pliki i podgląd idą z karty etapu: PDF Nowego CV
  // i Word nowego wyglądu, z poprawkami z edytora.
  const wantsPdf = props.fileFormat === "pdf" || props.fileFormat === "both";
  const newLayoutResult = main?.cv_layout === "new";
  const stageNew = main ? newLayoutStageId(main) !== null : false;
  const pdfAllowed = !!props.onDownloadPdf && (stageNew || (wantsPdf && !newLayoutResult));
  const downloadKinds: ("docx" | "pdf")[] = !pdfAllowed
    ? ["docx"]
    : stageNew
      ? props.fileFormat === "docx"
        ? ["docx", "pdf"]
        : ["pdf", "docx"]
      : props.fileFormat === "pdf"
        ? ["pdf", "docx"]
        : ["docx", "pdf"];
  const subtitle = [main?.content_mode ? contentModeLabel(main.content_mode) : null, jobTitle, clientName]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="space-y-4" aria-live="polite">
      <section aria-label="Wynik generacji" className="rounded-xl border border-border bg-card p-5">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
              {processing ? (
                <Loader2 aria-hidden className="h-5 w-5 animate-spin text-primary" />
              ) : failed.length && !ready.length ? (
                <AlertTriangle aria-hidden className="h-5 w-5 text-destructive" />
              ) : (
                <CheckCircle2 aria-hidden className="h-5 w-5 text-success" />
              )}
              {processing
                ? `Generuję CV — ${name}`
                : failed.length && !ready.length
                  ? `CV nie powstało — ${name}`
                  : `CV gotowe — ${name}`}
            </h2>
            {subtitle ? <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p> : null}
            {processing ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Ok. 40 s. Możesz zamknąć to okno — gotowe CV znajdziesz w plikach kandydata.
              </p>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            {props.onRegenerate ? (
              <Button type="button" variant="outline" size="sm" onClick={props.onRegenerate}>
                <RotateCcw aria-hidden className="mr-1.5 h-4 w-4" />
                Wygeneruj ponownie
              </Button>
            ) : null}
            {props.onNew ? (
              <Button type="button" variant="outline" size="sm" onClick={props.onNew}>
                Nowe CV
              </Button>
            ) : null}
          </div>
        </div>

        {props.stageConflict ? (
          <div
            role="status"
            data-testid="cv-result-stage-conflict"
            className="mt-4 space-y-2 rounded-lg border border-warning/30 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
          >
            <p className="flex items-start gap-2">
              <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 flex-none" />
              <span>
                Etap ma już CV do klienta{dayMonth(props.stageConflict.since)}. Ta wersja nie trafiła do rekrutacji.
                Po podmianie poprzednią przywrócisz w karcie „CV do klienta” („Wróć do poprzedniej”).
              </span>
            </p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" size="sm" disabled={props.stageConflict.busy} onClick={props.stageConflict.onUse}>
                {props.stageConflict.busy ? "Używam…" : "Użyj tej wersji w rekrutacji"}
              </Button>
              <Button type="button" size="sm" variant="outline" disabled={props.stageConflict.busy} onClick={props.stageConflict.onKeep}>
                Zostaw stare
              </Button>
            </div>
          </div>
        ) : props.attachedStage ? (
          <div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg bg-success-muted px-3 py-2 text-sm text-success-muted-foreground">
            <CheckCircle2 aria-hidden className="h-4 w-4" />
            <span>
              {processing ? "Po wygenerowaniu trafi do procesu" : "Podpięte do procesu"} jako CV do klienta
              {` (etap ${stageLabel(props.attachedStage)})`}, jeśli etap nie miał jeszcze CV.
            </span>
            {props.jobHref ? (
              <a href={props.jobHref} className="ml-auto font-medium text-primary hover:underline">
                Otwórz rekrutację →
              </a>
            ) : null}
          </div>
        ) : null}

        {props.error ? (
          <p role="alert" className="mt-4 text-sm text-destructive">
            Nie udało się wczytać stanu CV. Spróbuj ponownie za chwilę.
          </p>
        ) : null}

        {props.documents.length > 0 ? (
          <div className="mt-4">
            <h3 className="mb-2 text-sm font-semibold text-foreground">
              {props.documents.length > 1 ? "Dokumenty — wybrano „Obie”" : "Dokument"}
            </h3>
            <ul className="divide-y divide-border rounded-lg border border-border">
              {props.documents.map((doc) => (
                <li key={doc.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                  <StatusChip tone="info">{doc.language.toUpperCase()}</StatusChip>
                  <span className="min-w-0 flex-1 truncate font-mono text-xs text-foreground">{doc.filename}</span>
                  {doc.status === "processing" ? (
                    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" />
                      {doc.job_status === "queued" ? "czeka w kolejce" : "generuje się…"}
                    </span>
                  ) : doc.status === "failed" ? (
                    <span className="text-xs text-destructive">{doc.error_message || "nie powstało"}</span>
                  ) : (
                    <span className="flex flex-wrap gap-1">
                      <Button type="button" variant="ghost" size="sm" disabled={!doc.can_download && !doc.consent_missing} onClick={() => props.onPreview({ ...doc, consent_missing: doc.consent_missing || consentMissing })}>
                        <Eye aria-hidden className="mr-1.5 h-4 w-4" />Podgląd
                      </Button>
                      {props.canWrite ? (
                        <Button type="button" variant="ghost" size="sm" onClick={() => props.onEdit(doc)}>
                          <Pencil aria-hidden className="mr-1.5 h-4 w-4" />Edytuj
                        </Button>
                      ) : null}
                      {downloadKinds.map((kind) => (
                        <Button
                          key={kind}
                          type="button"
                          variant="outline"
                          size="sm"
                          data-testid={`cv-result-download-${kind}`}
                          disabled={!doc.can_download || consentMissing}
                          title={consentMissing ? "Pobranie zablokowane — brak zrzutu zgody RODO" : undefined}
                          onClick={() => (kind === "pdf" ? props.onDownloadPdf?.(doc) : props.onDownload(doc))}
                        >
                          <Download aria-hidden className="mr-1.5 h-4 w-4" />
                          {kind === "pdf" ? "Pobierz PDF" : stageNew ? "Pobierz Word" : "Pobierz DOCX"}
                        </Button>
                      ))}
                    </span>
                  )}
                </li>
              ))}
            </ul>
            {wantsPdf && props.fileFormat ? (
              <p className="mt-2 text-xs text-muted-foreground" data-testid="cv-result-client-format">
                Klient chce: {CV_FILE_FORMAT_LABEL[props.fileFormat]}
                {newLayoutResult && !stageNew
                  ? ". PDF w układzie „Nowe CV” pobierzesz z karty „CV do klienta” w rekrutacji — plik DOCX stąd jest klasyczny."
                  : null}
              </p>
            ) : null}
            {((failed.length > 0 && ready.length > 0) || interrupted) && props.onRetryPackage && props.canWrite ? (
              <Button type="button" variant="outline" size="sm" className="mt-2" onClick={props.onRetryPackage}>
                {interrupted ? "Ponów generację" : "Ponów brakującą wersję językową"}
              </Button>
            ) : null}
          </div>
        ) : null}

        {main && ready.length > 0 && consentMissing ? (
          <div className="mt-4 space-y-2 rounded-lg border border-warning/30 bg-warning-muted p-3 text-sm text-warning-muted-foreground">
            <p>
              <strong className="font-semibold">Pobranie zablokowane.</strong>{" "}
              {clientName ?? "Klient"} wymaga zrzutu maila, w którym kandydat zgadza się na przetwarzanie
              danych. Zrzut trafi na koniec CV.
            </p>
            {props.canWrite ? <ConsentAttachButton generatedId={main.id} hasConsent={false} /> : null}
          </div>
        ) : main && ready.length > 0 && consentRequired && props.canWrite ? (
          <div className="mt-4 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <StatusChip tone="ok">zrzut zgody dołączony</StatusChip>
            <ConsentAttachButton generatedId={main.id} hasConsent compact />
          </div>
        ) : null}

        {main && props.onDelete && main.can_delete && props.canWrite && !processing ? (
          <div className="mt-4 border-t border-border pt-3">
            <Button type="button" variant="ghost" size="sm" onClick={() => props.onDelete?.(main)}>
              <Trash2 aria-hidden className="mr-1.5 h-4 w-4" />Usuń z listy
            </Button>
          </div>
        ) : null}
      </section>

      {ready.length > 0 ? (
        <CvWarnings warnings={warnings} onShowInCv={() => main && props.onPreview(main)} />
      ) : null}
    </div>
  );
}

export interface CvResultLiveProps {
  mainId: number;
  candidateId?: number | null;
  /** Etap wybrany w generatorze — do sprawdzenia, czy CV do niego trafiło. */
  stageId?: number | null;
  fallbackTitle?: CvResultViewProps["fallbackTitle"];
  attachedStage?: string | null;
  jobId?: number | null;
  canWrite: boolean;
  onRegenerate?: () => void;
  onNew?: () => void;
  onDeleted?: () => void;
}

/** Widok wyniku z danymi z serwera: odpytuje listę, dopóki CV się generuje. */
export function CvResultLive(props: CvResultLiveProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [previewItem, setPreviewItem] = useState<GeneratedCvItem | null>(null);
  const [editItem, setEditItem] = useState<GeneratedCvItem | null>(null);
  const query = useQuery({
    queryKey: ["cv-result", props.mainId, props.candidateId ?? null],
    queryFn: async () => {
      const { data } = await cvGeneratorApi.listGenerated(
        props.candidateId
          ? { candidate_id: props.candidateId, limit: 40 }
          : { mine: true, days: 2, limit: 40 },
      );
      return packageDocuments(data, props.mainId);
    },
    refetchInterval: (q) => {
      const docs = q.state.data;
      return !docs?.length || docs.some((doc) => doc.status === "processing") ? 4000 : false;
    },
  });
  const documents = query.data ?? [];

  // Etap miał już inne CV (26.11.2026): generacja nie trafiła do rekrutacji.
  const main = documents.find((doc) => doc.id === props.mainId) ?? null;
  const notAttached = !!main && main.status === "ready" && main.stage_cv_stage_id == null && props.stageId != null;
  const stageCv = useStageBrandedCv(props.stageId ?? null, { enabled: notAttached });
  const existing = stageCv.ownQuery.data;
  const [kept, setKept] = useState(false);
  const applyVersion = useMutation({
    mutationFn: async () => {
      const stageId = props.stageId as number;
      const revision = existing?.edit_revision ?? 0;
      return (await candidateStageCvApi.branded.selectGenerated(stageId, props.mainId, revision)).data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: stageBrandedQueryKey(props.stageId ?? null) });
      void queryClient.invalidateQueries({ queryKey: ["cv-generated"] });
      void query.refetch();
      toast.showSuccess("Ta wersja jest teraz CV do klienta w rekrutacji.");
    },
    onError: (error) => toast.showError(apiErrorMessage(error, "Nie udało się użyć tej wersji w rekrutacji.")),
  });
  const stageConflict: StageConflict | null =
    notAttached && !kept && existing && existing.status !== "none" && existing.generated_document_id !== props.mainId
      ? {
          since: existing.updated_at ?? null,
          busy: applyVersion.isPending,
          onUse: () => applyVersion.mutate(),
          onKeep: () => setKept(true),
        }
      : null;

  async function downloadStage(stageId: number, doc: GeneratedCvItem, pdf: boolean) {
    try {
      const file = pdf ? await fetchStageCvPdf(stageId, { download: "mine" }) : await fetchStageCvFile(stageId, { download: "mine" });
      downloadBlob(file.blob, file.filename || doc.filename);
    } catch (error) {
      toast.showError(apiErrorMessage(error, pdf ? "Nie udało się pobrać PDF. Spróbuj za chwilę." : "Nie udało się pobrać CV."));
    }
  }

  async function download(doc: GeneratedCvItem) {
    const stageId = newLayoutStageId(doc);
    if (stageId !== null) return downloadStage(stageId, doc, false);
    const problem = await downloadGeneratedCv(doc);
    if (problem) toast.showError(problem);
  }

  async function downloadPdf(doc: GeneratedCvItem) {
    const stageId = newLayoutStageId(doc);
    if (stageId !== null) return downloadStage(stageId, doc, true);
    const problem = await downloadGeneratedCvPdf(doc);
    if (problem) toast.showError(problem);
  }

  // Format pliku z reguły klienta tej generacji (ten sam odczyt co baner generatora).
  const clientId = (documents.find((doc) => doc.id === props.mainId) ?? documents[0])?.client_id ?? null;
  const ruleQuery = useClientCvRule(clientId);
  const fileFormat = ruleQuery.data?.is_active ? cvFileFormat(ruleQuery.data.cv_file_format) : null;

  async function retryPackage() {
    try {
      await api.post(`/api/cv-generator/generated/${props.mainId}/package/retry`, {});
      await query.refetch();
    } catch (error) {
      toast.showError(apiErrorMessage(error, "Nie udało się ponowić brakującej wersji."));
    }
  }

  async function remove(doc: GeneratedCvItem) {
    try {
      await cvGeneratorApi.deleteGenerated(doc.id);
      void queryClient.invalidateQueries({ queryKey: ["cv-generated"] });
      toast.showSuccess("Usunięto CV.");
      props.onDeleted?.();
    } catch (error) {
      toast.showError(apiErrorMessage(error, "Nie udało się usunąć wpisu."));
    }
  }

  return (
    <>
      <CvResultView
        mainId={props.mainId}
        documents={documents}
        fallbackTitle={props.fallbackTitle}
        attachedStage={props.attachedStage}
        stageConflict={stageConflict}
        jobHref={props.jobId && props.candidateId ? `/jobs/${props.jobId}?candidate=${props.candidateId}` : null}
        loading={query.isPending}
        error={query.isError}
        canWrite={props.canWrite}
        onPreview={setPreviewItem}
        onEdit={setEditItem}
        onDownload={(doc) => void download(doc)}
        fileFormat={fileFormat}
        onDownloadPdf={(doc) => void downloadPdf(doc)}
        onRegenerate={props.onRegenerate}
        onRetryPackage={() => void retryPackage()}
        onDelete={(doc) => void remove(doc)}
        onNew={props.onNew}
      />
      <GeneratedCvPreviewModal
        item={previewItem}
        onClose={() => setPreviewItem(null)}
        onDownload={(doc) => void download(doc)}
        loadDocx={
          previewItem && newLayoutStageId(previewItem) !== null
            ? (doc) => fetchStageCvFile(newLayoutStageId(doc) as number).then((file) => file.blob)
            : undefined
        }
      />
      {editItem && props.canWrite ? (
        <CVBrandedEditModal
          open
          // Nowe CV: edycja w CV etapu (zakładka „Strona 1”), nie w pliku generacji.
          {...(newLayoutStageId(editItem) !== null
            ? { stageId: newLayoutStageId(editItem) as number }
            : { generatedId: editItem.id, generatorWarnings: editItem.warnings ?? [] })}
          candidateName={editItem.candidate_name}
          onRegenerate={() => {
            setEditItem(null);
            props.onRegenerate?.();
          }}
          onOpenChange={(open) => {
            if (!open) {
              setEditItem(null);
              void query.refetch();
            }
          }}
        />
      ) : null}
    </>
  );
}
