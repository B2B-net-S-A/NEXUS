"use client";

/**
 * „CV do klienta” — karta CV jednej osoby w jednej rekrutacji (generator CV v3).
 *
 * Zastępuje osadzony w panelu osoby cały generator, wybór wersji „Zastąp szkic
 * i otwórz edytor” i stary szablon „CV firmowe”. Stany (makieta
 * „Rekrutacja → panel osoby → CV do klienta”):
 *  - gotowe — szkic albo zatwierdzona wersja etapu: Podgląd · Edytuj ·
 *    Pobierz DOCX, uwagi kontroli AI, zgoda RODO, „Wygeneruj ponownie”
 *    i „Użyj nowej wersji”, gdy obok leży nowsza, niepodpięta generacja;
 *  - generuje się — ręczna generacja z tej karty albo auto-CV po weryfikacji;
 *  - brak — „Generuj CV” otwiera to samo okno co na profilu, z osobą
 *    i rekrutacją już ustawionymi; serwer sam podpina gotowe CV do etapu;
 *  - stary szablon — szkic HTML sprzed generatora: tylko podgląd.
 *
 * Karta NICZEGO nie blokuje („Kanban bez bramek”): ruch na „CV wysłane”
 * i stawka do klienta żyją obok, w warsztacie wysyłki. Brak zgody RODO
 * wyłącza wyłącznie pobranie pliku — serwer i tak odpowiada wtedy 409.
 */

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Download,
  Eye,
  FileText,
  Info,
  Loader2,
  Pencil,
  RefreshCcw,
  Sparkles,
} from "lucide-react";

import api, {
  candidateStageCvApi,
  type CVBrandedState,
  type CVOriginalSnapshot,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadAuthenticatedFile,
  downloadBlob,
  postAuthenticatedDownload,
} from "@/lib/authenticated-files";
import { CV_CONTENT_MODES } from "@/lib/cv-generator";
import {
  cvToClientRowsQueryKey,
  cvToClientShouldPoll,
  resolveCvToClient,
  stageBrandedQueryKey,
  type StageGeneratedCvRow,
} from "@/lib/cv-to-client";
import {
  BACKGROUND_EVENTS_STEP,
  autoCvSkipReason,
  jobBackgroundEventsApi,
  jobBackgroundEventsQueryKey,
  latestAutoCvSkip,
} from "@/lib/job-background-events";
import { formatDate } from "@/lib/utils";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CvGeneratorDialog } from "@/components/v2/cv-generator/CvGeneratorDialog";
import { ConsentAttachButton } from "@/components/v2/cv-generator/ConsentAttachButton";
import { CVOriginalPreviewModal } from "@/components/v2/modals/CVOriginalPreviewModal";

// Edytor CV to TipTap — za granicą `dynamic()`, jak w doku kanbana.
const CVBrandedEditModal = dynamic(
  () =>
    import("@/components/v2/modals/CVBrandedEditModal").then(
      (m) => m.CVBrandedEditModal,
    ),
  { ssr: false },
);

const POLL_MS = 4000;
/** Po tylu minutach przestajemy czekać na podpięcie — dalej decyduje człowiek. */
const PENDING_TIMEOUT_MS = 5 * 60_000;

/**
 * Dlaczego automat NIE przygotował CV tej osoby (np. reguła klienta wymaga
 * zrzutu zgody RODO). Źródłem jest „Praca w tle” rekrutacji — ten sam klucz
 * zapytania co okno „Historia i czat”, bez osobnego endpointu. Informacja, nie
 * bramka: ładowanie, błąd i brak zdarzenia nie rysują nic.
 */
export function AutoCvSkipNotice({ jobId, candidateId }: { jobId: number; candidateId: number }) {
  const query = useQuery({
    queryKey: jobBackgroundEventsQueryKey(jobId, BACKGROUND_EVENTS_STEP),
    queryFn: () => jobBackgroundEventsApi.list(jobId, BACKGROUND_EVENTS_STEP),
    retry: false,
    staleTime: 30_000,
  });
  const skipped = latestAutoCvSkip(query.data?.items ?? [], candidateId);
  if (!skipped) return null;
  return (
    <p
      role="note"
      data-testid="auto-cv-skip-notice"
      className="flex items-start gap-2 rounded-lg border border-info/25 bg-info-muted px-3 py-2 text-xs text-info-muted-foreground"
    >
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>
        CV nie zostało wygenerowane automatycznie: {autoCvSkipReason(skipped)}. Możesz je
        wygenerować ręcznie.
      </span>
    </p>
  );
}

/**
 * Podgląd treści CV etapu. Treść pochodzi z edytora (HTML), więc przed
 * wstawieniem przechodzi przez DOMPurify — ładowany dopiero przy otwarciu.
 * Działa także bez zgody RODO: blokada dotyczy pobrania pliku, nie czytania.
 */
function CvHtmlPreviewDialog({
  open,
  onOpenChange,
  html,
  title,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  html: string | null;
  title: string;
}) {
  const [safe, setSafe] = useState<string | null>(null);
  useEffect(() => {
    if (!open || !html) return;
    let cancelled = false;
    void import("dompurify").then(({ default: DOMPurify }) => {
      if (cancelled) return;
      setSafe(DOMPurify.sanitize(html, { FORBID_TAGS: ["style", "script"] }));
    });
    return () => {
      cancelled = true;
    };
  }, [open, html]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="2xl" className="flex max-h-[92vh] flex-col p-0">
        <DialogHeader className="border-b border-border px-5 py-3">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>Podgląd treści CV do klienta.</DialogDescription>
        </DialogHeader>
        <div className="flex-1 overflow-auto bg-background p-5">
          {!html ? (
            <p className="text-sm text-muted-foreground">To CV nie ma jeszcze treści.</p>
          ) : safe == null ? (
            <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" aria-hidden /> Wczytywanie podglądu…
            </p>
          ) : (
            <div
              data-testid="cv-to-client-preview"
              className="prose prose-sm max-w-none rounded-lg border border-border bg-card p-4"
              // Treść po DOMPurify (bez skryptów i stylów).
              dangerouslySetInnerHTML={{ __html: safe }}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export interface CvToClientCardProps {
  /** Etap osoby w tej rekrutacji — na nim leży CV do klienta. */
  stageId: number;
  candidateId: number;
  candidateName: string;
  jobId: number;
  jobTitle?: string;
  readOnly: boolean;
}

export function CvToClientCard({
  stageId,
  candidateId,
  candidateName,
  jobId,
  jobTitle,
  readOnly,
}: CvToClientCardProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const jobLabel = jobTitle?.trim() || `Rekrutacja #${jobId}`;

  const [generatorOpen, setGeneratorOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [originalOpen, setOriginalOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);
  // Generacja zlecona z TEJ karty — czekamy, aż serwer ją podepnie do etapu.
  const [pending, setPending] = useState<{ id: number; expired: boolean } | null>(null);
  const pendingId = pending?.id ?? null;
  useEffect(() => {
    if (pendingId == null) return;
    const timer = setTimeout(
      () => setPending((current) => (current?.id === pendingId ? { ...current, expired: true } : current)),
      PENDING_TIMEOUT_MS,
    );
    return () => clearTimeout(timer);
  }, [pendingId]);

  const brandedQuery = useQuery<CVBrandedState>({
    queryKey: stageBrandedQueryKey(stageId),
    queryFn: () => candidateStageCvApi.branded.get(stageId).then((r) => r.data),
  });
  const rowsQuery = useQuery<StageGeneratedCvRow[]>({
    queryKey: cvToClientRowsQueryKey(candidateId, jobId),
    queryFn: () =>
      api
        .get<StageGeneratedCvRow[]>("/api/cv-generator/generated", {
          params: { candidate_id: candidateId, job_id: jobId, limit: 20 },
        })
        .then((r) => r.data),
  });
  const originalQuery = useQuery<CVOriginalSnapshot>({
    queryKey: ["cv-original", stageId],
    queryFn: () => candidateStageCvApi.original.get(stageId).then((r) => r.data),
  });

  const branded = brandedQuery.data;
  const state = resolveCvToClient({
    branded,
    rows: rowsQuery.data,
    pendingGeneratedId: pendingId,
  });

  // Odpytywanie: generacja w toku albo czekamy na podpięcie zleconej z karty.
  // Sufit czasu — etap ze starym szkicem nie dostanie podpięcia nigdy, a karta
  // i tak pokazuje wtedy „Użyj tej wersji”.
  const polling = cvToClientShouldPoll(state, pendingId) && pending?.expired !== true;
  useEffect(() => {
    if (!polling) return;
    const id = setInterval(() => {
      // Serwer podpina gotowe CV do etapu sam — CV etapu odświeżamy razem
      // z listą, inaczej karta pokazałaby „Użyj tej wersji” zamiast gotowego CV.
      void queryClient.invalidateQueries({ queryKey: cvToClientRowsQueryKey(candidateId, jobId) });
      void queryClient.invalidateQueries({ queryKey: stageBrandedQueryKey(stageId) });
    }, POLL_MS);
    return () => clearInterval(id);
  }, [polling, queryClient, candidateId, jobId, stageId]);

  // Koniec czekania: serwer podpiął CV (etap ma treść) albo generacja padła.
  useEffect(() => {
    if (!pending) return;
    if (state.kind === "ready" || state.kind === "failed") setPending(null);
  }, [pending, state.kind]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: cvToClientRowsQueryKey(candidateId, jobId) });
    void queryClient.invalidateQueries({ queryKey: stageBrandedQueryKey(stageId) });
  };

  const attachVersionMut = useMutation({
    mutationFn: (generatedId: number) =>
      candidateStageCvApi.branded.selectGenerated(
        stageId,
        generatedId,
        branded?.edit_revision ?? 0,
      ),
    onSuccess: (response) => {
      queryClient.setQueryData(stageBrandedQueryKey(stageId), response.data);
      void queryClient.invalidateQueries({ queryKey: cvToClientRowsQueryKey(candidateId, jobId) });
      showSuccess("CV podpięte do tej rekrutacji.");
    },
    onError: (error) =>
      showError(
        apiErrorMessage(
          error,
          "Nie udało się podpiąć CV — szkic mógł zmienić się w innym oknie. Odśwież i spróbuj ponownie.",
        ),
      ),
  });

  const download = async () => {
    if (!branded) return;
    setDownloading(true);
    try {
      if (branded.status === "finalized") {
        await downloadAuthenticatedFile(
          `/api/candidates/stages/${stageId}/cv/branded/versions/${branded.version}/docx`,
          branded.docx_filename || "CV.docx",
        );
      } else {
        const result = await postAuthenticatedDownload(
          `/api/candidates/stages/${stageId}/cv/branded/preview-docx`,
          { content_html: branded.content_html ?? "", expected_revision: branded.edit_revision },
        );
        downloadBlob(result.blob, result.filename || "SZKIC_CV.docx");
      }
    } catch (error) {
      // 409 `consent_required` niesie polski komunikat serwera.
      showError(apiErrorMessage(error, "Nie udało się pobrać CV."));
    } finally {
      setDownloading(false);
    }
  };

  const openGenerator = () => setGeneratorOpen(true);
  const onEnqueued = (generatedId: number) => {
    setPending({ id: generatedId, expired: false });
    setGeneratorOpen(false);
    void queryClient.invalidateQueries({ queryKey: cvToClientRowsQueryKey(candidateId, jobId) });
  };

  const loading = brandedQuery.isLoading || rowsQuery.isLoading;
  const loadFailed = brandedQuery.isError || rowsQuery.isError;
  const attached = state.attached ?? state.candidate;
  const modeLabel =
    CV_CONTENT_MODES.find((mode) => mode.value === attached?.content_mode)?.label ?? null;
  const languageLabel = attached?.language ? attached.language.toUpperCase() : null;

  let body: React.ReactNode;
  if (loading) {
    body = (
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="size-3 animate-spin" aria-hidden /> Wczytywanie CV…
      </p>
    );
  } else if (loadFailed && !branded) {
    // Awaria NIE może wyglądać jak „brak CV”.
    body = (
      <p role="alert" className="text-xs text-destructive-muted-foreground">
        Nie udało się wczytać CV do klienta.{" "}
        <button
          type="button"
          className="font-medium underline underline-offset-2"
          onClick={() => {
            void brandedQuery.refetch();
            void rowsQuery.refetch();
          }}
        >
          Ponów
        </button>
      </p>
    );
  } else if (state.kind === "ready" && branded) {
    const finalized = branded.status === "finalized";
    body = (
      <div className="space-y-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge size="sm" variant={finalized ? "success" : "info"}>
            {finalized ? `CV gotowe · wersja ${branded.version}` : "CV gotowe · szkic"}
          </Badge>
          {modeLabel ? <Badge size="sm" variant="neutral">{modeLabel}</Badge> : null}
          {languageLabel ? <Badge size="sm" variant="neutral">{languageLabel}</Badge> : null}
          {state.needsReview ? (
            <Badge size="sm" variant="warning" className="h-auto whitespace-normal py-0.5 text-left">
              wygenerowane automatycznie — sprawdź przed wysyłką
            </Badge>
          ) : null}
        </div>
        {state.attached?.origin === "auto" && state.attached.created_at ? (
          <p className="text-[11px] text-muted-foreground">
            Wygenerowane automatycznie {formatDate(state.attached.created_at)}, po ruchu na
            „Zweryfikowany”.
          </p>
        ) : null}
        {state.findings > 0 ? (
          <p
            role="note"
            className="flex items-start gap-1.5 rounded-md border border-warning/30 bg-warning-muted px-2.5 py-1.5 text-xs text-warning-muted-foreground"
          >
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            {state.findings === 1
              ? "1 rzecz do sprawdzenia"
              : `${state.findings} rzeczy do sprawdzenia`}{" "}
            — kontrola AI nie znalazła pokrycia w źródłach. Porównaj z oryginałem w edytorze.
          </p>
        ) : null}
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setPreviewOpen(true)}>
            <Eye className="h-3.5 w-3.5" aria-hidden /> Podgląd
          </Button>
          {!readOnly ? (
            <Button size="sm" variant="outline" onClick={() => setEditorOpen(true)}>
              <Pencil className="h-3.5 w-3.5" aria-hidden /> Edytuj
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="outline"
            onClick={() => void download()}
            disabled={downloading || state.consentMissing}
            loading={downloading}
            title={
              state.consentMissing
                ? "Najpierw dołącz zrzut zgody RODO — bez niego nie pobierzesz CV."
                : undefined
            }
          >
            <Download className="h-3.5 w-3.5" aria-hidden /> Pobierz DOCX
          </Button>
        </div>
        {state.consentMissing && state.attached ? (
          <div
            role="note"
            className="flex flex-col items-start gap-2 rounded-md border border-destructive/25 bg-destructive-muted px-2.5 py-2 text-xs text-destructive-muted-foreground"
          >
            <span>
              Zgoda RODO: brak zrzutu. Bez niego nie pobierzesz CV.
            </span>
            {!readOnly ? (
              <ConsentAttachButton
                compact
                generatedId={state.attached.id}
                hasConsent={false}
                onAttached={refresh}
              />
            ) : null}
          </div>
        ) : null}
        {state.generating ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" aria-hidden /> Generuje się nowa wersja…
          </p>
        ) : null}
        {state.candidate && !readOnly ? (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-info/25 bg-info-muted px-2.5 py-1.5 text-xs text-info-muted-foreground">
            <span className="min-w-0 flex-1">
              Jest nowsza wersja z generatora
              {state.candidate.created_at ? ` (${formatDate(state.candidate.created_at)})` : ""}.
              Zastąpi bieżący szkic; zatwierdzone wersje zostają.
            </span>
            <Button
              size="sm"
              variant="outline"
              loading={attachVersionMut.isPending}
              disabled={attachVersionMut.isPending}
              onClick={() => attachVersionMut.mutate(state.candidate!.id)}
            >
              Użyj nowej wersji
            </Button>
          </div>
        ) : null}
        {!readOnly ? (
          <Button size="sm" variant="ghost" onClick={openGenerator}>
            <RefreshCcw className="h-3.5 w-3.5" aria-hidden /> Wygeneruj ponownie
          </Button>
        ) : null}
      </div>
    );
  } else if (state.kind === "generating") {
    const auto = state.generating?.origin === "auto";
    body = (
      <div className="space-y-1.5">
        <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
          {auto ? "Automat generuje CV…" : "Generuje się…"}
        </p>
        <p className="text-xs text-muted-foreground">
          Możesz zamknąć panel. CV pojawi się tutaj i w „Moich CV”.
        </p>
      </div>
    );
  } else if (state.kind === "unattached" && state.candidate) {
    const waiting = pending != null && !pending.expired;
    body = (
      <div className="space-y-2">
        {waiting ? (
          <p className="flex items-center gap-1.5 text-sm text-foreground">
            <Loader2 className="size-3.5 animate-spin" aria-hidden /> CV gotowe — podpinam do
            tej rekrutacji…
          </p>
        ) : (
          <p className="text-sm text-foreground">
            Jest gotowe CV z generatora, ale ta rekrutacja jeszcze go nie używa.
          </p>
        )}
        {!readOnly ? (
          <div className="flex flex-wrap gap-1.5">
            <Button
              size="sm"
              loading={attachVersionMut.isPending}
              disabled={attachVersionMut.isPending}
              onClick={() => attachVersionMut.mutate(state.candidate!.id)}
            >
              Użyj tej wersji
            </Button>
            <Button size="sm" variant="ghost" onClick={openGenerator}>
              <RefreshCcw className="h-3.5 w-3.5" aria-hidden /> Wygeneruj ponownie
            </Button>
          </div>
        ) : null}
      </div>
    );
  } else if (state.kind === "failed") {
    body = (
      <div className="space-y-2">
        <p role="alert" className="text-xs text-destructive-muted-foreground">
          Generowanie CV nie powiodło się
          {state.failed?.error_message ? `: ${state.failed.error_message}` : "."}
        </p>
        {!readOnly ? (
          <Button size="sm" onClick={openGenerator}>
            <Sparkles className="h-3.5 w-3.5" aria-hidden /> Spróbuj ponownie
          </Button>
        ) : null}
      </div>
    );
  } else if (state.kind === "legacy") {
    body = (
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge size="sm" variant="neutral">Stary szablon · tylko odczyt</Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          To CV powstało ze starego szablonu „CV firmowe” (bez obróbki treści). Można je
          obejrzeć; do klienta wygeneruj nowe CV.
        </p>
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setPreviewOpen(true)}>
            <Eye className="h-3.5 w-3.5" aria-hidden /> Podgląd
          </Button>
          {!readOnly && state.candidate ? (
            <Button
              size="sm"
              variant="outline"
              loading={attachVersionMut.isPending}
              disabled={attachVersionMut.isPending}
              onClick={() => attachVersionMut.mutate(state.candidate!.id)}
            >
              Użyj wygenerowanego CV
            </Button>
          ) : null}
          {!readOnly ? (
            <Button size="sm" onClick={openGenerator}>
              <Sparkles className="h-3.5 w-3.5" aria-hidden /> Wygeneruj CV
            </Button>
          ) : null}
        </div>
      </div>
    );
  } else {
    body = (
      <div className="space-y-2">
        <AutoCvSkipNotice jobId={jobId} candidateId={candidateId} />
        <p className="text-sm text-foreground">Jeszcze nie ma CV do klienta dla tej rekrutacji.</p>
        {!readOnly ? (
          <div className="space-y-1">
            <Button size="sm" onClick={openGenerator}>
              <Sparkles className="h-3.5 w-3.5" aria-hidden /> Generuj CV
            </Button>
            <p className="text-[11px] text-muted-foreground">
              Otworzy okno generatora z tą osobą i tą rekrutacją.
            </p>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            CV wygeneruje osoba z prawem zapisu w tej rekrutacji.
          </p>
        )}
      </div>
    );
  }

  const original = originalQuery.data;
  return (
    <section
      aria-label="CV do klienta"
      data-testid="cv-to-client-card"
      className="space-y-3 rounded-xl border border-border bg-card p-3"
    >
      <h3 className="text-sm font-semibold text-foreground">CV do klienta</h3>
      {body}
      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-2 text-[11px] text-muted-foreground">
        <FileText className="h-3 w-3 shrink-0" aria-hidden />
        {originalQuery.isLoading ? (
          <span>Plik CV kandydata…</span>
        ) : original?.has_snapshot ? (
          <>
            <span className="min-w-0 truncate">
              Plik CV: {original.original_cv_filename ?? "oryginał"}
              {original.original_snapshot_at
                ? ` · z ${formatDate(original.original_snapshot_at)}`
                : ""}
            </span>
            <button
              type="button"
              className="font-medium text-primary hover:underline"
              onClick={() => setOriginalOpen(true)}
            >
              Pokaż oryginał
            </button>
          </>
        ) : (
          <span>Brak pliku CV w momencie zgłoszenia.</span>
        )}
      </div>

      {generatorOpen ? (
        <CvGeneratorDialog
          open
          onOpenChange={setGeneratorOpen}
          candidateId={candidateId}
          candidateName={candidateName}
          jobId={jobId}
          onEnqueued={onEnqueued}
        />
      ) : null}
      {editorOpen && !readOnly ? (
        <CVBrandedEditModal
          open
          onOpenChange={(open) => {
            setEditorOpen(open);
            if (!open) refresh();
          }}
          onRegenerate={openGenerator}
          stageId={stageId}
          jobTitle={jobLabel}
          candidateName={candidateName}
        />
      ) : null}
      {previewOpen ? (
        <CvHtmlPreviewDialog
          open
          onOpenChange={setPreviewOpen}
          html={branded?.content_html ?? null}
          title={`CV do klienta — ${candidateName}`}
        />
      ) : null}
      {originalOpen ? (
        <CVOriginalPreviewModal
          open
          onOpenChange={setOriginalOpen}
          stageId={stageId}
          jobTitle={jobLabel}
          candidateName={candidateName}
        />
      ) : null}
    </section>
  );
}
