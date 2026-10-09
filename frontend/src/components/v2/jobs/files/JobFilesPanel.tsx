"use client";

/**
 * Lista plików rekrutacji z dodawaniem, podglądem, pobraniem i usuwaniem
 * (0427, 09.10.2026). Ten sam panel stoi w dwóch miejscach:
 *
 * - `/jobs/new`, karta „Pliki” — pliki wiszą na niedokończonym formularzu.
 *   Formularza może jeszcze nie być, więc pierwszy upload woła `ensureOwner`
 *   (zapis formularza), a serwer przepina pliki na rekrutację przy „Utwórz”.
 * - strona rekrutacji, menu „⋯” → „Pliki” — widzi je każdy, dodaje i usuwa
 *   ten, kto redaguje rekrutację (`can_edit` z serwera).
 *
 * Awaria odczytu to komunikat z „Ponów”, nigdy pusta lista: pustka czyta się
 * jak „nikt niczego nie dodał”.
 */

import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Eye, FileText, Loader2, Paperclip, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  FilePreviewModal,
  formatFileSize,
  type CandidateDocument,
} from "@/components/v2/files/FilePreviewModal";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  JOB_FILES_MAX,
  JOB_FILE_ACCEPT,
  JOB_FILE_TYPES_TEXT,
  deleteJobFile,
  downloadJobFile,
  fetchJobFileBlob,
  fetchJobFiles,
  jobFilePreviewable,
  jobFileRefusal,
  jobFilesKey,
  uploadJobFile,
  type JobFileItem,
  type JobFilesOwner,
  type JobFilesResponse,
} from "@/lib/api/jobFiles";
import { apiErrorMessage } from "@/lib/api-error";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

export interface JobFilesPanelProps {
  /** Czyje pliki; `null` = formularz jeszcze nie zapisany (lista jest pusta). */
  owner: JobFilesOwner | null;
  /** Zapisuje formularz przed pierwszym uploadem i oddaje właściciela. */
  ensureOwner?: () => Promise<JobFilesOwner | null>;
  /**
   * Czy wolno dodawać i usuwać. Dla rekrutacji decyduje serwer (`can_edit`);
   * `false` tutaj wyłącza edycję niezależnie od niego (tryb tylko do odczytu).
   */
  editable?: boolean;
  /** Harness `/preview/*`: gotowe dane, zero zapytań. */
  seed?: JobFilesResponse;
  emptyText?: string;
  disabled?: boolean;
  className?: string;
}

const EMPTY_TEXT = "Nikt nie dodał jeszcze plików do tej rekrutacji.";
const NO_OWNER_TEXT = "Nie udało się zapisać formularza, więc plik nie ma dokąd trafić.";

/** Plik rekrutacji w kształcie, którego oczekuje okno podglądu. */
function asPreviewDocument(file: JobFileItem): CandidateDocument {
  return {
    id: file.id,
    filename: file.filename,
    content_type: file.content_type,
    size_bytes: file.size_bytes,
    document_kind: "other",
    is_primary: false,
    uploaded_at: file.created_at,
    external_source: null,
    created_at: file.created_at,
    uploaded_by_name: file.uploaded_by_name,
  };
}

export function JobFilesPanel({
  owner,
  ensureOwner,
  editable = true,
  seed,
  emptyText = EMPTY_TEXT,
  disabled = false,
  className,
}: JobFilesPanelProps) {
  const queryClient = useQueryClient();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [preview, setPreview] = useState<JobFileItem | null>(null);

  const query = useQuery({
    queryKey: owner ? jobFilesKey(owner) : ["job-files", "none"],
    queryFn: () => fetchJobFiles(owner as JobFilesOwner),
    enabled: owner != null && !seed,
    initialData: seed,
    staleTime: 30_000,
    retry: false,
  });
  const files = query.data?.items ?? [];
  const canEdit = editable && !disabled && (owner?.kind === "form" || owner == null
    ? true
    : query.data?.can_edit === true);
  const limit = query.data?.max_files ?? JOB_FILES_MAX;
  const full = files.length >= limit;

  const refresh = (target: JobFilesOwner) =>
    queryClient.invalidateQueries({ queryKey: jobFilesKey(target) });

  const addFiles = async (picked: File[]) => {
    if (picked.length === 0) return;
    const refused = picked.map(jobFileRefusal).filter((x): x is string => x != null);
    const accepted = picked.filter((file) => jobFileRefusal(file) == null);
    const room = Math.max(0, limit - files.length);
    const sending = accepted.slice(0, room);
    const issues = [...refused];
    if (accepted.length > sending.length)
      issues.push(`Rekrutacja może mieć najwyżej ${limit} plików — reszty nie dodano.`);
    if (sending.length === 0) {
      setProblems(issues);
      return;
    }
    setUploading(true);
    try {
      const target = owner ?? (ensureOwner ? await ensureOwner() : null);
      if (!target) {
        setProblems([...issues, NO_OWNER_TEXT]);
        return;
      }
      for (const file of sending) {
        try {
          await uploadJobFile(target, file);
        } catch (error) {
          issues.push(
            `„${file.name}”: ${apiErrorMessage(error, "nie udało się dodać pliku.")}`,
          );
        }
      }
      await refresh(target);
      setProblems(issues);
    } finally {
      setUploading(false);
    }
  };

  const remove = async (file: JobFileItem) => {
    if (!owner) return;
    const confirmed = await askConfirm({
      title: "Usunąć plik?",
      description: `„${file.filename}” zniknie z rekrutacji. Tej operacji nie da się cofnąć.`,
      confirmLabel: "Usuń plik",
      variant: "destructive",
    });
    if (!confirmed) return;
    setBusyId(file.id);
    try {
      await deleteJobFile(owner, file.id);
      setProblems([]);
      await refresh(owner);
    } catch (error) {
      setProblems([
        `„${file.filename}”: ${apiErrorMessage(error, "nie udało się usunąć pliku.")}`,
      ]);
    } finally {
      setBusyId(null);
    }
  };

  const download = async (file: JobFileItem) => {
    if (!owner) return;
    setBusyId(file.id);
    try {
      await downloadJobFile(owner, file);
    } catch {
      setProblems([`„${file.filename}”: nie udało się pobrać pliku.`]);
    } finally {
      setBusyId(null);
    }
  };

  const loading = owner != null && !seed && query.isPending;
  const failed = owner != null && query.isError;

  return (
    <div className={cn("flex flex-col gap-3", className)} data-testid="job-files-panel">
      {loading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Wczytuję pliki…
        </p>
      ) : failed ? (
        <p role="alert" className="text-sm text-destructive">
          Nie udało się wczytać plików.{" "}
          <button
            type="button"
            className="font-medium underline"
            onClick={() => void query.refetch()}
          >
            Ponów
          </button>
        </p>
      ) : files.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="job-files-empty">
          {emptyText}
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-border" aria-label="Pliki rekrutacji">
          {files.map((file) => (
            <li key={file.id} className="flex items-center gap-3 py-2">
              <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground" title={file.filename}>
                  {file.filename}
                </p>
                <p className="truncate text-xs text-muted-foreground">
                  {file.source === "request" ? (
                    <span className="mr-1.5 rounded-full bg-primary/10 px-1.5 py-0.5 font-medium text-primary">
                      Request klienta
                    </span>
                  ) : null}
                  {formatFileSize(file.size_bytes)} · dodano {formatIsoDatePl(file.created_at)}
                  {file.uploaded_by_name ? ` · ${file.uploaded_by_name}` : ""}
                </p>
              </div>
              {jobFilePreviewable(file) ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`Podgląd: ${file.filename}`}
                  title="Podgląd"
                  onClick={() => setPreview(file)}
                >
                  <Eye className="h-4 w-4" aria-hidden />
                </Button>
              ) : null}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Pobierz: ${file.filename}`}
                title="Pobierz"
                disabled={busyId === file.id}
                onClick={() => void download(file)}
              >
                <Download className="h-4 w-4" aria-hidden />
              </Button>
              {canEdit ? (
                <Button
                  type="button"
                  variant="quiet"
                  size="icon"
                  aria-label={`Usuń: ${file.filename}`}
                  title="Usuń"
                  disabled={busyId === file.id}
                  onClick={() => void remove(file)}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {canEdit && !failed ? (
        <div className="flex flex-col gap-1.5">
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={JOB_FILE_ACCEPT}
            className="sr-only"
            aria-label="Dodaj pliki do rekrutacji"
            onChange={(event) => {
              const picked = Array.from(event.target.files ?? []);
              event.target.value = "";
              void addFiles(picked);
            }}
          />
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-1.5 border-dashed"
              loading={uploading}
              disabled={uploading || full}
              title={full ? `Najwyżej ${limit} plików` : undefined}
              onClick={() => inputRef.current?.click()}
            >
              <Paperclip className="h-3.5 w-3.5" aria-hidden />
              Dodaj pliki
            </Button>
            <span className="text-xs text-muted-foreground">
              {JOB_FILE_TYPES_TEXT}, do 20 MB.
            </span>
          </div>
        </div>
      ) : null}
      {problems.length > 0 ? (
        <ul role="alert" className="flex flex-col gap-0.5 text-xs text-destructive">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}

      {owner ? (
        <FilePreviewModal
          doc={preview ? asPreviewDocument(preview) : null}
          candidateId={0}
          onClose={() => setPreview(null)}
          onDownload={(doc) => {
            const file = files.find((item) => item.id === doc.id);
            if (file) void download(file);
          }}
          loadDocumentBlob={(_candidateId, fileId, disposition) =>
            fetchJobFileBlob(owner, fileId, disposition)
          }
        />
      ) : null}
      {confirmDialog}
    </div>
  );
}

export default JobFilesPanel;
