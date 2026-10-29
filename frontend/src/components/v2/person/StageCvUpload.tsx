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
 *
 * 15.10.2026: gotowe CV do klienta z kafelka. Plik Word nazwany jak CV do
 * klienta („B2B_…”, wzór nazwy klienta) serwer zapisuje od razu jako CV do
 * klienta pary — bez głównego CV profilu, oryginału i odczytu AI. CV, które
 * ktoś poprawiał albo zatwierdził, podmienia dopiero po pytaniu (409
 * `client_cv_replace_confirm`), a nieprzejrzane wgranie da się cofnąć —
 * „Cofnij” wysyła ten sam plik jako CV kandydata (`mode: "original"`).
 */

import { useId, useRef, useState, type DragEvent, type ReactNode } from "react";
import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";
import type { AxiosResponse } from "axios";
import { Upload } from "lucide-react";

import { useToast } from "@/components/Toast";
import { FileDropZone } from "@/components/ds/FileDropZone";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { invalidateCandidateMutation } from "@/components/v2/pages/candidate-cache";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { candidateStageCvApi, type StageCvUploadResult } from "@/lib/api";
import { MOVE_REQUIREMENTS_PREFIX } from "@/lib/api/moveRequirements";
import { apiErrorMessage } from "@/lib/api-error";
import { cvAiSourcesQueryKey } from "@/lib/cv-ai-sources";
import { apiErrorCode } from "@/lib/cv-qc";
import {
  cvToClientIssuesQueryKey,
  cvToClientQcQueryKey,
  cvToClientRowsQueryKey,
  stageBrandedQueryKey,
} from "@/lib/cv-to-client";
import { newCvUploadFrom, newCvUploadKey } from "@/lib/new-cv-upload";
import { cn } from "@/lib/utils";

export const STAGE_CV_ACCEPT = ".pdf,.doc,.docx";
export const STAGE_CV_MAX_BYTES = 10 * 1024 * 1024;
const ALLOWED = STAGE_CV_ACCEPT.split(",");
/** Nakładka: dokąd trafi plik (15.10.2026 — CV do klienta po nazwie pliku). */
const STAGE_CV_HINT = "CV kandydata → oryginał · plik „B2B_…” → CV do klienta";
/**
 * Kafelek ma podpis w jednej linii (`FileDropZone` go ucina): w doku na
 * laptopie 1280 px mieści się ok. 35 znaków, a dłuższe zdanie gubiło „CV do
 * klienta” — jedyną nową informację.
 */
const STAGE_CV_TILE_HINT = "Plik „B2B_…” = od razu CV do klienta";

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
  /** Wgrywanie albo otwarte pytanie „Zastąpić CV do klienta?” — drugi plik czeka. */
  isPending: boolean;
  /** Plik w drodze — kafelek pokazuje jego nazwę. */
  pendingFile: File | null;
  /** Chwila ostatniego udanego wgrania (ms) — linia „AI czyta nowe CV”. */
  uploadedAt: number | null;
  /** Pytanie „Zastąpić CV do klienta?” — wyrenderuj raz obok kafelka. */
  confirmDialog: ReactNode;
}

/** Czym stał się wgrany plik: CV kandydata albo CV do klienta tej rekrutacji. */
export type StageCvUploadKind = "original" | "client_cv";

interface UploadVariables {
  file: File;
  mode?: "original";
  replaceClientCv?: boolean;
  /**
   * „Cofnij” po CV do klienta: serwer dostaje tylko `mode: "original"` i sam
   * przywraca poprzednie CV do klienta — tu komunikat i wiersz do odświeżenia.
   */
  undo?: { clientCvStageId: number };
}

const REPLACE_CONFIRM_CODE = "client_cv_replace_confirm";
const UPLOAD_FAILED = "Nie udało się wgrać CV. Spróbuj ponownie.";

export function useStageCvUpload({
  candidateId,
  stageId,
  jobId,
  onUploaded,
}: {
  candidateId: number;
  stageId: number;
  jobId: number;
  onUploaded?: (kind: StageCvUploadKind) => void;
}): StageCvUpload {
  const queryClient = useQueryClient();
  const { showSuccess, showError, showInfo, showActionToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [uploadedAt, setUploadedAt] = useState<number | null>(null);
  // Plik czekający na odpowiedź „Zastąpić CV do klienta?”.
  const [confirming, setConfirming] = useState<File | null>(null);

  const invalidate = (keys: readonly QueryKey[]) => {
    for (const queryKey of keys) void queryClient.invalidateQueries({ queryKey });
  };

  // CV do klienta pary na wierszu `targetId` (po ruchu karty bywa wcześniejszy):
  // karta „CV do klienta”, przegląd DL, okno QC i edytor liczą od nowa.
  const clientCvKeys = (targetId: number): QueryKey[] => [
    ...(targetId !== stageId ? [stageBrandedQueryKey(stageId)] : []),
    cvToClientRowsQueryKey(candidateId, jobId),
    ["cv-generated", "dl-review", candidateId, jobId],
    cvToClientQcQueryKey(targetId).slice(0, 2),
    cvToClientIssuesQueryKey(targetId).slice(0, 2),
    cvAiSourcesQueryKey(targetId),
  ];

  // Plik stał się CV do klienta pary: oryginał i profil bez zmian, bez odczytu AI.
  const clientCvUploaded = (data: StageCvUploadResult, variables: UploadVariables) => {
    const targetId = data.client_cv_stage_id ?? stageId;
    if (data.client_cv) queryClient.setQueryData(stageBrandedQueryKey(targetId), data.client_cv);
    invalidateCandidateMutation(queryClient, candidateId, "document");
    invalidate([
      ...clientCvKeys(targetId),
      MOVE_REQUIREMENTS_PREFIX,
      ["kanban", String(jobId)],
      ["kanban", jobId],
    ]);
    const name = data.uploaded_filename ?? variables.file.name;
    const message =
      `CV do klienta z pliku ${name}.` +
      (data.replaced === "auto_cv" ? " Zastąpiło CV od automatu." : "") +
      (data.replaced === "confirmed" ? " Poprzednia wersja jest w historii." : "");
    if (data.undo_available) {
      showActionToast(message, {
        actionLabel: "Cofnij",
        // Błąd pokazuje `onError`; toast tylko czeka na koniec.
        onAction: () =>
          mutation.mutateAsync({ file: variables.file, mode: "original", undo: { clientCvStageId: targetId } }).then(
            () => undefined,
            () => undefined,
          ),
      });
    } else {
      showSuccess(message);
    }
    onUploaded?.("client_cv");
  };

  const mutation = useMutation<AxiosResponse<StageCvUploadResult> | undefined, unknown, UploadVariables>({
    mutationFn: ({ file, mode, replaceClientCv }) =>
      mode || replaceClientCv
        ? candidateStageCvApi.original.upload(stageId, file, {
            ...(mode ? { mode } : {}),
            ...(replaceClientCv ? { replaceClientCv: true } : {}),
          })
        : candidateStageCvApi.original.upload(stageId, file),
    onSuccess: (response, variables) => {
      const data = response?.data;
      // Starsze odpowiedzi nie mają `outcome` — to zawsze CV kandydata.
      const outcome = data?.outcome ?? "original";
      if (outcome === "client_cv" && data) {
        clientCvUploaded(data, variables);
        return;
      }
      if (outcome === "client_cv_kept") {
        invalidateCandidateMutation(queryClient, candidateId, "document");
        showInfo("Klient ma już CV tej osoby, więc go nie podmieniam. Plik zapisany w profilu w „CV dla klientów”.");
        return;
      }
      invalidateCandidateMutation(queryClient, candidateId, "document");
      invalidate([
        candidateQueryKeys.quickView(candidateId),
        ["cv-original", stageId],
        ["cv-qc", stageId],
        // Otwarty panel „Z czego zrobić CV?”: nowy plik to Oryginał CV
        // rekrutacji i musi być na liście generatora (audyt 22.10).
        cvAiSourcesQueryKey(stageId).slice(0, 1),
        ["cv-gen-sources", candidateId],
        MOVE_REQUIREMENTS_PREFIX,
        ["kanban", String(jobId)],
        ["kanban", jobId],
      ]);
      // Cofnięcie przywróciło poprzednie CV do klienta — karta i dok pokazują je od nowa.
      if (variables.undo) {
        const targetId = variables.undo.clientCvStageId;
        invalidate([stageBrandedQueryKey(targetId), ...clientCvKeys(targetId)]);
      }
      const at = Date.now();
      setUploadedAt(at);
      // Blok „Nowe CV” w karcie i panelu (29.10.2026): co z CV do klienta.
      const entry = variables.undo ? null : newCvUploadFrom(data, variables.file.name, at);
      queryClient.setQueryData(newCvUploadKey(candidateId, jobId), entry);
      if (entry?.companyStageId != null && entry.companyStageId !== stageId) {
        invalidate([stageBrandedQueryKey(entry.companyStageId)]);
      }
      if (entry?.plan === "regenerating") {
        invalidate([stageBrandedQueryKey(stageId), cvToClientRowsQueryKey(candidateId, jobId)]);
      }
      showSuccess(
        variables.undo
          ? "Cofnięte. Plik jest CV kandydata: główne w profilu i oryginał w tej rekrutacji."
          : "Nowe CV kandydata wgrane. Jest główne w profilu i oryginałem w tej rekrutacji.",
      );
      onUploaded?.("original");
    },
    onError: (error, variables) => {
      // CV do klienta, które ktoś poprawiał, wybrał albo zatwierdził (D2):
      // pytamy i wysyłamy ten sam plik jeszcze raz. „Nie podmieniaj” = nic.
      if (apiErrorCode(error) === REPLACE_CONFIRM_CODE && !variables.replaceClientCv) {
        setConfirming(variables.file);
        void askConfirm({
          title: "Zastąpić CV do klienta?",
          description: apiErrorMessage(error, "Ta osoba ma już CV do klienta w tej rekrutacji."),
          confirmLabel: "Zastąp",
          cancelLabel: "Nie podmieniaj",
        }).then((yes) => {
          setConfirming(null);
          if (yes) mutation.mutate({ file: variables.file, replaceClientCv: true });
        });
        return;
      }
      showError(apiErrorMessage(error, UPLOAD_FAILED));
    },
  });

  const isPending = mutation.isPending || confirming != null;
  return {
    upload: (file) => {
      if (isPending) return;
      mutation.mutate({ file });
    },
    isPending,
    pendingFile: mutation.isPending ? (mutation.variables?.file ?? null) : confirming,
    uploadedAt,
    confirmDialog,
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
      hint={STAGE_CV_TILE_HINT}
      error={error}
      onError={setError}
      disabled={upload.isPending}
      className={className}
    />
  );
}

/**
 * „Wgraj nowe CV” w nagłówku zwiniętej sekcji „CV” panelu osoby (29.10.2026,
 * D2): kafelek stoi na dole rozwiniętej sekcji, poniżej ekranu 1280 × 720.
 */
export function StageCvUploadButton({ upload, label = "Wgraj nowe CV" }: { upload: StageCvUpload; label?: string }) {
  const input = useRef<HTMLInputElement>(null);
  const { showError } = useToast();
  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-7 shrink-0 px-2 text-xs"
        loading={upload.isPending}
        disabled={upload.isPending}
        onClick={() => input.current?.click()}
      >
        <Upload className="h-3.5 w-3.5" aria-hidden /> {upload.isPending ? "Wgrywanie…" : label}
      </Button>
      <input
        ref={input}
        type="file"
        accept={STAGE_CV_ACCEPT}
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          const problem = cvFileProblem(file);
          if (problem) {
            showError(problem);
            return;
          }
          upload.upload(file);
        }}
      />
    </>
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
            <p className="text-xs text-muted-foreground">{STAGE_CV_HINT}</p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
