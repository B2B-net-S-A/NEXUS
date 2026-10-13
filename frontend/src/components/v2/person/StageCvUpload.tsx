"use client";

/**
 * „Wgraj nowe CV” w rekrutacji (13.10.2026, zgłoszenie rekruterki: kafelek
 * „na wierzchu”, bez przeklikiwania do profilu).
 *
 * Jedna akcja w panelu osoby, w podglądzie po „Rozwiń” i w oknie „Dodaj
 * z CV”: plik staje się głównym CV profilu (AI odświeża profil w tle) i od
 * razu kopią CV etapu („Oryginał CV”) — `POST …/cv/original/upload` robi oba
 * zapisy w jednej transakcji. Tylko PDF, DOC i DOCX: kopia etapu bierze się
 * z głównego CV, a `get_current_cv` innych formatów nie widzi.
 */

import { useId, useRef, useState, type DragEvent, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";

import { useToast } from "@/components/Toast";
import { FileDropZone } from "@/components/ds/FileDropZone";
import { invalidateCandidateMutation } from "@/components/v2/pages/candidate-cache";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { candidateStageCvApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";

export const STAGE_CV_ACCEPT = ".pdf,.doc,.docx";
export const STAGE_CV_MAX_BYTES = 10 * 1024 * 1024;
const ALLOWED = STAGE_CV_ACCEPT.split(",");

/** Ta sama walidacja co `FileDropZone` — dla pliku upuszczonego na panel. */
export function cvFileProblem(file: File): string | null {
  const dot = file.name.lastIndexOf(".");
  const ext = dot === -1 ? "" : file.name.slice(dot).toLowerCase();
  if (!ALLOWED.includes(ext)) return `Dozwolone formaty: ${ALLOWED.join(", ")}`;
  if (file.size === 0) return "Plik jest pusty.";
  if (file.size > STAGE_CV_MAX_BYTES) return "Plik przekracza 10 MB";
  return null;
}

/**
 * „Wgraj CV” w podglądzie CV (`CandidatePreviewPane`) — tylko dla osoby, która
 * może wgrać plik do teczki kandydata i zapisuje w tej rekrutacji. Bez tego
 * obiektu podgląd niczego nie wgrywa. Typ stoi tutaj, nie przy podglądzie:
 * `PersonSidePreview` ładuje podgląd za `next/dynamic` i nie może importować
 * jego modułu nawet dla typu (`heavy-bundle-boundaries.test.ts`).
 */
export interface PreviewCvUpload {
  candidateName: string;
  jobTitle?: string;
}

export interface StageCvUpload {
  upload: (file: File) => void;
  isPending: boolean;
  /** Plik w drodze — kafelek pokazuje jego nazwę. */
  pendingFile: File | null;
  /** Chwila ostatniego udanego wgrania (ms) — linia „AI czyta nowe CV”. */
  uploadedAt: number | null;
}

export function useStageCvUpload({
  candidateId,
  stageId,
  jobId,
  onUploaded,
}: {
  candidateId: number;
  stageId: number;
  jobId: number;
  onUploaded?: () => void;
}): StageCvUpload {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [uploadedAt, setUploadedAt] = useState<number | null>(null);
  const mutation = useMutation({
    mutationFn: (file: File) => candidateStageCvApi.original.upload(stageId, file),
    onSuccess: () => {
      invalidateCandidateMutation(queryClient, candidateId, "document");
      for (const queryKey of [
        candidateQueryKeys.quickView(candidateId),
        ["cv-original", stageId],
        ["cv-qc", stageId],
        ["move-requirements"],
        ["kanban", String(jobId)],
        ["kanban", jobId],
      ]) {
        void queryClient.invalidateQueries({ queryKey });
      }
      setUploadedAt(Date.now());
      showSuccess("Nowe CV wgrane. Jest główne w profilu i w tej rekrutacji.");
      onUploaded?.();
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się wgrać CV. Spróbuj ponownie.")),
  });
  return {
    upload: (file) => mutation.mutate(file),
    isPending: mutation.isPending,
    pendingFile: mutation.isPending ? (mutation.variables ?? null) : null,
    uploadedAt,
  };
}

/** Kafelek „Wgraj nowe CV” — klik otwiera wybór pliku, plik można też upuścić. */
export function StageCvUploadTile({
  upload,
  label = "Wgraj nowe CV",
  className,
}: {
  upload: StageCvUpload;
  label?: string;
  className?: string;
}) {
  const inputId = useId();
  const [error, setError] = useState<string | null>(null);
  return (
    <FileDropZone
      inputId={inputId}
      file={upload.pendingFile}
      onPick={(file) => {
        setError(null);
        if (file) upload.upload(file);
      }}
      accept={STAGE_CV_ACCEPT}
      maxBytes={STAGE_CV_MAX_BYTES}
      label={upload.isPending ? "Wgrywanie…" : label}
      hint="Trafi na górę profilu i do tej rekrutacji"
      error={error}
      onError={setError}
      disabled={upload.isPending}
      className={className}
    />
  );
}

function isFileDrag(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}

/** Pole pliku z własną obsługą upuszczania (`ds/FileDropZone`) — plik jest dla niego. */
function inNestedDropZone(event: DragEvent): boolean {
  const target = event.target as Element | null;
  return typeof target?.closest === "function" && target.closest("[data-drag-over]") != null;
}

/**
 * Upuszczenie pliku w dowolnym miejscu obszaru (panel osoby, podgląd CV)
 * wgrywa CV — także przy zwiniętej sekcji „CV”. Nakładka reaguje wyłącznie na
 * pliki: Tablica przesuwa karty przez `@hello-pangea/dnd` (zdarzenia
 * wskaźnika, nie natywne przeciąganie), a przeciągnięty tekst czy link nie
 * ma typu „Files”.
 *
 * Dwie granice (przegląd kodu 13.10.2026):
 * - tylko zdarzenia z DOM-u tego obszaru. W Reakcie zdarzenia z portali
 *   (okna dialogowe, podgląd w lewej strefie panelu) wędrują też do przodków
 *   w drzewie komponentów — plik Championa z okna generatora albo drugi
 *   egzemplarz w podglądzie wgrałyby się jako CV;
 * - pole pliku w środku (kafelek CV, „Wgraj plik” notatki w Screeningu)
 *   dostaje plik samo: nakładka znika nad nim i nie przechwytuje upuszczenia.
 *   Tak samo wewnętrzny obszar (podgląd CV w panelu poniżej 1024 px) —
 *   zewnętrzny nie wgrywa upuszczenia, które tamten już obsłużył.
 */
export function CvFileDropTarget({
  enabled,
  upload,
  title,
  className,
  children,
}: {
  enabled: boolean;
  upload: StageCvUpload;
  /** Kogo dotyczy wgranie — „Anna Nowak · Senior Java Developer”. */
  title: string;
  className?: string;
  children: ReactNode;
}) {
  const { showError } = useToast();
  const [active, setActive] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  // dragenter/dragleave przychodzą też z dzieci — licznik, nie flaga.
  const depth = useRef(0);
  if (!enabled) return <div className={className}>{children}</div>;

  const ours = (event: DragEvent): boolean => {
    if (!isFileDrag(event)) return false;
    const target = event.target as Node | null;
    return target != null && root.current != null && root.current.contains(target);
  };
  const reset = () => {
    depth.current = 0;
    setActive(false);
  };
  return (
    <div
      ref={root}
      className={cn("relative", className)}
      onDragEnter={(event) => {
        if (!ours(event)) return;
        event.preventDefault();
        depth.current += 1;
        setActive(!inNestedDropZone(event));
      }}
      onDragOver={(event) => {
        if (!ours(event)) return;
        event.preventDefault();
        setActive(!inNestedDropZone(event));
      }}
      onDragLeave={(event) => {
        if (!ours(event)) return;
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setActive(false);
      }}
      onDrop={(event) => {
        if (!ours(event)) return;
        reset();
        // Pole pliku w środku obsłużyło upuszczenie samo. `defaultPrevented`:
        // obsłużył je wewnętrzny obszar — poniżej 1024 px podgląd CV z własnym
        // `CvFileDropTarget` stoi w DOM-ie panelu osoby i to samo upuszczenie
        // wgrywało CV dwa razy (audyt 13.10.2026).
        if (event.defaultPrevented || inNestedDropZone(event)) return;
        event.preventDefault();
        const file = event.dataTransfer.files?.[0];
        if (!file || upload.isPending) return;
        const problem = cvFileProblem(file);
        if (problem) {
          showError(problem);
          return;
        }
        upload.upload(file);
      }}
    >
      {children}
      {active ? (
        // Sama grafika (`pointer-events-none`): zdarzenia trafiają w elementy
        // pod spodem, więc nad polem pliku nakładka znika, a nie zabiera mu pliku.
        <div data-testid="cv-drop-overlay" className="pointer-events-none absolute inset-0 z-30 p-2">
          <div className="grid h-full place-content-center gap-1.5 rounded-xl border-2 border-dashed border-primary bg-background/95 p-4 text-center shadow-sm">
            <Upload className="mx-auto h-8 w-8 text-primary" aria-hidden />
            <p className="text-sm font-semibold text-foreground">Upuść, aby wgrać nowe CV</p>
            <p className="text-xs text-foreground">{title}</p>
            <p className="text-xs text-muted-foreground">Trafi na górę profilu i do tej rekrutacji</p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
