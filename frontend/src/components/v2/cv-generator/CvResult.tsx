"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, Eye, Loader2, Pencil, RotateCcw, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import api, { cvGeneratorApi, type GeneratedCvItem } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { contentModeLabel, stageLabel } from "@/lib/cv-generator";

import { ConsentAttachButton } from "./ConsentAttachButton";
import { CvWarnings } from "./CvWarnings";
import { downloadGeneratedCv } from "./cv-generated-files";
import { GeneratedCvPreviewModal } from "./GeneratedCvPreviewModal";
import { StatusChip } from "./GeneratorParts";

// Edytor (TipTap + podgląd) tylko po kliknięciu „Edytuj”.
const CVBrandedEditModal = dynamic(
  () => import("@/components/v2/modals/CVBrandedEditModal").then((mod) => mod.CVBrandedEditModal),
  { ssr: false },
);

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
  onRegenerate?: () => void;
  onRetryPackage?: () => void;
  onDelete?: (doc: GeneratedCvItem) => void;
  onNew?: () => void;
}

/** Widok po generacji — ten sam dla „Generuj CV” i „Otwórz” na liście Moje CV. */
export function CvResultView(props: CvResultViewProps) {
  const main = props.documents.find((doc) => doc.id === props.mainId) ?? props.documents[0] ?? null;
  const processing = !main || props.documents.some((doc) => doc.status === "processing");
  const failed = props.documents.filter((doc) => doc.status === "failed");
  const ready = props.documents.filter((doc) => doc.status === "ready");
  const name = main?.candidate_name || props.fallbackTitle?.candidateName || "";
  const jobTitle = main?.job_title ?? main?.position ?? props.fallbackTitle?.jobTitle ?? null;
  const clientName = main?.client_name ?? props.fallbackTitle?.clientName ?? null;
  const consentMissing = props.documents.some((doc) => doc.consent_missing);
  const consentRequired = props.documents.some((doc) => doc.consent_required);
  const warnings = [...new Set(props.documents.flatMap((doc) => doc.warnings ?? []))];
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
                Ok. 40 s. Możesz zamknąć to okno — CV pojawi się na liście Moje CV.
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

        {props.attachedStage ? (
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
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={!doc.can_download || consentMissing}
                        title={consentMissing ? "Pobranie zablokowane — brak zrzutu zgody RODO" : undefined}
                        onClick={() => props.onDownload(doc)}
                      >
                        <Download aria-hidden className="mr-1.5 h-4 w-4" />Pobierz DOCX
                      </Button>
                    </span>
                  )}
                </li>
              ))}
            </ul>
            {failed.length > 0 && ready.length > 0 && props.onRetryPackage && props.canWrite ? (
              <Button type="button" variant="outline" size="sm" className="mt-2" onClick={props.onRetryPackage}>
                Ponów brakującą wersję językową
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

  async function download(doc: GeneratedCvItem) {
    const problem = await downloadGeneratedCv(doc);
    if (problem) toast.showError(problem);
  }

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
      void queryClient.invalidateQueries({ queryKey: ["cv-my-list"] });
      void queryClient.invalidateQueries({ queryKey: ["cv-generated"] });
      toast.showSuccess("Usunięto z listy.");
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
        jobHref={props.jobId && props.candidateId ? `/jobs/${props.jobId}?candidate=${props.candidateId}` : null}
        loading={query.isPending}
        error={query.isError}
        canWrite={props.canWrite}
        onPreview={setPreviewItem}
        onEdit={setEditItem}
        onDownload={(doc) => void download(doc)}
        onRegenerate={props.onRegenerate}
        onRetryPackage={() => void retryPackage()}
        onDelete={(doc) => void remove(doc)}
        onNew={props.onNew}
      />
      <GeneratedCvPreviewModal item={previewItem} onClose={() => setPreviewItem(null)} onDownload={(doc) => void download(doc)} />
      {editItem && props.canWrite ? (
        <CVBrandedEditModal
          open
          generatedId={editItem.id}
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
