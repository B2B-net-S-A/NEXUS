"use client";

/**
 * „CV do klienta” — karta CV jednej osoby w jednej rekrutacji (generator CV v3).
 *
 * Zastępuje osadzony w panelu osoby cały generator, wybór wersji „Zastąp szkic
 * i otwórz edytor” i stary szablon „CV firmowe”. Stany (makieta
 * „Rekrutacja → panel osoby → CV do klienta”):
 *  - gotowe — szkic albo zatwierdzona wersja etapu: miniatura pierwszej
 *    strony (klik = wszystkie strony), „Otwórz i popraw” · „Pobierz Word” ·
 *    „⋯”, liczba rzeczy do sprawdzenia, zgoda RODO i „Użyj nowej wersji”,
 *    gdy obok leży nowsza, niepodpięta generacja;
 *  - generuje się — ręczna generacja z tej karty albo auto-CV po weryfikacji;
 *  - brak — „Generuj CV” rozwija w karcie panel „Z czego powstało”
 *    (`CvGeneratePanel`); serwer sam podpina gotowe CV do etapu;
 *  - stary szablon — szkic HTML sprzed generatora: tylko podgląd.
 *
 * 13.10.2026 (PR 4 „CV w procesie”, decyzja D4): CV powstaje w procesie, więc
 * karta nie otwiera już okna generatora. „Generuj CV”, „Wygeneruj ponownie”
 * i „Spróbuj ponownie” rozwijają panel ze źródłami dla AI, obróbką i językiem.
 * Ponowna generacja przy istniejącym szkicu kończy się tą samą operacją co
 * „Użyj nowej wersji” (zastąpienie szkicu, zatwierdzone wersje zostają) —
 * rekruter o nią prosił, więc karta robi to sama, gdy CV jest gotowe. Zamiast
 * licznika kontroli AI karta pokazuje jedną liczbę „N rzeczy do sprawdzenia
 * przed wysłaniem” (`CvToClientChecks`) z „Sprawdź i popraw” → edytor na
 * panelu „Do poprawy”.
 *
 * 12.10.2026 — „Użyj innego CV”: pomiar na produkcji pokazał, że 16 z 22
 * auto-CV z dwóch tygodni powstało dla osób, które miały już gotowe CV,
 * a karta dawała tylko „Wygeneruj ponownie”. Pasek „Ta osoba ma już gotowe
 * CV” podpowiada najlepsze z nich, a okno `UseOtherCvDialog` daje wybór:
 * CV etapu z innej rekrutacji (z poprawkami rekrutera), plik Word z profilu
 * albo z dysku. Kopia bez dokumentu generatora ma własną plakietkę
 * pochodzenia i własne dołączenie zgody RODO.
 *
 * Karta NICZEGO nie blokuje („Kanban bez bramek”): ruch na „CV wysłane”
 * i stawka do klienta żyją obok, w warsztacie wysyłki. Brak zgody RODO
 * wyłącza wyłącznie pobranie pliku — serwer i tak odpowiada wtedy 409.
 *
 * 14.10.2026 („Droga rekrutera do DL”): `handoff` idzie do każdego otwarcia
 * edytora z tej karty (stopka „Zapisz i przekaż do DL”, D6) — wołający podaje
 * go tylko na „Zweryfikowany”. Po „Zapisz i przekaż dalej” w formularzu
 * (`forwarded`) karta pokazuje nad treścią blok postępu: screening → CV → QC,
 * pyta serwer co 4 s, aż automat założy CV albo powie, czemu go nie zrobił
 * (najdłużej 5 min), i daje „Następna w Screeningu” — bez samego skoku.
 *
 * 14.10.2026 (Edytor CV 3, „Ekran 5”): zespół mówił, że karta jest chaotyczna.
 * Gotowe CV to miniatura prawdziwej pierwszej strony pliku dla klienta (PDF
 * z pliku Word, `CvFirstPageThumb`) z liczbą stron obok; „Podgląd” zastąpił
 * klik w miniaturę, „Edytuj” — „Otwórz i popraw”, a rzadkie akcje („Pobierz
 * PDF”, „Użyj innego CV”, „Historia wersji”, „Wygeneruj ponownie”) są w menu
 * „⋯”. PDF stron jest pobierany raz na wersję CV i dzielony przez miniaturę
 * i okno stron — zamiana na serwerze kosztuje ok. 2 s procesora.
 */

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Circle,
  Download,
  Eye,
  FileDown,
  FileText,
  History,
  Info,
  Loader2,
  MoreHorizontal,
  Pencil,
  RefreshCcw,
  Repeat2,
  Sparkles,
  Undo2,
  RotateCcw,
  X,
} from "lucide-react";

import {
  candidateStageCvApi,
  type CVBrandedRewrite,
  type CVOriginalSnapshot,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadAuthenticatedFile,
  downloadBlob,
  postAuthenticatedDownload,
} from "@/lib/authenticated-files";
import { withDownloadIntent, type CvDownloadSurface } from "@/lib/cv-download-intent";
import { CV_CONTENT_MODES } from "@/lib/cv-generator";
import { countForm } from "@/lib/cv-qc";
import { cvAiSourcesQueryKey, fetchCvAiSources } from "@/lib/cv-ai-sources";
import { sourceCvWarning } from "@/lib/cv-generate-confirm";
import type { CvEditorHandoff } from "@/lib/cv-editor-handoff";
import {
  cvToClientIssuesQueryKey,
  cvToClientQcQueryKey,
  cvToClientRowsQueryKey,
  cvToClientShouldPoll,
  forwardProgress,
  resolveCvToClient,
  stageBrandedQueryKey,
  stageCvOrigin,
  type ForwardStep,
} from "@/lib/cv-to-client";
import { bestReadyCv, otherReadyCvCount, type StageCvOption } from "@/lib/stage-cv-options";
import {
  BACKGROUND_EVENTS_STEP,
  autoCvSkipReason,
  jobBackgroundEventsApi,
  jobBackgroundEventsQueryKey,
  latestAutoCvSkip,
} from "@/lib/job-background-events";
import { cn, formatDate } from "@/lib/utils";
import { readCvRewriteDraft, writeCvRewriteDraft } from "@/lib/cv-rewrite-drafts";
import { useAuthStore } from "@/store/auth";
import { useCvToClientRows } from "@/hooks/useCvToClientRows";
import { useStageBrandedCv } from "@/hooks/useStageBrandedCv";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ConsentAttachButton } from "@/components/v2/cv-generator/ConsentAttachButton";
import { CVOriginalPreviewModal } from "@/components/v2/modals/CVOriginalPreviewModal";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { CvGeneratePanel } from "@/components/v2/recruitment/CvGeneratePanel";
import { CvRewriteForm, REWRITE_MAX } from "@/components/v2/recruitment/CvRewriteForm";
import { CvFilePreviewDialog } from "@/components/v2/cv/CvFilePreviewDialog";
import { CvFirstPageThumb } from "@/components/v2/cv/CvFirstPageThumb";
import { fetchStageCvFile, fetchStageCvPdf } from "@/lib/stage-cv-file";
import { normalizeCvAlign } from "@/lib/cv-editor-align";
import { CvToClientChecks, useCvChecksCount } from "@/components/v2/recruitment/CvToClientChecks";
import { UseOtherCvDialog } from "@/components/v2/recruitment/UseOtherCvDialog";
import { useStageCvUpload } from "@/components/v2/person/StageCvUpload";
import { useReadyCvChoice } from "@/components/v2/recruitment/useReadyCvChoice";

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

/** Ostatnie pominięcie auto-CV tej osoby z „Pracy w tle” rekrutacji (albo `null`). */
function useAutoCvSkip(jobId: number, candidateId: number) {
  const query = useQuery({
    queryKey: jobBackgroundEventsQueryKey(jobId, BACKGROUND_EVENTS_STEP),
    queryFn: () => jobBackgroundEventsApi.list(jobId, BACKGROUND_EVENTS_STEP),
    retry: false,
    staleTime: 30_000,
  });
  return latestAutoCvSkip(query.data?.items ?? [], candidateId);
}

/**
 * Dlaczego automat NIE przygotował CV tej osoby (np. reguła klienta wymaga
 * zrzutu zgody RODO). Źródłem jest „Praca w tle” rekrutacji — ten sam klucz
 * zapytania co okno „Historia i czat”, bez osobnego endpointu. Informacja, nie
 * bramka: ładowanie, błąd i brak zdarzenia nie rysują nic.
 */
export function AutoCvSkipNotice({ jobId, candidateId }: { jobId: number; candidateId: number }) {
  const skipped = useAutoCvSkip(jobId, candidateId);
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

/** Następna osoba w kolumnie Tablicy (lustro `NextInColumn` panelu osoby). */
export interface CvCardNextPerson {
  candidateId: number;
  name: string;
  detail?: string | null;
}

const STEP_ICON: Record<ForwardStep["tone"], React.ReactNode> = {
  done: <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />,
  busy: <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-primary" aria-hidden />,
  pending: <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />,
  warn: <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />,
  info: <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" aria-hidden />,
};

/** Krok bloku postępu: ikona stanu i zdanie. */
function ProgressStep({ step }: { step: ForwardStep }) {
  return (
    <li className="flex items-start gap-2" data-tone={step.tone}>
      {STEP_ICON[step.tone]}
      <span className={cn("min-w-0 [overflow-wrap:anywhere]", step.tone === "pending" && "text-muted-foreground")}>
        {step.text}
      </span>
    </li>
  );
}

/**
 * Blok postępu po „Zapisz i przekaż dalej” (P3, 14.10.2026): screening
 * zapisany → CV → QC, zdanie o dzwonku i „Następna w Screeningu”.
 */
function ForwardProgressBlock({
  cv,
  qc,
  waiting,
  next,
  onOpenPerson,
}: ReturnType<typeof forwardProgress> & {
  next: CvCardNextPerson | null;
  onOpenPerson?: (candidateId: number) => void;
}) {
  return (
    <div data-testid="cv-forward-progress" className="space-y-2 rounded-lg border border-border bg-muted/30 px-3 py-2">
      <ol aria-label="Po przekazaniu" className="space-y-1 text-xs text-foreground">
        <ProgressStep step={{ tone: "done", text: "Screening zapisany" }} />
        <ProgressStep step={cv} />
        <ProgressStep step={qc} />
      </ol>
      {waiting ? (
        <p className="text-[11px] text-muted-foreground">
          Dam znać w ikonie „CV”, gdy CV będzie gotowe. Możesz w tym czasie zająć się kolejną osobą.
        </p>
      ) : null}
      {next && onOpenPerson ? (
        <Button
          size="sm"
          variant="outline"
          className="h-auto max-w-full whitespace-normal py-1 text-left"
          onClick={() => onOpenPerson(next.candidateId)}
        >
          <span className="min-w-0 [overflow-wrap:anywhere]">
            Następna w Screeningu: {next.name}
            {next.detail ? <span className="text-muted-foreground"> ({next.detail})</span> : null} · Otwórz
          </span>
          <ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden />
        </Button>
      ) : null}
    </div>
  );
}

/**
 * „Ta osoba ma już gotowe CV” — podpowiedź zamiast generacji. Pokazuje
 * najlepsze z gotowych CV (CV etapu z innej rekrutacji, potem plik Word,
 * potem generację spoza tej rekrutacji); resztę otwiera okno wyboru.
 */
function ReadyCvHint({
  best,
  count,
  busy,
  onUse,
  onShowAll,
}: {
  best: StageCvOption;
  count: number;
  busy: boolean;
  onUse: () => void;
  onShowAll: () => void;
}) {
  return (
    <div
      role="note"
      data-testid="ready-cv-hint"
      className="space-y-2 rounded-md border border-info/25 bg-info-muted px-2.5 py-2 text-xs text-info-muted-foreground"
    >
      <div className="flex items-start gap-1.5">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <div className="min-w-0">
          <p className="font-semibold">Ta osoba ma już gotowe CV</p>
          <p className="break-words">
            {best.title}
            {best.origin ? ` · ${best.origin}` : ""}
          </p>
          {best.detail ? <p className="break-words">{best.detail}</p> : null}
          {best.note ? <p className="mt-0.5">{best.note}</p> : null}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Button size="sm" loading={busy} disabled={busy} onClick={onUse}>
          Użyj tego CV
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onShowAll}>
          {count > 1 ? `Pokaż wszystkie (${count})` : "Inne źródło albo plik z dysku"}
        </Button>
      </div>
    </div>
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
  /** Harness `/preview/cv-to-client`: panel „Z czego powstało” otwarty od razu. */
  initialGenerateOpen?: boolean;
  /**
   * Przekazanie Delivery Leadowi ze stopki edytora (D6, 14.10.2026) — idzie
   * do każdego otwarcia edytora z tej karty. Wołający podaje je tylko, gdy
   * karta stoi na „Zweryfikowany” i nie jest tylko do odczytu.
   */
  handoff?: CvEditorHandoff;
  /** Osobę przed chwilą przekazano dalej z formularza — blok postępu (P3). */
  forwarded?: boolean;
  /** „Następna w Screeningu” — kto czeka w kolejności Tablicy; `null` = nikt. */
  nextInScreening?: CvCardNextPerson | null;
  /** Otwiera wskazaną osobę w panelu (jak „›”); bez niego przycisku nie ma. */
  onOpenPerson?: (candidateId: number) => void;
  /**
   * Osoba jest już u klienta („CV wysłane” i dalej, D3 14.10.2026): klient ma
   * plik, więc karta nie podmienia CV na inne i nie generuje go od nowa.
   * Zostają podgląd, „Otwórz i popraw” (edytor zapisuje historię wersji),
   * pobieranie i dołączenie zgody RODO.
   */
  lockedAfterSend?: boolean;
  /**
   * Plik CV do „Podglądu” (bez intencji pobrania). Harness `/preview/cv-to-client`
   * podaje plik z pamięci — w `/preview/*` zapytania POST są blokowane.
   */
  loadStageCvFile?: (stageId: number) => Promise<{ blob: Blob }>;
  /**
   * Strony CV (PDF z pliku Word): miniatura, okno stron i „Pobierz PDF”
   * (z `download`). Harness podaje plik z pamięci.
   */
  loadStageCvPdf?: (
    stageId: number,
    opts?: { download?: CvDownloadSurface },
  ) => Promise<{ blob: Blob; filename?: string | null }>;
}

/** Bez zgody RODO serwer i tak odpowie 409 — miniatura nie pyta wcale. */
const noPagesWithoutConsent = () => Promise.reject(new Error("consent_required"));

/** Radix oddaje fokus PO `onSelect` — okno otwarte w tym samym ticku zamknęłoby się. */
const afterMenuCloses = (action: () => void) => () => window.setTimeout(action, 0);

function quoteList(items: readonly string[]): string {
  const quoted = items.map((item) => `„${item}”`);
  if (quoted.length <= 1) return quoted[0] ?? "";
  return `${quoted.slice(0, -1).join(", ")} i ${quoted[quoted.length - 1]}`;
}

/** Zdanie po „Napisz od nowa”: co zostało w wersji rekrutera (makieta „Ekran 4”). */
function rewriteSentence(result: CVBrandedRewrite): string {
  if (!result.recognized) {
    return "Nowa wersja CV. Ręcznych poprawek nie dało się rozpoznać — to cała nowa wersja.";
  }
  if (result.kept.length === 0) return "Nowa wersja CV.";
  return `Nowa wersja CV. ${quoteList(result.kept)} ${result.kept.length === 1 ? "zostało" : "zostały"} w Twojej wersji.`;
}

export function CvToClientCard({
  stageId,
  candidateId,
  candidateName,
  jobId,
  jobTitle,
  readOnly,
  initialGenerateOpen = false,
  handoff,
  forwarded = false,
  nextInScreening = null,
  onOpenPerson,
  lockedAfterSend = false,
  loadStageCvFile = fetchStageCvFile,
  loadStageCvPdf = fetchStageCvPdf,
}: CvToClientCardProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const jobLabel = jobTitle?.trim() || `Rekrutacja #${jobId}`;
  // Podmiana CV (inne CV, generacja, nowa wersja z generatora) — nie po wysyłce.
  const canReplace = !readOnly && !lockedAfterSend;

  // Panel „Z czego powstało” (generacja w karcie, bez okna generatora).
  const [generateOpen, setGenerateOpen] = useState(initialGenerateOpen);
  const [editorOpen, setEditorOpen] = useState(false);
  // „Sprawdź i popraw” otwiera edytor od razu na panelu „Do poprawy”,
  // „Historia wersji” z menu „⋯” — na historii.
  const [editorPanel, setEditorPanel] = useState<"issues" | "history" | undefined>(undefined);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [originalOpen, setOriginalOpen] = useState(false);
  const [otherOpen, setOtherOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  // Liczba stron z miniatury — ważna tylko dla wersji CV, z której pochodzi.
  const [pages, setPages] = useState<{ key: string; count: number } | null>(null);
  // Generacja zlecona z TEJ karty — czekamy, aż serwer ją podepnie do etapu
  // (`replace` = etap miał już CV: gotową wersję podpinamy sami, jak „Użyj
  // nowej wersji”, bo serwer podpina tylko do etapu bez szkicu). Wiersz etapu
  // i wersję szkicu zapamiętujemy w chwili zlecenia: edycja szkicu w trakcie
  // generacji ma dać 409 przy podmianie, a nie zostać nadpisana.
  const [pending, setPending] = useState<{
    id: number;
    expired: boolean;
    replace: boolean;
    stageId: number;
    revision: number;
    // „Napisz od nowa” (PR 5): ręcznie poprawione części szkicu zostają.
    keepEdits: boolean;
  } | null>(null);
  // „Napisz od nowa” (Edytor CV 3, PR 5): uwaga dla panelu generacji
  // (`undefined` = zwykły panel) i wynik podmiany. Pole z listą poprawek
  // i jej szkicem to `CvRewriteForm`.
  const [rewrite, setRewrite] = useState<string | undefined>(undefined);
  const userId = useAuthStore((s) => s.user?.id);
  const [rewriteResult, setRewriteResult] = useState<
    (CVBrandedRewrite & { stageId: number; revision: number }) | null
  >(null);
  const pendingId = pending?.id ?? null;
  useEffect(() => {
    if (pendingId == null) return;
    const timer = setTimeout(
      () => setPending((current) => (current?.id === pendingId ? { ...current, expired: true } : current)),
      PENDING_TIMEOUT_MS,
    );
    return () => clearTimeout(timer);
  }, [pendingId]);

  // Runda 11 (PIPE-3, F23): ruch na kolejną kolumnę zakłada nowy wiersz etapu
  // bez CV, a CV firmowe zostaje na wierszu, na którym powstało. Serwer
  // wskazuje ten wiersz (`pair_source_stage_id`) — karta pokazuje, pobiera
  // i edytuje TEN dokument zamiast proponować generację od nowa.
  const { query: brandedQuery, pairStageId, cvStageId } = useStageBrandedCv(stageId);
  const rowsQuery = useCvToClientRows(candidateId, jobId);
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

  // „Użyj innego CV”: gotowe CV tej osoby zamiast generacji. Podpowiedź
  // pokazujemy, gdy CV jeszcze nie ma albo leży auto-CV, którego nikt nie
  // przejrzał — rekruter, który sam wygenerował albo wybrał CV, już zdecydował.
  const hasCv = branded != null && branded.status !== "none";
  // Dopiero po wczytaniu stanu karty: w trakcie ładowania „brak CV” jest
  // tylko brakiem danych i pytalibyśmy o gotowe CV przy każdym otwarciu.
  const hintWanted =
    canReplace &&
    brandedQuery.isSuccess &&
    rowsQuery.isSuccess &&
    (state.kind === "none" || (state.kind === "ready" && state.needsReview));
  const choice = useReadyCvChoice({
    candidateId,
    jobId,
    stageId,
    targetStageId: cvStageId,
    revision: branded?.edit_revision ?? 0,
    replaces: hasCv,
    enabled: canReplace && (hintWanted || otherOpen),
    onChosen: () => {
      setOtherOpen(false);
      // Wybrane CV kończy czekanie na generację zleconą z tej karty.
      setPending(null);
    },
  });
  // „Wygeneruj z tego pliku” z okna (29.10.2026): plik jako CV kandydata, jak
  // z kafelka „Wgraj nowe CV”, a potem panel generowania w tej karcie.
  const candidateCvUpload = useStageCvUpload({
    candidateId,
    stageId,
    jobId,
    onUploaded: (kind) => {
      if (kind !== "original") return;
      setOtherOpen(false);
      openGenerator();
    },
  });
  const bestReady = hintWanted && !choice.isPending ? bestReadyCv(choice.options) : null;
  const readyHint = bestReady ? (
    <ReadyCvHint
      best={bestReady}
      count={otherReadyCvCount(choice.options)}
      busy={choice.busyKey != null || choice.uploading}
      onUse={() => void choice.choose(bestReady)}
      onShowAll={() => setOtherOpen(true)}
    />
  ) : null;
  const useOtherButton = canReplace ? (
    <Button size="sm" variant="outline" onClick={() => setOtherOpen(true)}>
      <Repeat2 className="h-3.5 w-3.5" aria-hidden />{" "}
      {hasCv ? "Użyj innego CV" : "Użyj gotowego CV"}
    </Button>
  ) : null;
  const origin = stageCvOrigin(branded);

  // Po „Zapisz i przekaż dalej” (14.10.2026). Od 21.10.2026 ruch nie generuje
  // CV — karta nie czeka na automat. Powód pominięcia z „Pracy w tle” liczy się
  // tylko w trybie z flagą `CV_AUTO_GENERATE_WITHOUT_CONFIRMATION`.
  const [forwardedAt, setForwardedAt] = useState<number | null>(() => (forwarded ? Date.now() : null));
  useEffect(() => {
    setForwardedAt(forwarded ? Date.now() : null);
  }, [forwarded]);
  const skip = useAutoCvSkip(jobId, candidateId);
  // Stare pominięcie (np. z poprzedniej weryfikacji) nie jest odpowiedzią na
  // to przekazanie; dwie minuty zapasu na rozjazd zegara przeglądarki i serwera.
  const freshSkip =
    forwarded && skip && (forwardedAt == null || !skip.created_at || Date.parse(skip.created_at) >= forwardedAt - 120_000)
      ? skip
      : null;

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
      if (pairStageId != null) {
        void queryClient.invalidateQueries({ queryKey: stageBrandedQueryKey(pairStageId) });
      }
    }, POLL_MS);
    return () => clearInterval(id);
  }, [polling, queryClient, candidateId, jobId, stageId, pairStageId]);

  // 21.10.2026: po przekazaniu do „Zweryfikowany” potwierdzenia otwierają się
  // same — CV powstaje dopiero po nich. Raz na przekazanie, bez wymuszania
  // po „Anuluj”.
  const openedAfterForward = useRef(false);
  const settledNone =
    !brandedQuery.isLoading && !rowsQuery.isLoading && !brandedQuery.isError && state.kind === "none";
  useEffect(() => {
    if (!forwarded) {
      openedAfterForward.current = false;
      return;
    }
    if (openedAfterForward.current || !canReplace || !settledNone) return;
    openedAfterForward.current = true;
    setGenerateOpen(true);
  }, [forwarded, canReplace, settledNone]);

  // Koniec czekania: serwer podpiął CV (etap ma treść) albo generacja padła.
  useEffect(() => {
    if (!pending || pending.replace) return;
    if (state.kind === "ready" || state.kind === "failed") setPending(null);
  }, [pending, state.kind]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: cvToClientRowsQueryKey(candidateId, jobId) });
    void queryClient.invalidateQueries({ queryKey: stageBrandedQueryKey(stageId) });
    if (pairStageId != null) {
      void queryClient.invalidateQueries({ queryKey: stageBrandedQueryKey(pairStageId) });
    }
    // Liczba rzeczy do sprawdzenia i „Z czego powstało” po edycji albo nowym CV.
    void queryClient.invalidateQueries({ queryKey: cvToClientQcQueryKey(cvStageId).slice(0, 3) });
    void queryClient.invalidateQueries({ queryKey: cvToClientIssuesQueryKey(cvStageId).slice(0, 3) });
    void queryClient.invalidateQueries({ queryKey: cvAiSourcesQueryKey(cvStageId).slice(0, 1) });
  };

  const attachVersionMut = useMutation({
    mutationFn: (target: { stageId: number; generatedId: number; revision: number; keepEdits?: boolean }) =>
      target.keepEdits
        ? candidateStageCvApi.branded.selectGenerated(target.stageId, target.generatedId, target.revision, undefined, {
            keepEdits: true,
          })
        : candidateStageCvApi.branded.selectGenerated(target.stageId, target.generatedId, target.revision),
    onSuccess: (response, target) => {
      queryClient.setQueryData(stageBrandedQueryKey(target.stageId), response.data);
      void queryClient.invalidateQueries({ queryKey: cvToClientRowsQueryKey(candidateId, jobId) });
      const rewritten = response.data.rewrite;
      if (rewritten) {
        setRewriteResult({ ...rewritten, stageId: target.stageId, revision: response.data.edit_revision ?? 0 });
        return;
      }
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

  const restorePreviousMut = useMutation({
    mutationFn: (target: { stageId: number; revision: number }) =>
      candidateStageCvApi.branded.restorePrevious(target.stageId, target.revision),
    onSuccess: (response, target) => {
      queryClient.setQueryData(stageBrandedQueryKey(target.stageId), response.data);
      setRewriteResult(null);
      refresh();
      showSuccess("Przywrócono poprzednią wersję CV.");
    },
    onError: (error) =>
      showError(apiErrorMessage(error, "Nie udało się przywrócić poprzedniej wersji. Odśwież i spróbuj ponownie.")),
  });

  // „Odrzuć to CV i zacznij od nowa” (21.10.2026): karta wraca do potwierdzeń,
  // treść idzie do historii wersji — nic nie jest kasowane.
  const { askConfirm, confirmDialog } = useConfirmV2();
  const discardMut = useMutation({
    mutationFn: (target: { stageId: number; revision: number }) =>
      candidateStageCvApi.branded.discard(target.stageId, target.revision),
    onSuccess: (response, target) => {
      queryClient.setQueryData(stageBrandedQueryKey(target.stageId), response.data);
      setRewriteResult(null);
      refresh();
      setEditorOpen(false);
      setGenerateOpen(true);
      showSuccess("CV odrzucone. Potwierdź, z czego zrobić nowe.");
    },
    onError: (error) =>
      showError(apiErrorMessage(error, "Nie udało się odrzucić CV — odśwież i spróbuj ponownie.")),
  });
  const discardCv = async () => {
    if (!branded) return;
    const ok = await askConfirm({
      title: "Odrzucić to CV do klienta?",
      description:
        "Karta wróci do wyboru pliku, odpowiedzi i notatek. To CV zostaje w historii wersji i w plikach kandydata — nic nie jest kasowane.",
      confirmLabel: "Odrzuć i zacznij od nowa",
    });
    if (ok) discardMut.mutate({ stageId: cvStageId, revision: branded.edit_revision ?? 0 });
  };

  // „Powstało z: <plik>” — źródło bieżącej wersji (ten sam odczyt co panel).
  const sourcesQuery = useQuery({
    queryKey: cvAiSourcesQueryKey(cvStageId),
    queryFn: () => fetchCvAiSources(cvStageId),
    enabled: state.kind === "ready",
    retry: false,
  });
  const usedFile = state.kind === "ready" ? (sourcesQuery.data?.last_source_cv ?? null) : null;
  const sourceWarning = state.kind === "ready" ? sourceCvWarning(sourcesQuery.data) : null;

  /** „Użyj nowej wersji” — wersja szkicu z chwili kliknięcia. */
  const attachNewVersion = (generatedId: number) =>
    attachVersionMut.mutate({ stageId: cvStageId, generatedId, revision: branded?.edit_revision ?? 0 });

  const download = async () => {
    if (!branded) return;
    setDownloading(true);
    try {
      if (branded.status === "finalized") {
        await downloadAuthenticatedFile(
          withDownloadIntent(
            `/api/candidates/stages/${cvStageId}/cv/branded/versions/${branded.version}/docx`,
            "card",
          ),
          branded.docx_filename || "CV.docx",
        );
      } else {
        const result = await postAuthenticatedDownload(
          withDownloadIntent(`/api/candidates/stages/${cvStageId}/cv/branded/preview-docx`, "card"),
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

  // Strony CV (PDF z pliku Word) — raz na treść CV, wspólne dla miniatury
  // i okna stron: zamiana na serwerze kosztuje ok. 2 s procesora. Nieudany
  // odczyt nie zostaje w pamięci, okno stron spróbuje jeszcze raz.
  // Edytor zapisuje szkic co kilka sekund w tym samym kluczu zapytania, który
  // czyta karta — gdy jest otwarty, klucz stoi, a miniatura odświeża się raz,
  // po zamknięciu (inaczej każdy autozapis to nowa zamiana i limit 20/min).
  const liveKey = `${cvStageId}:${branded?.status ?? "none"}:${branded?.version ?? 0}:${branded?.edit_revision ?? 0}`;
  const [pagesKey, setPagesKey] = useState(liveKey);
  useEffect(() => {
    if (!editorOpen) setPagesKey(liveKey);
  }, [editorOpen, liveKey]);
  const pagesPdf = useRef<{ key: string; promise: Promise<Blob> } | null>(null);
  const loadPagesPdf = () => {
    if (pagesPdf.current?.key !== pagesKey) {
      const promise = loadStageCvPdf(cvStageId).then((file) => file.blob);
      const entry = { key: pagesKey, promise };
      promise.catch(() => {
        if (pagesPdf.current === entry) pagesPdf.current = null;
      });
      pagesPdf.current = entry;
    }
    return pagesPdf.current.promise;
  };

  /** „Pobierz PDF” z menu „⋯” — serwer zapisuje pobranie (format `pdf`). */
  const downloadPdf = async () => {
    setDownloadingPdf(true);
    try {
      const file = await loadStageCvPdf(cvStageId, { download: "card" });
      downloadBlob(file.blob, file.filename || (branded?.status === "finalized" ? "CV.pdf" : "SZKIC_CV.pdf"));
    } catch (error) {
      // 409 bez zgody i 503 (PDF chwilowo niedostępny) niosą polski komunikat serwera.
      showError(apiErrorMessage(error, "Nie udało się pobrać PDF. Spróbuj za chwilę albo pobierz plik Word."));
    } finally {
      setDownloadingPdf(false);
    }
  };

  // Ponowna generacja przy istniejącym CV: gotową wersję podpinamy sami
  // (ta sama operacja co „Użyj nowej wersji”). Raz na generację; odmowa
  // (szkic zmienił się w innym oknie) zostawia przycisk „Użyj nowej wersji”.
  const pendingRow =
    pending != null ? ((rowsQuery.data ?? []).find((row) => row.id === pending.id) ?? null) : null;
  const replaceTried = useRef<number | null>(null);
  const attachVersion = attachVersionMut.mutate;
  const attachedId = branded?.generated_document_id ?? null;
  const pendingStatus = pendingRow?.status ?? null;
  const currentRevision = branded?.edit_revision ?? null;
  useEffect(() => {
    if (!pending?.replace) return;
    if (attachedId === pending.id) {
      setPending(null);
      return;
    }
    if (pendingStatus !== "ready" || replaceTried.current === pending.id) return;
    // „Napisz od nowa” scala z BIEŻĄCYM szkicem (poprawki z czasu generacji
    // też zostają), ale nie pod otwartym edytorem — po jego zamknięciu.
    if (pending.keepEdits && editorOpen) return;
    replaceTried.current = pending.id;
    attachVersion(
      {
        stageId: pending.stageId,
        generatedId: pending.id,
        revision: pending.keepEdits ? (currentRevision ?? pending.revision) : pending.revision,
        keepEdits: pending.keepEdits,
      },
      { onSettled: () => setPending(null) },
    );
  }, [pending, attachedId, pendingStatus, attachVersion, editorOpen, currentRevision]);
  const replacing = pending?.replace === true && pendingStatus === "ready";
  const replaceFailed = pending?.replace === true && pendingStatus === "failed" ? pendingRow : null;

  const openGenerator = () => {
    setRewrite(undefined);
    setEditorOpen(false);
    setGenerateOpen(true);
  };
  /** „Napisz od nowa” z karty albo z asystenta w edytorze (edytor zamknął się sam). */
  const startRewrite = (instruction: string) => {
    if (!rewriteAvailable) return;
    // Polecenie z asystenta („Napisz od nowa: …”) też nie przekroczy limitu serwera.
    setRewrite(instruction.trim().slice(0, REWRITE_MAX));
    setRewriteResult(null);
    setEditorOpen(false);
    setGenerateOpen(true);
  };
  const openEditor = (panel?: "issues" | "history") => {
    setEditorPanel(panel);
    setEditorOpen(true);
  };
  // CV pary z innego wiersza etapu (runda 11): bieżący wiersz jest pusty, więc
  // serwer podepnie nową wersję do niego sam — szkicu tamtego wiersza nie ruszamy.
  const replacesDraft = hasCv && pairStageId == null;
  // „Napisz od nowa” tylko, gdy nic innego nie podmienia szkicu tej karty.
  // Po „CV wysłane” (`lockedAfterSend`) CV u klienta nie jest pisane od nowa (D3).
  const rewriteAvailable = canReplace && replacesDraft && !generateOpen && !pending && !replacing;
  const onEnqueued = (generatedId: number) => {
    setPending({
      id: generatedId,
      expired: false,
      replace: replacesDraft,
      stageId: cvStageId,
      revision: branded?.edit_revision ?? 0,
      keepEdits: rewrite !== undefined && replacesDraft,
    });
    setRewrite(undefined);
    setGenerateOpen(false);
    void queryClient.invalidateQueries({ queryKey: cvToClientRowsQueryKey(candidateId, jobId) });
  };
  /** Przycisk otwierający panel generacji — znika, gdy panel jest otwarty. */
  const generateButton = (label: string, primary: boolean, icon: "sparkles" | "refresh") =>
    generateOpen ? null : (
      <Button size="sm" variant={primary ? "primary" : "ghost"} onClick={openGenerator}>
        {icon === "sparkles" ? (
          <Sparkles className="h-3.5 w-3.5" aria-hidden />
        ) : (
          <RefreshCcw className="h-3.5 w-3.5" aria-hidden />
        )}{" "}
        {label}
      </Button>
    );

  const loading = brandedQuery.isLoading || rowsQuery.isLoading;
  const loadFailed = brandedQuery.isError || rowsQuery.isError;
  const attached = state.attached ?? state.candidate;
  const modeLabel =
    CV_CONTENT_MODES.find((mode) => mode.value === attached?.content_mode)?.label ?? null;
  const languageLabel = attached?.language ? attached.language.toUpperCase() : null;

  // Blok postępu liczy rzeczy do sprawdzenia tymi samymi odczytami co karta.
  const checks = useCvChecksCount(cvStageId, branded?.edit_revision ?? null, forwarded && state.kind === "ready");
  // Awaria wczytania nie udaje „CV się generuje” — mówi o niej treść karty.
  const progress =
    forwarded && !loading && !(loadFailed && !branded)
      ? forwardProgress({
          state,
          origin,
          skipReason: freshSkip ? autoCvSkipReason(freshSkip) : null,
          manual: pending != null || state.generating?.origin !== "auto",
          checks,
        })
      : null;

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
    // Miniatura rysuje się od nowa przy każdej wersji CV i po dołączeniu zgody.
    const thumbKey = `${pagesKey}:${state.consentMissing ? "no-consent" : "consent"}`;
    const pagesLabel =
      pages?.key === pagesKey ? countForm(pages.count, ["strona", "strony", "stron"]) : null;
    const facts = [pagesLabel, modeLabel, languageLabel].filter((fact): fact is string => !!fact);
    const regenerateLabel = replaceFailed ? "Spróbuj ponownie" : "Wygeneruj ponownie";
    body = (
      <div className="space-y-2.5">
        <div className="flex items-start gap-3">
          <CvFirstPageThumb
            key={thumbKey}
            load={state.consentMissing ? noPagesWithoutConsent : loadPagesPdf}
            onOpen={() => setPreviewOpen(true)}
            onPages={(count) => setPages({ key: pagesKey, count })}
            label={`Otwórz strony CV — ${candidateName}`}
          />
          <div className="min-w-0 flex-1 space-y-2">
            <div data-testid="cv-ready-facts" className="space-y-1 text-xs text-muted-foreground">
              <Badge size="sm" variant={finalized ? "success" : "info"}>
                {finalized ? `wersja ${branded.version}` : "szkic"}
              </Badge>
              {facts.length > 0 ? <p>{facts.join(" · ")}</p> : null}
              {usedFile ? (
                <p data-testid="cv-source-file" className="[overflow-wrap:anywhere]">
                  Powstało z: <span className="font-medium text-foreground">{usedFile.filename ?? "plik CV"}</span>
                </p>
              ) : null}
            </div>
            {state.needsReview || origin ? (
              <div className="flex flex-wrap items-center gap-1.5">
                {state.needsReview ? (
                  <Badge size="sm" variant="warning" className="h-auto whitespace-normal py-0.5 text-left">
                    wygenerowane automatycznie — sprawdź przed wysyłką
                  </Badge>
                ) : null}
                {origin ? (
                  <Badge
                    size="sm"
                    variant={origin.tone === "warning" ? "warning" : "neutral"}
                    className="h-auto whitespace-normal py-0.5 text-left"
                    data-testid="cv-origin-badge"
                  >
                    {origin.badge}
                  </Badge>
                ) : null}
              </div>
            ) : null}
            {state.attached?.origin === "auto" && state.attached.created_at ? (
              <p className="text-[11px] text-muted-foreground">
                Wygenerowane automatycznie {formatDate(state.attached.created_at)}, po ruchu na
                „Zweryfikowany”.
              </p>
            ) : null}
            {origin ? <p className="text-[11px] text-muted-foreground">{origin.sentence}</p> : null}
            {sourceWarning ? (
              <div
                role="note"
                data-testid="cv-source-warning"
                className="space-y-1.5 rounded-md border border-warning/30 bg-warning-muted px-2.5 py-2 text-xs text-warning-muted-foreground"
              >
                <p className="[overflow-wrap:anywhere]">{sourceWarning}</p>
                {canReplace && !generateOpen ? (
                  <Button size="sm" variant="outline" onClick={openGenerator}>
                    <RefreshCcw className="h-3.5 w-3.5" aria-hidden /> Wygeneruj z innego pliku
                  </Button>
                ) : null}
              </div>
            ) : null}
            <div className="flex flex-wrap gap-1.5">
              {!readOnly ? (
                <Button size="sm" variant="outline" onClick={() => openEditor()}>
                  <Pencil className="h-3.5 w-3.5" aria-hidden /> Otwórz i popraw
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
                <Download className="h-3.5 w-3.5" aria-hidden /> Pobierz Word
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    aria-label="Więcej akcji CV"
                    title="Więcej akcji CV"
                    data-testid="cv-card-more"
                  >
                    <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    disabled={downloadingPdf || state.consentMissing}
                    title={
                      state.consentMissing
                        ? "Najpierw dołącz zrzut zgody RODO — bez niego nie pobierzesz CV."
                        : undefined
                    }
                    onSelect={() => void downloadPdf()}
                  >
                    <FileDown className="h-3.5 w-3.5" aria-hidden /> Pobierz PDF
                  </DropdownMenuItem>
                  {canReplace ? (
                    <DropdownMenuItem onSelect={afterMenuCloses(() => setOtherOpen(true))}>
                      <Repeat2 className="h-3.5 w-3.5" aria-hidden /> Użyj innego CV
                    </DropdownMenuItem>
                  ) : null}
                  {!readOnly ? (
                    <DropdownMenuItem onSelect={afterMenuCloses(() => openEditor("history"))}>
                      <History className="h-3.5 w-3.5" aria-hidden /> Historia wersji
                    </DropdownMenuItem>
                  ) : null}
                  {canReplace && !generateOpen ? (
                    <DropdownMenuItem onSelect={afterMenuCloses(openGenerator)}>
                      <RefreshCcw className="h-3.5 w-3.5" aria-hidden /> Wygeneruj ponownie
                    </DropdownMenuItem>
                  ) : null}
                  {canReplace && !generateOpen && !pending ? (
                    <DropdownMenuItem
                      disabled={discardMut.isPending}
                      onSelect={afterMenuCloses(() => void discardCv())}
                    >
                      <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Odrzuć to CV i zacznij od nowa
                    </DropdownMenuItem>
                  ) : null}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </div>
        {/* Pełna szerokość karty: obok miniatury zdanie i „Sprawdź i popraw” łamały się w słupek. */}
        <CvToClientChecks
          stageId={cvStageId}
          revision={branded.edit_revision ?? null}
          readOnly={readOnly}
          onReview={() => openEditor("issues")}
        />
        {readyHint}
        {state.consentMissing ? (
          <div
            role="note"
            className="flex flex-col items-start gap-2 rounded-md border border-destructive/25 bg-destructive-muted px-2.5 py-2 text-xs text-destructive-muted-foreground"
          >
            <span>
              Zgoda RODO: brak zrzutu. Bez niego nie pobierzesz CV.
            </span>
            {readOnly ? null : state.attached ? (
              <ConsentAttachButton
                compact
                generatedId={state.attached.id}
                hasConsent={false}
                onAttached={refresh}
              />
            ) : (
              // Kopia (plik Word, CV z innej rekrutacji, przepięcie) nie ma
              // dokumentu generatora — zgoda idzie na CV etapu.
              <ConsentAttachButton
                compact
                stageCopy={{ candidateId, stageId: cvStageId }}
                hasConsent={false}
                onAttached={refresh}
              />
            )}
          </div>
        ) : null}
        {rewriteResult && rewriteResult.stageId === cvStageId && rewriteResult.revision === branded.edit_revision ? (
          // Pasek znika sam, gdy rekruter zapisze dalsze poprawki (makieta „Ekran 4”).
          <div
            role="status"
            data-testid="cv-rewrite-result"
            className="flex flex-wrap items-center gap-2 rounded-md border border-success/25 bg-success-muted px-2.5 py-1.5 text-xs text-success-muted-foreground"
          >
            <span className="min-w-0 flex-1">{rewriteSentence(rewriteResult)}</span>
            {rewriteResult.can_restore && !readOnly ? (
              <Button
                size="sm"
                variant="outline"
                className="h-7 px-2"
                loading={restorePreviousMut.isPending}
                onClick={() =>
                  restorePreviousMut.mutate({ stageId: cvStageId, revision: branded.edit_revision ?? 0 })
                }
              >
                <Undo2 className="h-3.5 w-3.5" aria-hidden /> Wróć do poprzedniej
              </Button>
            ) : null}
            <button
              type="button"
              aria-label="Zamknij informację o nowej wersji"
              className="rounded p-0.5 hover:bg-success/10"
              onClick={() => setRewriteResult(null)}
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
        ) : null}
        {rewriteAvailable ? <CvRewriteForm stageId={cvStageId} onRewrite={startRewrite} /> : null}
        {state.generating ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" aria-hidden /> Generuje się nowa wersja…
            {pending?.replace && pending.id === state.generating.id
              ? " Zastąpi bieżący szkic, gdy będzie gotowa."
              : ""}
          </p>
        ) : null}
        {replacing ? (
          <p role="status" className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" aria-hidden /> Nowa wersja gotowa — podpinam ją jako
            szkic…
          </p>
        ) : null}
        {replaceFailed ? (
          <div className="space-y-1.5">
            <p role="alert" className="text-xs text-destructive-muted-foreground">
              Nowa wersja nie powstała
              {replaceFailed.error_message ? `: ${replaceFailed.error_message}` : "."} Bieżące CV zostaje.
            </p>
            {/* Ponowienie po awarii stoi przy komunikacie, nie tylko w „⋯”. */}
            {canReplace ? generateButton(regenerateLabel, false, "refresh") : null}
          </div>
        ) : null}
        {state.candidate && canReplace && !replacing ? (
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
              onClick={() => attachNewVersion(state.candidate!.id)}
            >
              Użyj nowej wersji
            </Button>
          </div>
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
          Możesz zamknąć panel. CV pojawi się tutaj i w plikach kandydata.
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
        {canReplace ? (
          <div className="flex flex-wrap gap-1.5">
            <Button
              size="sm"
              loading={attachVersionMut.isPending}
              disabled={attachVersionMut.isPending}
              onClick={() => attachNewVersion(state.candidate!.id)}
            >
              Użyj tej wersji
            </Button>
            {useOtherButton}
            {generateButton("Wygeneruj ponownie", false, "refresh")}
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
        {canReplace ? (
          <div className="flex flex-wrap gap-1.5">
            {generateButton("Spróbuj ponownie", true, "sparkles")}
            {useOtherButton}
          </div>
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
          {canReplace && state.candidate ? (
            <Button
              size="sm"
              variant="outline"
              loading={attachVersionMut.isPending}
              disabled={attachVersionMut.isPending}
              onClick={() => attachNewVersion(state.candidate!.id)}
            >
              Użyj wygenerowanego CV
            </Button>
          ) : null}
          {canReplace ? generateButton("Wygeneruj CV", true, "sparkles") : null}
          {useOtherButton}
        </div>
      </div>
    );
  } else if (lockedAfterSend) {
    body = <p className="text-sm text-foreground">CV firmowego nie ma w tej rekrutacji.</p>;
  } else {
    body = (
      <div className="space-y-2">
        <AutoCvSkipNotice jobId={jobId} candidateId={candidateId} />
        <p className="text-sm text-foreground">Jeszcze nie ma CV do klienta dla tej rekrutacji.</p>
        {readyHint}
        {!readOnly ? (
          <div className="space-y-1">
            <div className="flex flex-wrap gap-1.5">
              {generateOpen ? null : (
                <Button size="sm" variant={readyHint ? "outline" : "primary"} onClick={openGenerator}>
                  <Sparkles className="h-3.5 w-3.5" aria-hidden /> Generuj CV
                </Button>
              )}
              {/* Pasek ma już wejście do okna wyboru — bez drugiego obok. */}
              {readyHint ? null : useOtherButton}
            </div>
            <p className="text-[11px] text-muted-foreground">
              Najpierw potwierdzisz plik CV, odpowiedzi ze screeningu i dodatkowe notatki — CV powstaje
              dopiero po „Generuj”, nie samo po ruchu na „Zweryfikowany”.
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
      {confirmDialog}
      {progress ? (
        <ForwardProgressBlock {...progress} next={nextInScreening} onOpenPerson={onOpenPerson} />
      ) : null}
      {lockedAfterSend && state.kind !== "none" ? (
        <p className="text-xs text-muted-foreground" data-testid="cv-locked-after-send">
          CV jest już u klienta: nie podmienisz go i nie wygenerujesz od nowa. Poprawki zapisze
          edytor w historii wersji.
        </p>
      ) : null}
      {body}
      {generateOpen && canReplace ? (
        <CvGeneratePanel
          candidateId={candidateId}
          candidateName={candidateName}
          jobId={jobId}
          replaces={replacesDraft}
          onEnqueued={onEnqueued}
          onCancel={() => {
            // Anulowana lista poprawek wraca do pola, chyba że ktoś zaczął już nową.
            if (rewrite?.trim() && !readCvRewriteDraft(userId, cvStageId)) {
              writeCvRewriteDraft(userId, cvStageId, rewrite);
            }
            setGenerateOpen(false);
            setRewrite(undefined);
          }}
          rewrite={rewrite}
        />
      ) : null}
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

      {editorOpen && !readOnly ? (
        <CVBrandedEditModal
          open
          onOpenChange={(open) => {
            setEditorOpen(open);
            if (!open) refresh();
          }}
          onRegenerate={lockedAfterSend ? undefined : openGenerator}
          // W trakcie generacji drugiej nie zlecamy — wynik pierwszej by przepadł.
          onRewrite={rewriteAvailable ? startRewrite : undefined}
          initialPanel={editorPanel}
          stageId={cvStageId}
          jobTitle={jobLabel}
          candidateName={candidateName}
          handoff={handoff}
        />
      ) : null}
      {choice.confirmDialog}
      {candidateCvUpload.confirmDialog}
      {otherOpen && canReplace ? (
        <UseOtherCvDialog
          open
          onOpenChange={setOtherOpen}
          candidateId={candidateId}
          candidateName={candidateName}
          jobLabel={jobLabel}
          choice={choice}
          replaces={hasCv}
          onGenerateFromFile={candidateCvUpload.uploadAsOriginal}
          generatingFromFile={candidateCvUpload.isPending}
        />
      ) : null}
      {previewOpen ? (
        <CvFilePreviewDialog
          open
          onOpenChange={setPreviewOpen}
          title={`CV do klienta — ${candidateName}`}
          loadPdf={loadPagesPdf}
          load={() => loadStageCvFile(cvStageId).then((file) => file.blob)}
          fallbackHtml={branded?.content_html ?? null}
          language={branded?.language === "en" ? "en" : "pl"}
          textAlign={normalizeCvAlign(branded?.text_align)}
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
