"use client";

/**
 * PipelineCandidateDock — dok „Karta w procesie" (krok 04 Pipeline, program
 * „flow w języku C2", PR 3/7).
 *
 * Ten sam język co `JobMatchDock` w `/jobs/[id]/page.tsx` (warsztat C2):
 * dok obok tablicy, akcje na dole, zakładki montowane leniwie (dopiero po
 * kliknięciu). Ruch na etap NIE ma własnej logiki — woła `onMoveTo`, które
 * `KanbanBoardV2` podłącza do `requestMove` (ta sama gałąź co drag&drop:
 * modal stawki dla „Zweryfikowany", stawki do klienta dla „CV Wysłane",
 * potwierdzenie dla „Zatrudniony", powód dla etapów terminalnych).
 *
 * Świadomie BEZ „następnej akcji" — backend (`CandidateStageResponse`) nie
 * niesie takiego pola. Wymyślanie treści tego typu byłoby fabrykowaniem
 * danych, których system nie ma; gdy pole kiedyś powstanie, doda się tu
 * warunkowy blok, nie wcześniej.
 */

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileText,
  HelpCircle,
  Loader2,
  Mail,
  Send,
  Sparkles,
  UserPlus,
  UserX,
  X,
} from "lucide-react";

import api, {
  candidatesApi,
  candidateStageCvApi,
  extractErrorMsg,
  screeningApi,
  type CVBrandedState,
  type CVOriginalSnapshot,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TabbedNav } from "@/components/ds";
import { cn, formatDate } from "@/lib/utils";
import { countPl } from "@/lib/plural-pl";
import { encodeJobBackRef } from "@/lib/url-filters";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { DopasowanieTab } from "@/components/v2/pages/DopasowanieTab";
import { ScoreRing, type KanbanColumn, type KanbanItem } from "@/components/v2/pages/kanban-shared";
import { CVOriginalPreviewModal } from "@/components/v2/modals/CVOriginalPreviewModal";
import { CVShareLinkModal } from "@/components/v2/modals/CVShareLinkModal";
import { SendEmailV2 } from "@/components/v2/modals/SendEmailV2";

// Edytor brandowanego CV jest ciężki (rich text) — leniwy import jak w
// CandidateDetailV2, żeby nie puchła zakładka Pipeline dla osób, które go
// nigdy nie otworzą.
const CVBrandedEditModal = dynamic(
  () =>
    import("@/components/v2/modals/CVBrandedEditModal").then(
      (m) => m.CVBrandedEditModal
    ),
  { ssr: false }
);

export interface PipelineMoveTarget {
  col: KanbanColumn;
  blockedReason: string | null;
}

type DockTab = "process" | "screening" | "cv" | "match" | "notes";

const DOCK_TABS: { value: DockTab; label: string }[] = [
  { value: "process", label: "W procesie" },
  { value: "screening", label: "Screening" },
  { value: "cv", label: "CV" },
  { value: "match", label: "Dopasowanie" },
  { value: "notes", label: "Notatki" },
];

interface NoteListItem {
  id: number;
  content: string;
  content_rendered?: string | null;
  author_name?: string | null;
  created_at: string;
}

function daysLabel(n: number): string {
  return `${n} ${Math.abs(n) === 1 ? "dzień" : "dni"}`;
}

export interface PipelineCandidateDockProps {
  item: KanbanItem;
  jobId: number;
  currentStageLabel: string;
  /** Tytuł rekrutacji — nagłówki modali CV i zakładka „Dopasowanie". Bez
   *  niego fallback „Rekrutacja #id"; nigdy nazwa etapu (to inna rzecz). */
  jobTitle?: string;
  matchScore?: number | null;
  scoresLoading?: boolean;
  moveTargets: PipelineMoveTarget[];
  readOnly: boolean;
  contactFeatureEnabled: boolean;
  canReject: boolean;
  onClose: () => void;
  onMoveTo: (col: KanbanColumn) => void;
  onOpenScreening: (stageId: number, name: string) => void;
  onReject: () => void;
}

export function PipelineCandidateDock({
  item,
  jobId,
  currentStageLabel,
  jobTitle,
  matchScore,
  scoresLoading,
  moveTargets,
  readOnly,
  contactFeatureEnabled,
  canReject,
  onClose,
  onMoveTo,
  onOpenScreening,
  onReject,
}: PipelineCandidateDockProps) {
  const { showSuccess, showError } = useToast();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<DockTab>("process");
  const [openOriginal, setOpenOriginal] = useState(false);
  const [openBranded, setOpenBranded] = useState(false);
  const [openShare, setOpenShare] = useState(false);
  const [openEmail, setOpenEmail] = useState(false);
  const [noteText, setNoteText] = useState("");

  // Zmiana kandydata (nowy klik na tablicy) — wróć na pierwszą zakładkę i
  // wyczyść niedokończony draft notatki; inaczej dok pokazywałby zakładkę
  // „Notatki" poprzedniego kandydata z jego niewysłanym tekstem.
  useEffect(() => {
    setActiveTab("process");
    setNoteText("");
  }, [item.candidate_id]);

  const fullName = `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || "Kandydat";
  const jobLabel = jobTitle?.trim() || `Rekrutacja #${jobId}`;
  const initials = fullName
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  const isPending = item.verification_status === "pending";
  const normalizedScore =
    typeof matchScore === "number" && Number.isFinite(matchScore)
      ? Math.max(0, Math.min(100, Math.round(matchScore)))
      : null;

  const addedAttribution = item.added_to_job_by_name?.trim()
    ? `Dodano do rekrutacji przez: ${item.added_to_job_by_name.trim()}${
        item.added_to_job_at ? ` · ${formatDate(item.added_to_job_at)}` : ""
      }`
    : `Brak danych o osobie dodającej${
        item.added_to_job_at ? ` · dodano ${formatDate(item.added_to_job_at)}` : ""
      }`;

  // ── Screening — skrót wyniku, jeśli backend go ma ──────────────────────
  const screeningQuery = useQuery({
    queryKey: ["pipeline-stage-screening", item.id],
    queryFn: () => screeningApi.getForStage(item.id).then((r) => r.data),
    enabled: activeTab === "screening",
    staleTime: 30_000,
  });
  const screeningAnswers = screeningQuery.data?.screening_answers ?? null;

  // ── CV — status oryginalnego/brandowanego (tylko na zakładce CV) ───────
  const cvOriginalQuery = useQuery<CVOriginalSnapshot>({
    queryKey: ["cv-original", item.id],
    queryFn: () => candidateStageCvApi.original.get(item.id).then((r) => r.data),
    enabled: activeTab === "cv",
  });
  const cvBrandedQuery = useQuery<CVBrandedState>({
    queryKey: ["cv-branded", item.id],
    queryFn: () => candidateStageCvApi.branded.get(item.id).then((r) => r.data),
    enabled: activeTab === "cv" || openBranded || openShare,
  });
  const brandedStatus = cvBrandedQuery.data?.status ?? "none";

  // ── Notatki — przypięte do TEJ rekrutacji (candidate_id + job_id) ──────
  const notesQueryKey = useMemo(
    () => [...candidateQueryKeys.notes(item.candidate_id), jobId] as const,
    [item.candidate_id, jobId]
  );
  const notesQuery = useQuery<{ items?: NoteListItem[] }>({
    queryKey: notesQueryKey,
    queryFn: () =>
      api
        .get(`/api/notes?candidate_id=${item.candidate_id}&job_id=${jobId}`)
        .then((r) => r.data),
    enabled: activeTab === "notes",
  });
  const addNoteMutation = useMutation({
    mutationFn: (content: string) =>
      api.post("/api/notes", {
        candidate_id: item.candidate_id,
        job_id: jobId,
        content,
        note_type: "general",
      }),
    onSuccess: () => {
      setNoteText("");
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.notes(item.candidate_id),
      });
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.timelineRoot(item.candidate_id),
      });
      showSuccess("Notatka dodana.");
    },
    onError: (e) => showError(extractErrorMsg(e) || "Nie udało się dodać notatki"),
  });

  const submitNote = () => {
    const content = noteText.trim();
    if (!content || addNoteMutation.isPending) return;
    addNoteMutation.mutate(content);
  };

  // ── Email do kandydata — adres dociągamy leniwie, dopiero gdy modal się
  //    otwiera (pole nie istnieje na karcie kanbanu — patrz `KanbanItem`). ──
  const candidateDetailQuery = useQuery({
    queryKey: candidateQueryKeys.detail(item.candidate_id),
    queryFn: () => candidatesApi.get(item.candidate_id).then((r) => r.data),
    enabled: openEmail,
  });
  // Modal montuje się dopiero z DANYMI (patrz render niżej) — w oknie między
  // kliknięciem a odpowiedzią pole „Do" byłoby puste. Gdy zapytanie padnie,
  // intencja wysyłki jest zamykana z toastem, a nie wisi na spinnerze.
  const emailLookupFailed = openEmail && candidateDetailQuery.isError;
  useEffect(() => {
    if (!emailLookupFailed) return;
    showError("Nie udało się pobrać adresu e-mail kandydata.");
    setOpenEmail(false);
  }, [emailLookupFailed, showError]);

  return (
    <div className="flex max-h-[calc(100vh-2rem)] flex-col rounded-xl border border-border bg-card">
      {/* ── Nagłówek ──────────────────────────────────────────────────── */}
      <div className="space-y-2.5 border-b border-border p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
              {initials}
            </div>
            <div className="min-w-0">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-primary">
                Karta w procesie
              </div>
              <div className="truncate text-sm font-semibold text-foreground">
                {fullName}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-accent"
            aria-label="Zamknij dok"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {(normalizedScore != null || scoresLoading) && (
            <ScoreRing score={normalizedScore} density="compact" />
          )}
          {isPending && (
            <Badge variant="warning" size="sm">
              <HelpCircle className="h-2.5 w-2.5" /> Pending
            </Badge>
          )}
          {contactFeatureEnabled && (
            <ContactStatusBadge contactCase={item.contact_case} size="sm" />
          )}
          {item.hm_veto && (
            <Badge
              variant="danger"
              size="sm"
              title={[
                `${item.hm_veto.hiring_manager_name ?? "Hiring manager tej rekrutacji"} odrzucił(a) tego kandydata po rozmowie ${formatDate(item.hm_veto.rejected_at)}`,
                `Powód: ${item.hm_veto.rejection_reason_name}`,
                item.hm_veto.source_job_title
                  ? `Rekrutacja: ${item.hm_veto.source_job_title}`
                  : null,
              ]
                .filter(Boolean)
                .join("\n")}
            >
              <UserX className="h-2.5 w-2.5" /> Weto HM
            </Badge>
          )}
        </div>

        <TabbedNav
          ariaLabel="Zakładki karty kandydata"
          value={activeTab}
          onValueChange={(v) => setActiveTab(v as DockTab)}
          tabs={DOCK_TABS}
          overflow="scroll"
        />
      </div>

      {/* ── Treść zakładki (przewijana) ──────────────────────────────── */}
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {activeTab === "process" && (
          <div className="space-y-3">
            <div className="space-y-2 rounded-lg border border-border bg-muted/20 p-3 text-xs">
              <div className="flex items-center justify-between gap-2 font-medium text-foreground">
                <span className="truncate">Etap · {currentStageLabel}</span>
                {item.days_in_stage != null && (
                  <span className="inline-flex shrink-0 items-center gap-1 text-muted-foreground">
                    <Clock className="h-3 w-3" /> {daysLabel(item.days_in_stage)}
                  </span>
                )}
              </div>
              <div className="flex items-start gap-1.5 text-muted-foreground">
                <UserPlus className="mt-0.5 h-3 w-3 shrink-0" />
                <span>{addedAttribution}</span>
              </div>
            </div>

            {(item.expected_rate_value != null || item.budget_max_at_move != null) && (
              <div className="space-y-1">
                <div className="text-xs font-semibold text-foreground">
                  Warunki wobec oferty
                </div>
                <div className="grid grid-cols-[84px_minmax(0,1fr)] gap-x-2 gap-y-1 text-xs">
                  <span className="text-muted-foreground">Stawka</span>
                  <span>
                    {item.expected_rate_value != null ? (
                      <span className="font-medium tabular-nums text-foreground">
                        {item.expected_rate_value} {item.expected_rate_currency ?? "PLN"}
                        {item.expected_rate_unit ? `/${item.expected_rate_unit}` : ""}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">brak danych</span>
                    )}
                    {item.budget_max_at_move != null && (
                      <span className="ml-1 text-muted-foreground">
                        · budżet do {item.budget_max_at_move}
                      </span>
                    )}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === "screening" && (
          <div className="space-y-3">
            <Button
              size="sm"
              variant="outline"
              onClick={() => onOpenScreening(item.id, fullName)}
              className="w-full justify-start"
            >
              <Sparkles className="h-3.5 w-3.5" /> Otwórz Screening Championa
            </Button>
            {screeningQuery.isLoading ? (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie…
              </div>
            ) : screeningAnswers ? (
              <div className="space-y-1.5 rounded-lg border border-border bg-muted/20 p-3 text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-foreground">Wynik</span>
                  <Badge
                    size="sm"
                    variant={
                      screeningAnswers.overall_fit === "fit"
                        ? "success"
                        : screeningAnswers.overall_fit === "miss"
                          ? "danger"
                          : "warning"
                    }
                  >
                    {screeningAnswers.overall_fit === "fit"
                      ? "Pasuje"
                      : screeningAnswers.overall_fit === "miss"
                        ? "Nie pasuje"
                        : "Niepewne"}
                  </Badge>
                </div>
                <div className="text-muted-foreground">
                  Odpowiedziano na{" "}
                  {countPl(screeningAnswers.answers.length, "pytanie", "pytania", "pytań")}
                  {screeningAnswers.answers.some((a) => a.deal_breaker_hit) && (
                    <span className="ml-1 inline-flex items-center gap-0.5 text-destructive">
                      <AlertTriangle className="h-3 w-3" /> deal-breaker trafiony
                    </span>
                  )}
                </div>
                {screeningAnswers.answered_at && (
                  <div className="text-muted-foreground">
                    Wypełniono {formatDate(screeningAnswers.answered_at)}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Brak jeszcze wypełnionego screeningu dla tego etapu.
              </p>
            )}
          </div>
        )}

        {activeTab === "cv" && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-1.5">
              {cvOriginalQuery.isLoading ? (
                <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
              ) : cvOriginalQuery.data ? (
                cvOriginalQuery.data.has_snapshot ? (
                  <Badge size="sm" variant="success">
                    CV oryginalne
                  </Badge>
                ) : (
                  <Badge size="sm" variant="warning">
                    Brak CV w momencie zgłoszenia
                  </Badge>
                )
              ) : null}
              {brandedStatus === "finalized" ? (
                <Badge size="sm" variant="success">
                  Brandowane: gotowe
                </Badge>
              ) : brandedStatus === "draft" ? (
                <Badge size="sm" variant="info">
                  Brandowane: draft
                </Badge>
              ) : (
                <Badge size="sm" variant="neutral">
                  Brandowane: brak
                </Badge>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setOpenOriginal(true)}
                className="justify-start"
              >
                <FileText className="h-3.5 w-3.5" /> Pokaż CV oryginalne
              </Button>
              {!readOnly && (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setOpenBranded(true)}
                    className="justify-start"
                  >
                    <FileText className="h-3.5 w-3.5" />{" "}
                    {brandedStatus === "none" ? "Stwórz brandowane" : "Edytuj brandowane"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={brandedStatus !== "finalized"}
                    onClick={() => setOpenShare(true)}
                    title={
                      brandedStatus !== "finalized"
                        ? "Najpierw sfinalizuj brandowane CV"
                        : undefined
                    }
                    className="justify-start"
                  >
                    <Send className="h-3.5 w-3.5" /> Wyślij klientowi
                  </Button>
                </>
              )}
            </div>
          </div>
        )}

        {activeTab === "match" && (
          <DopasowanieTab
            candidateId={item.candidate_id}
            recruitments={[{ job_id: jobId, job_title: jobLabel }]}
            defaultJobId={jobId}
            readOnly={readOnly}
          />
        )}

        {activeTab === "notes" && (
          <div className="space-y-3">
            {!readOnly && (
              <div className="space-y-1.5">
                <textarea
                  value={noteText}
                  onChange={(e) => setNoteText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      submitNote();
                    }
                  }}
                  placeholder="Dodaj notatkę… (Enter wysyła, Shift+Enter nowa linia)"
                  rows={2}
                  className="w-full rounded-md border border-border bg-card px-3 py-2 text-xs focus:outline-hidden focus:ring-2 focus:ring-primary"
                />
                <div className="flex justify-end">
                  <Button
                    size="sm"
                    onClick={submitNote}
                    disabled={!noteText.trim() || addNoteMutation.isPending}
                    loading={addNoteMutation.isPending}
                  >
                    <Send className="h-3.5 w-3.5" />
                    Dodaj notatkę
                  </Button>
                </div>
              </div>
            )}
            {notesQuery.isLoading ? (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie…
              </div>
            ) : (notesQuery.data?.items ?? []).length > 0 ? (
              <div className="space-y-2">
                {(notesQuery.data?.items ?? []).map((n) => (
                  <div
                    key={n.id}
                    className="rounded-lg border border-border bg-muted/20 p-2.5 text-xs"
                  >
                    <div className="mb-1 flex items-center justify-between text-muted-foreground">
                      <span className="font-medium text-foreground">
                        {n.author_name ?? "Nieznany autor"}
                      </span>
                      <span>{formatDate(n.created_at)}</span>
                    </div>
                    <p className="whitespace-pre-line text-foreground">
                      {n.content_rendered ?? n.content}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Brak notatek dla tej rekrutacji.
              </p>
            )}
          </div>
        )}
      </div>

      {/* ── Przenieś na etap + akcje (zawsze widoczne, niezależnie od zakładki) ── */}
      <div className="space-y-3 border-t border-border bg-muted/10 p-4">
        {moveTargets.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-xs font-semibold text-foreground">Przenieś na etap</div>
            <div className="flex flex-wrap gap-1">
              {moveTargets.map(({ col, blockedReason }) => (
                <button
                  key={col.stage_def_id ?? col.stage}
                  type="button"
                  disabled={Boolean(blockedReason)}
                  title={blockedReason ?? undefined}
                  onClick={() => onMoveTo(col)}
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-[11px] transition-colors",
                    blockedReason
                      ? "cursor-not-allowed border-border bg-muted text-muted-foreground/60"
                      : "border-border bg-background text-foreground hover:border-primary hover:bg-primary/5"
                  )}
                >
                  {col.name ?? col.stage}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-1.5">
          <Button
            size="sm"
            variant="outline"
            onClick={() => setOpenOriginal(true)}
            className="justify-start"
          >
            <FileText className="h-3.5 w-3.5" /> Otwórz CV
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setOpenEmail(true)}
            loading={openEmail && !candidateDetailQuery.data && candidateDetailQuery.isFetching}
            className="justify-start"
          >
            <Mail className="h-3.5 w-3.5" /> Wyślij wiadomość
          </Button>
          <Link
            href={`/candidates/${item.candidate_id}?${encodeJobBackRef(jobId).toString()}`}
            className="inline-flex h-8 items-center justify-start gap-1.5 rounded-lg border border-border px-3 text-xs text-muted-foreground hover:bg-muted"
          >
            <ExternalLink className="h-3.5 w-3.5" /> Pełny profil
          </Link>
          {canReject && !readOnly && (
            <Button
              size="sm"
              variant="outline"
              onClick={onReject}
              className="justify-start text-destructive hover:bg-destructive/10 hover:text-destructive"
            >
              <Ban className="h-3.5 w-3.5" /> Odrzuć z powodem
            </Button>
          )}
        </div>
      </div>

      {openOriginal && (
        <CVOriginalPreviewModal
          open
          onOpenChange={setOpenOriginal}
          stageId={item.id}
          jobTitle={jobLabel}
          candidateName={fullName}
        />
      )}
      {!readOnly && openBranded && (
        <CVBrandedEditModal
          open
          onOpenChange={setOpenBranded}
          stageId={item.id}
          jobTitle={jobLabel}
          candidateName={fullName}
        />
      )}
      {!readOnly && openShare && (
        <CVShareLinkModal
          open
          onOpenChange={setOpenShare}
          stageId={item.id}
          candidateName={fullName}
        />
      )}
      {/* Dopiero z danymi — modal nigdy nie otwiera się z pustym adresem
          (adres nie jest na karcie kanbanu, dociągamy go leniwie wyżej). */}
      {openEmail && candidateDetailQuery.data && (
        <SendEmailV2
          open
          onOpenChange={setOpenEmail}
          candidateId={item.candidate_id}
          candidateName={fullName}
          candidateEmail={candidateDetailQuery.data.email ?? ""}
        />
      )}
    </div>
  );
}

/** Pusty stan doku — nic nie jest kliknięte na tablicy. Ten sam ton co
 *  `JobMatchDock` w warsztacie C2, żeby dwa doki tej samej rekrutacji
 *  mówiły tym samym językiem. */
export function PipelineCandidateDockEmpty() {
  return (
    <div className="rounded-xl border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
      <CheckCircle2 className="mx-auto mb-2 h-6 w-6 opacity-40" />
      Kliknij kartę na tablicy, aby zobaczyć jej etap, screening, CV i historię.
    </div>
  );
}
