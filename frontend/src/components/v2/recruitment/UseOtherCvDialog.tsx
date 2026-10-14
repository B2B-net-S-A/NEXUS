"use client";

/**
 * „Użyj innego CV” — okno karty „CV do klienta” (12.10.2026).
 *
 * Rekruter ma gotowe CV osoby i nie chce generować nowego. Trzy drogi do
 * szkicu bez generacji: CV etapu z innej rekrutacji (z jego poprawkami),
 * plik Word z profilu i plik Word z dysku. Wybrane CV otwiera się potem
 * w zwykłym edytorze CV etapu; źródło zostaje nietknięte.
 *
 * Dane i akcje przychodzą z `useReadyCvChoice` (jedna instancja w karcie),
 * więc okno niczego samo nie pobiera poza podglądem wskazanego CV.
 * Plik z dysku NIE trafia do plików kandydata — w teczce mógłby stać się
 * „aktualnym CV” osoby i źródłem dla generatora.
 */

import { useId, useState } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Upload } from "lucide-react";

import { candidateStageCvApi, type CVBrandedState } from "@/lib/api";
import { stageBrandedQueryKey } from "@/lib/cv-to-client";
import type { StageCvOption } from "@/lib/stage-cv-options";
import { useToast } from "@/components/Toast";
import { FileDropZone } from "@/components/ds";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CvFilePreviewDialog } from "@/components/v2/cv/CvFilePreviewDialog";
import { normalizeCvAlign } from "@/lib/cv-editor-align";
import { fetchStageCvFile, fetchStageCvPdf } from "@/lib/stage-cv-file";
import type { ReadyCvChoice } from "@/components/v2/recruitment/useReadyCvChoice";
import { StageCvPicker } from "@/components/v2/screening-form/StageCvPicker";

// Podgląd pliku ciągnie pdf.js i docx-preview — dopiero po kliknięciu.
const FilePreviewModal = dynamic(
  () => import("@/components/v2/files/FilePreviewModal").then((m) => m.FilePreviewModal),
  { ssr: false },
);

/** Limit konwertera Word → edytor (`cv_docx_import.MAX_BYTES`). */
const MAX_DOCX_BYTES = 10 * 1024 * 1024;

export interface UseOtherCvDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  candidateName: string;
  jobLabel: string;
  choice: ReadyCvChoice;
  /** Para ma już CV — tytuł i ostrzeżenie mówią o zastąpieniu. */
  replaces: boolean;
}

export function UseOtherCvDialog({
  open,
  onOpenChange,
  candidateId,
  candidateName,
  jobLabel,
  choice,
  replaces,
}: UseOtherCvDialogProps) {
  const inputId = useId();
  const { showError } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [previewDocumentId, setPreviewDocumentId] = useState<number | null>(null);
  const [previewStage, setPreviewStage] = useState<StageCvOption | null>(null);

  // Treść CV z innej rekrutacji — ten sam odczyt (i ta sama bramka zakresu)
  // co karta tamtej rekrutacji, pod wspólnym kluczem.
  const previewStageId = previewStage?.previewStageId ?? null;
  const stagePreviewQuery = useQuery<CVBrandedState>({
    queryKey: stageBrandedQueryKey(previewStageId),
    queryFn: () => candidateStageCvApi.branded.get(previewStageId as number).then((r) => r.data),
    enabled: previewStageId != null,
    retry: false,
  });

  const busy = choice.busyKey != null || choice.uploading;
  const empty = !choice.isPending && !choice.isError && choice.options.total === 0;
  const previewDocument = choice.documents.find((doc) => doc.id === previewDocumentId) ?? null;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent size="lg" className="flex flex-col p-0">
          <DialogHeader>
            <DialogTitle>{replaces ? "Użyj innego CV" : "Użyj gotowego CV"}</DialogTitle>
            <DialogDescription>
              {candidateName} · {jobLabel}. Wybrane CV stanie się szkicem tej rekrutacji — poprawisz
              je w edytorze. Źródło zostaje bez zmian.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            {choice.isError ? (
              // Awaria NIE może wyglądać jak „ta osoba nie ma gotowego CV”.
              <p role="alert" className="text-xs text-destructive-muted-foreground">
                Nie udało się wczytać listy gotowych CV.{" "}
                <button
                  type="button"
                  className="font-medium underline underline-offset-2"
                  onClick={() => choice.refetch()}
                >
                  Ponów
                </button>
              </p>
            ) : null}
            {empty ? (
              <p className="text-sm text-muted-foreground" data-testid="use-other-cv-empty">
                Ta osoba nie ma jeszcze gotowego CV w innych rekrutacjach ani pliku Word „B2B”
                w profilu. Możesz wgrać plik z dysku.
              </p>
            ) : (
              <StageCvPicker
                options={choice.options}
                isPending={choice.isPending}
                busyKey={busy ? (choice.busyKey ?? "upload") : null}
                onChoose={(option) => void choice.choose(option)}
                onPreviewDocument={setPreviewDocumentId}
                onPreviewStage={setPreviewStage}
                intro="CV z innej rekrutacji wchodzi w wersji po poprawkach rekrutera. Nagłówek CV z generatora dostaje tytuł tej rekrutacji; w CV wczytanym z pliku Word zostaje z pliku — sprawdź go."
              />
            )}

            <section aria-label="Plik z dysku" className="space-y-2">
              <h4 className="text-xs font-semibold text-muted-foreground">Plik z dysku</h4>
              <FileDropZone
                className="relative"
                inputId={inputId}
                file={file}
                accept=".docx"
                maxBytes={MAX_DOCX_BYTES}
                label="Wgraj plik CV z dysku"
                hint="Word (.docx), do 10 MB — przeciągnij tutaj albo wybierz z dysku"
                error={fileError}
                onError={setFileError}
                disabled={busy}
                onPick={(picked) => {
                  setFileError(null);
                  setFile(picked);
                }}
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  disabled={file == null || busy}
                  loading={choice.uploading}
                  onClick={() => {
                    if (file) void choice.upload(file);
                  }}
                >
                  <Upload className="h-3.5 w-3.5" aria-hidden /> Użyj tego pliku
                </Button>
                <p className="min-w-0 flex-1 basis-48 text-[11px] text-muted-foreground">
                  Treść wchodzi do edytora bez AI. Plik nie trafia do plików kandydata; PDF-a nie
                  da się wczytać do edytora.
                </p>
              </div>
            </section>
          </DialogBody>
          <DialogFooter className="sm:items-center sm:justify-between">
            {replaces ? (
              <p className="flex min-w-0 items-start gap-1.5 text-xs text-warning-muted-foreground">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                <span>
                  Wybrane CV zastąpi bieżący szkic tej rekrutacji. Zatwierdzone wersje zostają.
                </span>
              </p>
            ) : (
              <span />
            )}
            <Button size="sm" variant="outline" onClick={() => onOpenChange(false)}>
              Zamknij
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {previewDocument ? (
        <FilePreviewModal
          doc={previewDocument}
          candidateId={candidateId}
          onClose={() => setPreviewDocumentId(null)}
          onDownload={(doc) =>
            import("@/components/v2/files/FilePreviewModal")
              .then((m) => m.downloadDocumentBlob(candidateId, doc))
              .catch(() => showError("Nie udało się pobrać pliku."))
          }
        />
      ) : null}
      {previewStage && previewStageId != null ? (
        <CvFilePreviewDialog
          open
          onOpenChange={(next) => {
            if (!next) setPreviewStage(null);
          }}
          title={`${previewStage.title} — ${candidateName}`}
          loadPdf={() => fetchStageCvPdf(previewStageId).then((file) => file.blob)}
          load={() => fetchStageCvFile(previewStageId).then((file) => file.blob)}
          fallbackHtml={stagePreviewQuery.isSuccess ? (stagePreviewQuery.data.content_html ?? null) : null}
          language={stagePreviewQuery.data?.language === "en" ? "en" : "pl"}
          textAlign={normalizeCvAlign(stagePreviewQuery.data?.text_align)}
        />
      ) : null}
    </>
  );
}
