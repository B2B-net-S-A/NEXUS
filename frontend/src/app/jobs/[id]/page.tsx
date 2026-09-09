"use client";

import { summarizeFullSearch, type FullSearchSummary } from "@/lib/full-search-summary";

import { useFullCandidateSearch } from "@/hooks/useFullCandidateSearch";
import { SavedRequestRequirements } from "@/components/talent-radar/SavedRequestRequirements";
import { FullCandidateSearchStatus } from "@/components/talent-radar/FullCandidateSearchStatus";
import { fullSearchJobMatches } from "@/lib/full-search-job-adapter";
import { formatMatchingRate, matchingRateBand } from "@/lib/matching-rate";
import { useEffect, useState, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { resolveViewState } from "@/lib/view-state";
import { useCapability } from "@/hooks/useCapability";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { getAvatarColor } from "@/lib/colors";
import api, {
  postingsApi,
  matchingApi,
  phase3Api,
  recommendationsApi,
  hiddenTotal as computeHiddenTotal,
  HIDDEN_LABELS_PL,
  type HiddenReason,
} from "@/lib/api";
import { KanbanBoardV2 } from "@/components/v2/pages/KanbanBoardV2";
import { EditJobModal } from "@/components/AppShell";
import { RequestHistorySection } from "@/components/RequestHistorySection";
import { AIJobWriterModal } from "@/components/v2/jobs/AIJobWriterModal";
import { SourcingHub } from "@/components/v2/jobs/SourcingHub";
import {
  countContractStages,
  countHired,
  countInProcess,
  countInterviewStages,
  selectPendingVerifications,
  selectScreeningQueue,
  selectVerifiedQueue,
} from "@/lib/pipeline-flow";
import { buildJobHeaderKpis } from "@/lib/job-header-kpis";
import { buildJobHeaderSubtitle } from "@/lib/job-header-subtitle";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import { ChampionProfileEditor } from "@/components/ChampionProfileEditor";
import { ChampionSectionNav } from "@/components/v2/jobs/ChampionSectionNav";
import { JobSummaryCard } from "@/components/v2/jobs/JobSummaryCard";
import { JobReadinessDock } from "@/components/v2/jobs/JobReadinessDock";
import { QuestionBankTab } from "@/components/prep/QuestionBankTab";
import { CriteriaPreviewV2 as CriteriaPreviewModal } from "@/components/v2/modals/CriteriaPreviewV2";
import { JobOwnershipPanel } from "@/components/v2/jobs/JobOwnershipPanel";
import JobChatTab from "@/components/v2/pages/JobChatTab";
import { jobChatApi } from "@/lib/api";
import { MapPin, Banknote, Calendar, Globe, ExternalLink, Plus, Radio, X, Copy, Check, Sparkles, UserCheck, AlertCircle, Mail, Target, ChevronRight, SlidersHorizontal } from "lucide-react";
import { DopasowanieTab } from "@/components/v2/pages/DopasowanieTab";
import { AddCandidatesQuickModal } from "@/components/v2/modals/AddCandidatesQuickModal";
import { CandidateSearchView } from "@/components/v2/pages/CandidateSearchView";
import { proposalsBulkApi, shortlistApi } from "@/lib/candidate-search-api";
import {
  JobShortlist,
  jobShortlistQueryKey,
} from "@/components/v2/jobs/JobShortlist";
import { buildJobSearchPrefill } from "@/lib/job-search-prefill";
import { GenerateInviteLinkV2 } from "@/components/v2/modals/GenerateInviteLinkV2";
import { DeleteButton } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import Link from "next/link";
import { formatDate } from "@/lib/utils";
import { encodeJobBackRef } from "@/lib/url-filters";
import { useTabsStore } from "@/store/tabs";
import { hasRole, useAuthStore } from "@/store/auth";
import { RequirementVerificationDialog, useCanVerifyRequirements } from "@/components/talent-radar/RequirementVerificationDialog";
import { hasSectionAccess } from "@/lib/section-access";
import { ActiveViewers } from "@/components/v2/presence/ActiveViewers";
import { LocationInput } from "@/components/v2/filters/LocationInput";
import { formatCandidateLocation } from "@/components/v2/pages/candidate-list-helpers";
import { HiringManagerPicker } from "@/components/jobs/HiringManagerPicker";
import { useLocalStorageFlag } from "@/lib/use-local-storage-flag";
import {
  JOB_HEADER_COLLAPSED_DEFAULT,
  JOB_HEADER_COLLAPSED_STORAGE_KEY,
} from "@/lib/job-header-preferences";
import { JobPriorityContext } from "@/components/v2/priority-work";
import { assignErrorMessage } from "@/lib/assign-error";
import {
  JobDetailCompactHeader,
  type JobDetailTab,
} from "@/components/v2/jobs/JobDetailCompactHeader";
import { JobInterviewsTab } from "@/components/v2/jobs/JobInterviewsTab";
import { JobContractTab } from "@/components/v2/jobs/JobContractTab";
import { Badge } from "@/components/ui/badge";

// ── Types ─────────────────────────────────────────────────────────────────────

type Portal = "pracuj_pl" | "justjoinit" | "linkedin" | "nofluffjobs" | "bulldogjob";
type PostingStatus = "draft" | "published" | "expired" | "removed";

interface JobPosting {
  id: number;
  job_id: number;
  portal: Portal;
  external_id: string | null;
  status: PostingStatus;
  published_at: string | null;
  expires_at: string | null;
  url: string | null;
  views: number;
  applications: number;
}

// ── Portal config ─────────────────────────────────────────────────────────────

const PORTAL_CONFIG: Record<Portal, { label: string; color: string; dotColor: string }> = {
  pracuj_pl:   { label: "Pracuj.pl",    color: "bg-orange-100 text-orange-700",  dotColor: "bg-orange-500" },
  justjoinit:  { label: "JustJoinIT",   color: "bg-green-100 text-green-700",    dotColor: "bg-green-500" },
  linkedin:    { label: "LinkedIn",     color: "bg-primary/15 text-primary",      dotColor: "bg-primary" },
  nofluffjobs: { label: "NoFluffJobs",  color: "bg-destructive/15 text-destructive",        dotColor: "bg-destructive" },
  bulldogjob:  { label: "BulldogJob",   color: "bg-yellow-100 text-yellow-700",  dotColor: "bg-yellow-500" },
};

const ALL_PORTALS: Portal[] = ["pracuj_pl", "justjoinit", "linkedin", "nofluffjobs", "bulldogjob"];

const STATUS_CONFIG: Record<PostingStatus, { label: string; className: string }> = {
  draft:     { label: "Szkic",       className: "bg-muted text-muted-foreground" },
  published: { label: "Aktywne",     className: "bg-green-100 text-green-700" },
  expired:   { label: "Wygasłe",     className: "bg-destructive/15 text-destructive" },
  removed:   { label: "Usunięte",    className: "bg-muted text-muted-foreground" },
};

// ── Publish Modal ─────────────────────────────────────────────────────────────

function PublishModal({
  jobId,
  onClose,
  existingPortals,
}: {
  jobId: number;
  onClose: () => void;
  existingPortals: Portal[];
}) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Portal[]>([]);
  const [expiresDays, setExpiresDays] = useState(30);

  const publishMutation = useMutation({
    mutationFn: (portals: Portal[]) =>
      postingsApi.publishAll(jobId, { portals, expires_days: expiresDays }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["postings", jobId] });
      queryClient.invalidateQueries({ queryKey: ["postings-stats"] });
      onClose();
    },
  });

  const toggle = (p: Portal) =>
    setSelected((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));

  const activePortals = existingPortals;

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="publish-posting-title"
        className="bg-card rounded-xl shadow-xl w-full max-w-md p-6"
      >
        <h2 id="publish-posting-title" className="text-lg font-bold mb-1">
          Opublikuj ogłoszenie
        </h2>
        <p className="text-sm text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4">
          ⚠️ Integracja z portalami w przygotowaniu — dane symulowane
        </p>

        <div className="space-y-2 mb-4">
          {ALL_PORTALS.map((p) => {
            const config = PORTAL_CONFIG[p];
            const isActive = activePortals.includes(p);
            const isSelected = selected.includes(p);
            return (
              <label
                key={p}
                className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                  isActive
                    ? "opacity-50 cursor-not-allowed border-border bg-muted"
                    : isSelected
                    ? "border-primary/30 bg-primary/10"
                    : "border-border hover:border-border"
                }`}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  disabled={isActive}
                  onChange={() => !isActive && toggle(p)}
                  className="accent-blue-600"
                />
                <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${config.dotColor}`} />
                <span className="text-sm font-medium">{config.label}</span>
                {isActive && (
                  <span className="ml-auto text-xs text-green-600 font-medium">Już aktywne</span>
                )}
              </label>
            );
          })}
        </div>

        <div className="flex items-center gap-3 mb-5">
          <label className="text-sm text-muted-foreground whitespace-nowrap">Czas trwania:</label>
          <select
            className="text-sm border border-border rounded-lg px-3 py-1.5"
            value={expiresDays}
            onChange={(e) => setExpiresDays(Number(e.target.value))}
          >
            <option value={14}>14 dni</option>
            <option value={30}>30 dni</option>
            <option value={60}>60 dni</option>
            <option value={90}>90 dni</option>
          </select>
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => onClose()}
            className="flex-1 px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted"
          >
            Anuluj
          </button>
          <button
            onClick={() => selected.length > 0 && publishMutation.mutate(selected)}
            disabled={selected.length === 0 || publishMutation.isPending}
            className="flex-1 px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {publishMutation.isPending ? "Publikowanie..." : `Publikuj (${selected.length})`}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Postings Section ──────────────────────────────────────────────────────────

function PostingsSection({
  jobId,
  readOnly = false,
}: {
  jobId: number;
  readOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);

  const { data: postings = [], isLoading } = useQuery<JobPosting[]>({
    queryKey: ["postings", jobId],
    queryFn: () => postingsApi.list(jobId).then((r) => r.data),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => postingsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["postings", jobId] });
      queryClient.invalidateQueries({ queryKey: ["postings-stats"] });
    },
  });

  const publishAllMutation = useMutation({
    mutationFn: () =>
      postingsApi.publishAll(jobId, { portals: ALL_PORTALS, expires_days: 30 }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["postings", jobId] });
      queryClient.invalidateQueries({ queryKey: ["postings-stats"] });
    },
  });

  const activePortals = postings
    .filter((p) => p.status === "published")
    .map((p) => p.portal);

  if (isLoading) return <div className="text-muted-foreground text-sm">Ładowanie publikacji...</div>;

  return (
    <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Globe className="w-5 h-5 text-primary" />
          <h2 className="text-lg font-semibold">Portale ogłoszeniowe</h2>
          <span className="text-xs text-muted-foreground ml-1">({postings.length})</span>
        </div>
        {!readOnly ? <div className="flex gap-2">
          <button
            onClick={() => publishAllMutation.mutate()}
            disabled={publishAllMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted text-muted-foreground disabled:opacity-50"
          >
            <Radio className="w-3.5 h-3.5" />
            Publikuj na wszystkich
          </button>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary text-white rounded-lg hover:bg-primary/90"
          >
            <Plus className="w-3.5 h-3.5" />
            Opublikuj ogłoszenie
          </button>
        </div> : null}
      </div>

      {/* Simulation notice */}
      <div className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4">
        ⚠️ Integracja z portalami w przygotowaniu — dane symulowane
      </div>

      {/* Table */}
      {postings.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground">
          <Globe className="w-10 h-10 mx-auto mb-2 opacity-30" />
          <p className="text-sm">
            {readOnly
              ? "Brak publikacji."
              : "Brak publikacji. Opublikuj ogłoszenie na portalach rekrutacyjnych."}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border dark:border-border">
                <th className="text-left py-2 px-3 text-muted-foreground font-medium">Portal</th>
                <th className="text-left py-2 px-3 text-muted-foreground font-medium">Status</th>
                <th className="text-left py-2 px-3 text-muted-foreground font-medium">Data publ.</th>
                <th className="text-left py-2 px-3 text-muted-foreground font-medium">Wygaśnięcie</th>
                <th className="text-right py-2 px-3 text-muted-foreground font-medium">Wyświetlenia</th>
                <th className="text-right py-2 px-3 text-muted-foreground font-medium">Aplikacje</th>
                <th className="text-center py-2 px-3 text-muted-foreground font-medium">Link</th>
                {!readOnly ? (
                  <th className="text-center py-2 px-3 text-muted-foreground font-medium">Akcje</th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {postings.map((posting) => {
                const portalCfg = PORTAL_CONFIG[posting.portal];
                const statusCfg = STATUS_CONFIG[posting.status];
                return (
                  <tr key={posting.id} className="border-b border-gray-50 hover:bg-muted">
                    <td className="py-2.5 px-3">
                      <div className="flex items-center gap-2">
                        <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${portalCfg.dotColor}`} />
                        <span className="font-medium">{portalCfg.label}</span>
                      </div>
                    </td>
                    <td className="py-2.5 px-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusCfg.className}`}>
                        {statusCfg.label}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-muted-foreground">
                      {posting.published_at ? formatDate(posting.published_at) : "—"}
                    </td>
                    <td className="py-2.5 px-3 text-muted-foreground">
                      {posting.expires_at ? formatDate(posting.expires_at) : "—"}
                    </td>
                    <td className="py-2.5 px-3 text-right font-medium">
                      {posting.views.toLocaleString()}
                    </td>
                    <td className="py-2.5 px-3 text-right font-medium text-primary">
                      {posting.applications}
                    </td>
                    <td className="py-2.5 px-3 text-center">
                      {posting.url ? (
                        <a
                          href={posting.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={`Otwórz ogłoszenie na ${portalCfg.label} w nowej karcie`}
                          className="text-primary hover:text-primary/80 inline-flex items-center gap-1"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    {!readOnly ? (
                      <td className="py-2.5 px-3 text-center">
                        <DeleteButton onConfirm={() => deleteMutation.mutate(posting.id)} />
                      </td>
                    ) : null}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Publish modal */}
      {!readOnly && showModal && (
        <PublishModal
          jobId={jobId}
          existingPortals={activePortals}
          onClose={() => setShowModal(false)}
        />
      )}
    </div>
  );
}

// ── AI Job Writer Modal ───────────────────────────────────────────────────────

// ── Phase 4: AI criteria / scoring actions ──────────────────────────────────

function JobAIActions({
  jobId,
  onDone,
  readOnly = false,
}: {
  jobId: number;
  onDone: () => void;
  readOnly?: boolean;
}) {
  const [busy, setBusy] = useState<null | "criteria" | "recompute" | "embed-all">(null);
  const [last, setLast] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  const run = async (kind: "criteria" | "recompute" | "embed-all") => {
    if (readOnly) return;
    setBusy(kind);
    setLast(null);
    try {
      if (kind === "criteria") {
        const r = await recommendationsApi.refreshCriteria(jobId);
        const d = r.data as { must_skills: unknown[]; nice_skills: unknown[] };
        setLast(
          `Kryteria odświeżone: must=${d.must_skills.length}, nice=${d.nice_skills.length}`
        );
      } else if (kind === "recompute") {
        const r = await recommendationsApi.recomputeScores(jobId, 200);
        const d = r.data as { evaluated: number };
        setLast(`Przeliczono scoring dla ${d.evaluated} kandydatów`);
      } else {
        const r = await phase3Api.embedAllJobs(500);
        const d = r.data as { requested: number; embedded: number; failed: number };
        setLast(
          `Embedding rekrutacji: requested=${d.requested}, embedded=${d.embedded}, failed=${d.failed}`
        );
      }
      onDone();
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd")
          : "Błąd";
      setLast(`Błąd: ${msg}`);
    } finally {
      setBusy(null);
    }
  };

  if (readOnly) return null;

  return (
    <div className="rounded-lg border border-dashed border-primary/30 dark:border-primary/90 bg-primary/10 dark:bg-primary/10 p-3">
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-xs font-semibold text-muted-foreground dark:text-muted-foreground mr-2">
          AI / Scoring:
        </span>
        <button
          onClick={() => setShowPreview(true)}
          disabled={!!busy}
          className="text-xs px-3 py-1.5 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          data-testid="preview-criteria"
        >
          ✨ Podgląd kryteriów (edytowalne)
        </button>
        <button
          onClick={() => run("criteria")}
          disabled={!!busy}
          className="text-xs px-3 py-1.5 rounded-md bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50"
          data-testid="refresh-criteria"
        >
          {busy === "criteria" ? "Generuję…" : "⚡ Szybkie odświeżenie"}
        </button>
        <button
          onClick={() => run("recompute")}
          disabled={!!busy}
          className="text-xs px-3 py-1.5 rounded-md bg-primary text-white hover:bg-primary/90 disabled:opacity-50"
          data-testid="recompute-scores"
        >
          {busy === "recompute" ? "Liczę…" : "🧮 Przelicz scoring"}
        </button>
        <button
          onClick={() => run("embed-all")}
          disabled={!!busy}
          className="text-xs px-3 py-1.5 rounded-md bg-slate-600 text-white hover:bg-slate-700 disabled:opacity-50"
          data-testid="embed-all-jobs"
          title="Jednorazowo: wylicza embeddingi dla wszystkich rekrutacji bez vector ID"
        >
          {busy === "embed-all" ? "Embedduję…" : "🗂 Embed all jobs"}
        </button>
      </div>
      {last && (
        <div className="mt-2 text-xs text-muted-foreground dark:text-muted-foreground">{last}</div>
      )}

      <CriteriaPreviewModal
        open={showPreview}
        onOpenChange={setShowPreview}
        jobId={jobId}
        onSaved={() => {
          setLast("Kryteria zaktualizowane. Uruchom 'Przelicz scoring' aby odświeżyć wyniki.");
          onDone();
        }}
      />
    </div>
  );
}

// ── AI Matching Section ───────────────────────────────────────────────────────

function EmailTemplateModal({
  candidate,
  job,
  onClose,
}: {
  candidate: any;
  job: any;
  onClose: () => void;
}) {
  const fullName = `${candidate.name} ${candidate.lastname}`.trim();
  // Reference number (when present) is appended to the subject and quoted in
  // the body so the candidate can cite it in replies — and so the recruiter's
  // mailbox threads on a stable identifier.
  const refSuffix = job.reference_number ? ` [${job.reference_number}]` : "";
  const refLine = job.reference_number
    ? `\n\nNumer referencyjny: ${job.reference_number}`
    : "";
  const subject = `Oferta pracy: ${job.title}${refSuffix}`;
  const body = `Dzień dobry ${candidate.name},\n\nZwracam się do Pana/Pani w imieniu B2B.net S.A. z ofertą stanowiska:\n\n**${job.title}**${refLine}\n\nNa podstawie Pana/Pani profilu uważam, że ta rola idealnie odpowiada Pana/Pani kompetencjom.\n\nCzy byłby Pan/Pani zainteresowany/a rozmową wstępną?\n\nPozdrawiam,\nZespół Rekrutacji B2B.net`;

  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(`Temat: ${subject}\n\n${body}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const mailtoLink = `mailto:${candidate.email || ""}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-card dark:bg-muted rounded-xl shadow-xl w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-bold text-foreground dark:text-foreground">Wyślij wiadomość do {fullName}</h3>
          <button onClick={onClose}><X className="w-5 h-5 text-muted-foreground" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-xs font-semibold text-muted-foreground uppercase">Temat</label>
            <p className="text-sm mt-1 p-2 bg-muted dark:bg-muted rounded">{subject}</p>
          </div>
          <div>
            <label className="text-xs font-semibold text-muted-foreground uppercase">Treść</label>
            <pre className="text-sm mt-1 p-3 bg-muted dark:bg-muted rounded whitespace-pre-wrap font-sans">{body}</pre>
          </div>
          <div className="flex gap-2 pt-2">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-3 py-2 text-sm border border-border rounded-lg hover:bg-muted"
            >
              {copied ? <><Check className="w-4 h-4 text-green-500" /> Skopiowano</> : <><Copy className="w-4 h-4" /> Kopiuj</>}
            </button>
            {candidate.email && (
              <a
                href={mailtoLink}
                className="flex items-center gap-1.5 px-3 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary/90"
              >
                <Mail className="w-4 h-4" />
                Otwórz w kliencie email
              </a>
            )}
            <button onClick={onClose} className="ml-auto px-3 py-2 text-sm text-muted-foreground hover:text-foreground">
              Zamknij
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function AIMatchingSection({
  jobId,
  job,
  readOnly = false,
  isAdmin = false,
}: {
  jobId: number;
  job: any;
  readOnly?: boolean;
  isAdmin?: boolean;
}) {
  const canEditRequirements = useCapability("job.update") && !readOnly;
  const canVerify = useCanVerifyRequirements() && !readOnly;
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [emailTarget, setEmailTarget] = useState<any>(null);
  // Przełącznik dwóch stanów tego samego ekranu (makieta C2): „Ranking"
  // (szukam) ↔ „Shortlista" (oceniam i prowadzę).
  const [matchView, setMatchView] = useState<"ranking" | "shortlist">("ranking");
  const [shortlistingId, setShortlistingId] = useState<number | null>(null);
  // Wiersz zaznaczony do doku „Dopasowanie" (prawa kolumna warsztatu C2).
  const [selectedId, setSelectedId] = useState<number | null>(null);
  // Filtry lewej kolumny „Wymagania z Championa" — wszystkie po stronie klienta,
  // bez dodatkowego zapytania: próg wyniku, wybrany skill must, stawka wobec
  // budżetu, obecność w procesie. Multi-select do akcji zbiorczej „Przypisz".
  const [minScorePct, setMinScorePct] = useState<number | null>(null);
  const [skillFilter, setSkillFilter] = useState<string | null>(null);
  const [rateFilter, setRateFilter] = useState<"all" | "in" | "over" | "unknown">(
    "all",
  );
  const [stageFilter, setStageFilter] = useState<"all" | "in" | "out">("all");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  // Licznik do etykiety przełącznika — ten sam klucz co tablica shortlisty,
  // więc react-query deduplikuje fetch.
  const shortlistCountQuery = useQuery({
    queryKey: jobShortlistQueryKey(jobId),
    queryFn: () => shortlistApi.list(jobId),
    staleTime: 30_000,
  });
  const shortlistCount = shortlistCountQuery.data?.length ?? 0;
  // Optional result filter; job location remains a scoring input, not an implicit exclusion.
  const [locationFilter, setLocationFilter] = useState("");
  // Lista matchy nie odświeża się po dodaniu, więc trzymamy lokalny set już
  // dodanych — wyszarza przycisk i blokuje przypadkowe duplikaty.
  const [addedIds, setAddedIds] = useState<Set<number>>(new Set());
  const [addingId, setAddingId] = useState<number | null>(null);

  const actorId = useAuthStore(s => s.user?.id);
  const fullSearch = useFullCandidateSearch({
    includeCandidateDetails: true,
    storageKey: actorId ? `nexus-full-job:${actorId}:${jobId}` : undefined,
    filters: { skill: skillFilter ?? undefined, rate: rateFilter, stage: stageFilter, location: locationFilter.trim() },
  });
  const data = useMemo(() => fullSearchJobMatches(fullSearch.data, jobId, locationFilter.trim(), minScorePct ?? 0), [fullSearch.data, jobId, locationFilter, minScorePct]);
  const searchSummary = useMemo(() => summarizeFullSearch(fullSearch.data, Boolean(fullSearch.error)), [fullSearch.data, fullSearch.error]);
  const isLoading = fullSearch.running;
  const isError = Boolean(fullSearch.error);
  const refetch = () => fullSearch.start({ job_id: jobId });
  useEffect(() => { fullSearch.setMinScore(minScorePct ?? 0); }, [minScorePct, fullSearch.setMinScore]);
  useEffect(() => {
    queryClient.setQueryData(["full-search-summary", actorId, jobId], searchSummary);
  }, [searchSummary, actorId, jobId, queryClient]);

  // Wspólny kanon z sekcją „Kandydaci z podobnych projektów": bulk-proposals
  // dedupuje (już-w-pipeline → total_added=0) i wybiera pierwszy nie-terminalny
  // etap. Wcześniej legacy wysyłał `pipeline/move` ze `stage:"sourced"` (spoza
  // enum PipelineStage) → 422 i cichy fail.
  const addToPipelineMutation = useMutation({
    mutationFn: ({ candidateId }: { candidateId: number; fullName: string }) => {
      if (readOnly) {
        throw new Error("Sekcja Pipeline jest dostępna tylko do odczytu.");
      }
      return proposalsBulkApi.add(jobId, { candidate_ids: [candidateId] });
    },
    onMutate: ({ candidateId }) => setAddingId(candidateId),
    onSuccess: (res, { candidateId, fullName }) => {
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      // Newly-added candidate needs its AI score ring (prefix match → any id key).
      queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
      setAddedIds((prev) => new Set(prev).add(candidateId));
      showSuccess(
        res.total_added > 0
          ? `${fullName} — dodano do pipeline`
          : `${fullName} jest już w pipeline tej rekrutacji`,
      );
    },
    onError: (error: unknown) => showError(assignErrorMessage(error)),
    onSettled: () => setAddingId(null),
  });

  // Staged evaluation przed pipeline (kanon z SuggestedCandidatesWidget):
  // dodanie na shortlistę, nie od razu do pipeline'u.
  const shortlistMutation = useMutation({
    mutationFn: ({ candidateId }: { candidateId: number; fullName: string }) => {
      if (readOnly) {
        throw new Error("Shortlista jest dostępna tylko do odczytu.");
      }
      return shortlistApi.add(jobId, [candidateId]);
    },
    onMutate: ({ candidateId }) => setShortlistingId(candidateId),
    onSuccess: (res, { fullName }) => {
      queryClient.invalidateQueries({ queryKey: jobShortlistQueryKey(jobId) });
      showSuccess(
        res.total_added > 0
          ? `${fullName} — dodano na shortlistę`
          : `${fullName} jest już na shortliście`,
      );
    },
    onError: (error: unknown) => showError(assignErrorMessage(error)),
    onSettled: () => setShortlistingId(null),
  });

  // Akcja zbiorcza „Przypisz zaznaczonych" (checkboxy w rankingu → pipeline).
  const bulkAssignMutation = useMutation({
    mutationFn: (ids: number[]) => {
      if (readOnly) {
        throw new Error("Sekcja Pipeline jest dostępna tylko do odczytu.");
      }
      return proposalsBulkApi.add(jobId, { candidate_ids: ids });
    },
    onSuccess: (res, ids) => {
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
      setAddedIds((prev) => {
        const next = new Set(prev);
        ids.forEach((i) => next.add(i));
        return next;
      });
      setSelectedIds(new Set());
      showSuccess(
        res.total_added > 0
          ? `Dodano ${res.total_added} do pipeline`
          : "Zaznaczeni są już w pipeline tej rekrutacji",
      );
    },
    onError: (error: unknown) => showError(assignErrorMessage(error)),
  });

  // Członkostwo procesu nie zależy od dostępności pomiaru AI.
  const pipelineScoresQuery = useQuery({
    queryKey: ["pipeline-scores", jobId],
    queryFn: () => matchingApi.pipelineScores(jobId).then((r) => r.data),
    staleTime: 60_000,
  });
  const pipelineSet = useMemo(() => {
    return new Set<number>(pipelineScoresQuery.data?.pipeline_candidate_ids ?? []);
  }, [pipelineScoresQuery.data]);

  const matches = useMemo(() => data?.matches ?? [], [data]);
  const searchType = data?.search_type;
  // Sygnałem degradacji jest koperta `meta` — `/api/jobs/{id}/ai-matches`
  // wypełnia ją na OBU gałęziach (semantycznej i tag-fallback). Warunek na
  // `search_type` jest awaryjny: odpowiedź bez `meta` (starszy backend, wpis
  // z cache'u) nie może wyrenderować się jako zdrowy ranking, bo BRAK sygnału
  // jest nieodróżnialny od sygnału „wszystko w porządku". Jedyne wartości
  // uznane za zdrowe to rodzina „semantic*" (`semantic`, `semantic+rerank`).
  const degraded =
    data?.meta?.degraded === true ||
    (searchType != null && !searchType.startsWith("semantic") && searchType !== "full_population");
  // `semantic_unavailable` (padł Qdrant/Voyage) vs `no_semantic_hits`
  // (rekrutacja nie ma jeszcze trafień w indeksie) — dla rekrutera to dwie
  // różne instrukcje, więc nie zlewamy ich w jeden komunikat.
  const degradedReason = data?.meta?.reason;
  const requiredSkills = data?.required_skills ?? [];
  // Server echoes the effective location filter it applied (param, or the
  // job's own location). Non-empty → results are location-restricted.
  const locationActive = Boolean(data?.location_filter);
  // Dealbreaker-switche: liczniki ukrytych per powód. „Ukrywanie nigdy nie jest
  // ciche" (dealbreaker_filters) — pokazujemy pasek z rozbiciem. Bramka
  // dopuszczalności NIE trafia tu: `warn` są widoczni z powodem na wierszu,
  // a `hidden` (globalna blacklista) świadomie nie są liczeni (wyrocznia NDA).
  const hiddenMeta = data?.meta?.hidden;
  const hiddenTotal = computeHiddenTotal(hiddenMeta);
  // Rozbicie „ukryto N" per powód (0278: pięć rubryk) — jedno zdanie,
  // renderowane tylko z powodami, które faktycznie coś ukryły.
  const hiddenBreakdown = (
    Object.entries(HIDDEN_LABELS_PL) as [HiddenReason, string][]
  )
    .filter(([reason]) => (hiddenMeta?.[reason] ?? 0) > 0)
    .map(([reason, label]) => `${label}: ${hiddenMeta?.[reason]}`)
    .join(", ");
  const niceSkills: string[] = data?.nice_skills ?? [];
  const budgetHourly = data?.meta?.budget_hourly ?? null;

  // Same default threshold as Radar; unknown measurements stay in the result.
  const baseThresholdPct = 0;
  const effThresholdPct = minScorePct ?? baseThresholdPct;

  // All search filters run against the complete snapshot before LIMIT/OFFSET.
  const filtered = matches;
  const strongCount = searchSummary?.strong;
  const inProcessCount = pipelineSet.size;

  // Zaznaczenie do doku liczy się WZGLĘDEM widocznej listy: kandydat
  // odfiltrowany nie może zostać w doku bez podświetlonego wiersza (review
  // #1380). Gdy zaznaczony wypadł z filtra, dok pokazuje pierwszy widoczny.
  const effSelectedId: number | null = useMemo(() => {
    if (
      selectedId != null &&
      filtered.some((m: any) => m.candidate?.id === selectedId)
    ) {
      return selectedId;
    }
    return filtered[0]?.candidate?.id ?? null;
  }, [selectedId, filtered]);
  const selectedMatch =
    effSelectedId != null
      ? (filtered.find((m: any) => m.candidate?.id === effSelectedId) ?? null)
      : null;
  // Akcja zbiorcza działa TYLKO na zaznaczonych widocznych po filtrach —
  // zaznaczony, a potem odfiltrowany kandydat nie może trafić do pipeline'u
  // po cichu (review #1380). Samo zaznaczenie zostaje: cofnięcie filtra
  // przywraca je bez ponownego klikania.
  const visibleSelectedIds = useMemo(() => {
    const visible = new Set(filtered.map((m: any) => m.candidate?.id));
    return Array.from(selectedIds).filter((id) => visible.has(id));
  }, [selectedIds, filtered]);
  const ownerName: string | null =
    job?.primary_owner?.full_name ??
    job?.primary_owner?.name ??
    job?.primary_owner?.email ??
    null;

  return (
    <div className="space-y-4">
      <SavedRequestRequirements jobId={jobId} canEdit={canEditRequirements} onSaved={fullSearch.clear} />
      {/* Pasek kontekstu rekrutacji (makieta C2 „jobbar") — tytuł, klient,
          budżet kandydacki, deadline, właściciel + KPI + przełącznik. */}
      <div className="rounded-xl border border-border bg-card p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Target className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <span className="font-semibold text-foreground">
                  {job?.title ?? "Rekrutacja"}
                </span>
                {job?.client_name && (
                  <span className="text-sm text-muted-foreground">
                    · {job.client_name}
                  </span>
                )}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                {formatCandidateLocation(job?.location) && (
                  <span className="inline-flex items-center gap-1">
                    <MapPin className="h-3 w-3" />
                    {formatCandidateLocation(job?.location)}
                  </span>
                )}
                <span className="inline-flex items-center gap-1">
                  <Banknote className="h-3 w-3" />
                  {budgetHourly != null
                    ? `budżet do ${Math.round(budgetHourly)} PLN/h`
                    : job?.salary_min || job?.salary_max
                      ? `${job?.salary_min?.toLocaleString() ?? "?"}–${job?.salary_max?.toLocaleString() ?? "?"} PLN`
                      : "budżet nieokreślony"}
                </span>
                {job?.deadline && (
                  <span className="inline-flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    {formatDate(job.deadline)}
                  </span>
                )}
                {ownerName && (
                  <span className="inline-flex items-center gap-1">
                    <UserCheck className="h-3 w-3" />
                    {ownerName}
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-4 text-center">
              <div>
                <div className="text-base font-bold tabular-nums text-foreground">
                  {searchSummary?.total ?? "—"}
                </div>
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  w rankingu
                </div>
              </div>
              <div>
                <div className="text-base font-bold tabular-nums text-success">
                  {strongCount ?? "—"}
                </div>
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  ≥ 75 pkt
                </div>
              </div>
              <div>
                <div className="text-base font-bold tabular-nums text-foreground">
                  {inProcessCount}
                </div>
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  w procesie
                </div>
              </div>
            </div>

            {/* Przełącznik Ranking / Shortlista (makieta C2) */}
            <div className="inline-flex rounded-lg border border-border bg-background p-0.5 text-sm">
              <button
                type="button"
                onClick={() => setMatchView("ranking")}
                className={
                  "px-3 py-1 rounded-md transition-colors " +
                  (matchView === "ranking"
                    ? "bg-primary text-primary-foreground font-medium"
                    : "text-muted-foreground hover:bg-accent")
                }
              >
                Ranking
              </button>
              <button
                type="button"
                onClick={() => setMatchView("shortlist")}
                className={
                  "px-3 py-1 rounded-md transition-colors inline-flex items-center gap-1.5 " +
                  (matchView === "shortlist"
                    ? "bg-primary text-primary-foreground font-medium"
                    : "text-muted-foreground hover:bg-accent")
                }
              >
                Shortlista
                {shortlistCount > 0 && (
                  <span
                    className={
                      "rounded-full px-1.5 text-[11px] tabular-nums " +
                      (matchView === "shortlist"
                        ? "bg-primary-foreground/20"
                        : "bg-muted text-muted-foreground")
                    }
                  >
                    {shortlistCount}
                  </span>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {matchView === "shortlist" && (
        <JobShortlist jobId={jobId} readOnly={readOnly} />
      )}

      {matchView === "ranking" && (
        <>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_360px]">
        {/* ── Lewa kolumna: Wymagania z Championa + filtry ─────────── */}
        <aside className="space-y-4 self-start rounded-xl border border-border bg-card p-4">
          <div className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
            <Target className="h-4 w-4 text-primary" />
            Wymagania
            <span className="ml-auto text-[10px] font-normal uppercase tracking-wide text-muted-foreground">
              z Championa
            </span>
          </div>

          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">
              Musi mieć · {requiredSkills.length}
            </div>
            {requiredSkills.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {requiredSkills.map((s: string) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setSkillFilter(skillFilter === s ? null : s)}
                    title={
                      skillFilter === s
                        ? "Kliknij, aby zdjąć filtr"
                        : "Filtruj ranking po tym wymaganiu"
                    }
                    className={
                      "rounded-full border px-2 py-0.5 text-[11px] transition-colors " +
                      (skillFilter === s
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-background text-foreground hover:bg-accent")
                    }
                  >
                    {s}
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-[11px] text-muted-foreground">
                Brak — uzupełnij profil Championa lub wymagania rekrutacji.
              </p>
            )}
          </div>

          {niceSkills.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[11px] font-medium text-muted-foreground">
                Mile widziane · {niceSkills.length}
              </div>
              <div className="flex flex-wrap gap-1">
                {niceSkills.map((s) => (
                  <span
                    key={s}
                    className="rounded-full border border-dashed border-border bg-background px-2 py-0.5 text-[11px] text-muted-foreground"
                  >
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="border-t border-border" />

          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[11px] font-medium text-muted-foreground">
              <span>Próg dopasowania</span>
              <span className="tabular-nums text-foreground">≥ {effThresholdPct}</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={effThresholdPct}
              onChange={(e) => setMinScorePct(Number(e.target.value))}
              className="w-full accent-primary"
              aria-label="Próg dopasowania"
            />
          </div>

          <div className="border-t border-border" />

          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">
              Stawka wobec budżetu
            </div>
            <div className="flex flex-wrap gap-1">
              {(
                [
                  ["all", "Wszystkie"],
                  ["in", "Mieści się"],
                  ["over", "Powyżej"],
                  ["unknown", "Brak danych"],
                ] as const
              ).map(([val, label]) => (
                <button
                  key={val}
                  type="button"
                  onClick={() => setRateFilter(val)}
                  className={
                    "rounded-full border px-2 py-0.5 text-[11px] transition-colors " +
                    (rateFilter === val
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-background text-foreground hover:bg-accent")
                  }
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">
              Etap w tej rekrutacji
            </div>
            <div className="flex flex-wrap gap-1">
              {(
                [
                  ["all", "Wszyscy"],
                  ["out", "Poza procesem"],
                  ["in", "W procesie"],
                ] as const
              ).map(([val, label]) => (
                <button
                  key={val}
                  type="button"
                  onClick={() => setStageFilter(val)}
                  className={
                    "rounded-full border px-2 py-0.5 text-[11px] transition-colors " +
                    (stageFilter === val
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-background text-foreground hover:bg-accent")
                  }
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {(skillFilter ||
            rateFilter !== "all" ||
            stageFilter !== "all" ||
            minScorePct != null) && (
            <button
              type="button"
              onClick={() => {
                setSkillFilter(null);
                setRateFilter("all");
                setStageFilter("all");
                setMinScorePct(null);
              }}
              className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
            >
              <X className="h-3 w-3" /> Wyczyść filtry
            </button>
          )}
        </aside>

        {/* ── Środek: ranking ──────────────────────────────────────── */}
        <div className="min-w-0 space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="whitespace-nowrap text-sm text-muted-foreground">
                {isLoading ? (
                  "Wyszukiwanie..."
                ) : (
                  <>
                    Ranking · <strong>{fullSearch.data?.total_after_threshold ?? "—"}</strong>
                    {fullSearch.data && ` · na stronie: ${matches.length}`}
                  </>
                )}
              </span>
              {/* Licznik warstwy `hidden` — mirror Talent Radaru. Po decyzji
                  „pokaż wiersze" (2026-09) bramka pokazuje warn (NDA / konflikt /
                  weto) jako wiersze z powodem, więc TU liczą się już tylko
                  realnie ukryci: globalna blacklista i duplikaty. */}
              {!isLoading && (data?.meta?.eligibility_filtered ?? 0) > 0 && (
                <span
                  className="rounded-full border border-warning/25 bg-warning-muted px-2 py-0.5 text-[11px] font-medium text-warning-muted-foreground"
                  title="Globalna blacklista lub kandydat już w tej rekrutacji"
                  data-testid="ai-matches-eligibility-filtered"
                >
                  {data!.meta!.eligibility_filtered} pominięto (globalna blacklista
                  / już w rekrutacji)
                </span>
              )}
              {searchType?.startsWith("semantic") && (
                <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-medium text-primary">
                  Semantic AI
                </span>
              )}
              {degraded && (
                <span className="rounded-full border border-warning/25 bg-warning-muted px-2 py-0.5 text-[10px] font-medium text-warning-muted-foreground">
                  Tryb awaryjny · bez rankingu AI
                </span>
              )}
              {locationActive && (
                <span className="inline-flex items-center gap-1 rounded-full bg-success-muted px-2 py-0.5 text-[10px] font-medium text-success-muted-foreground">
                  <MapPin className="h-3 w-3" /> {data?.location_filter}
                </span>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <div className="w-48">
                <LocationInput
                  value={locationFilter}
                  onChange={setLocationFilter}
                  placeholder="Lokalizacja (np. Warszawa)"
                />
              </div>
              <button
                onClick={() => refetch()}
                disabled={fullSearch.running}
                className="whitespace-nowrap text-xs text-primary hover:underline disabled:opacity-50"
              >
                {fullSearch.runId ? "Uruchom ponownie" : "Szukaj w całej bazie"}
              </button>
            </div>
          </div>

          {!isError && fullSearch.data && <FullCandidateSearchStatus data={fullSearch.data} offset={fullSearch.offset} onPage={fullSearch.setOffset} fetching={fullSearch.fetching} />}

          {degraded && (
            <div
              role="status"
              className="rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
            >
              {degradedReason === "no_semantic_hits"
                ? "Ta rekrutacja nie ma jeszcze trafień w indeksie semantycznym."
                : "Wyszukiwanie semantyczne jest chwilowo niedostępne."}{" "}
              Lista poniżej to ranking zastępczy po pokryciu wymaganych
              umiejętności i kompletności profilu — to NIE jest wynik dopasowania
              AI. Zweryfikuj profile przed wysłaniem do klienta.
            </div>
          )}

          {!isLoading && !isError && hiddenTotal > 0 && (
            <div
              role="status"
              className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
            >
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
              <span>
                Ukryto <strong>{hiddenTotal}</strong>
                {hiddenBreakdown ? `: ${hiddenBreakdown}` : ""}.
              </span>
              <span className="text-muted-foreground">
                Sufit budżetu jest twardy (decyzja produktowa) — nieznana stawka
                zawsze przechodzi.
              </span>
            </div>
          )}

          {!readOnly && visibleSelectedIds.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm">
              <span>
                Zaznaczono <strong>{visibleSelectedIds.length}</strong>
                {selectedIds.size > visibleSelectedIds.length
                  ? ` (+${selectedIds.size - visibleSelectedIds.length} poza filtrem)`
                  : ""}
              </span>
              <button
                onClick={() => bulkAssignMutation.mutate(visibleSelectedIds)}
                disabled={bulkAssignMutation.isPending}
                className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                <Plus className="h-3 w-3" />
                {bulkAssignMutation.isPending
                  ? "Dodaję…"
                  : "Przypisz do rekrutacji"}
              </button>
              <button
                onClick={() => setSelectedIds(new Set())}
                className="text-xs text-muted-foreground hover:underline"
              >
                Wyczyść
              </button>
            </div>
          )}

          {isLoading ? (
            <div className="flex flex-col items-center gap-3 py-16 text-muted-foreground">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <p className="text-sm">Wyszukiwanie pasujących kandydatów...</p>
            </div>
          ) : isError ? (
            <div className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
              <AlertCircle className="h-10 w-10 text-red-400" />
              <p className="text-sm">Błąd podczas wyszukiwania kandydatów</p>
              <button
                onClick={() => refetch()}
                className="mt-1 text-sm text-primary hover:underline"
              >
                Spróbuj ponownie
              </button>
            </div>
          ) : matches.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
              <UserCheck className="h-12 w-12 opacity-30" />
              <p className="text-sm">
                {locationActive
                  ? `Brak pasujących kandydatów w lokalizacji „${data?.location_filter}"`
                  : !fullSearch.runId ? "Uruchom wyszukiwanie w całej bazie" : "Brak dostępnych wyników na tej stronie"}
              </p>
              <p className="text-xs text-muted-foreground">
                {locationActive
                  ? "Zmień lub wyczyść filtr lokalizacji powyżej"
                  : "Wyszukiwanie korzysta z tych samych kryteriów i punktacji co Talent Radar."}
              </p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
              <SlidersHorizontal className="h-10 w-10 opacity-30" />
              <p className="text-sm">Filtry nie przepuściły żadnego kandydata</p>
              <button
                onClick={() => {
                  setSkillFilter(null);
                  setRateFilter("all");
                  setStageFilter("all");
                  setMinScorePct(null);
                }}
                className="mt-1 text-sm text-primary hover:underline"
              >
                Wyczyść filtry
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              {filtered.map((match: any, idx: number) => {
                const c = match.candidate;
                const fullName = `${c.name} ${c.lastname}`.trim();
                const initials = fullName
                  .split(" ")
                  .map((w: string) => w[0])
                  .slice(0, 2)
                  .join("")
                  .toUpperCase();
                const avatarColor = getAvatarColor(fullName);
                const elig = match.eligibility as
                  | { reason: string; assignment_allowed: boolean; severity: string }
                  | null
                  | undefined;
                const assignBlocked = elig?.assignment_allowed === false;
                const pct =
                  match.match_score == null
                    ? null
                    : Math.round(match.match_score * 100);
                const mustTotal = requiredSkills.length;
                const mustHit = (match.matching_skills ?? []).length;
                const rate = c.expected_rate_hourly as number | null | undefined;
                const rateBand = matchingRateBand(match.rate_fit);
                const officeFit = match.office_fit;
                const officeFitLabel =
                  officeFit === "days_exceeded"
                    ? "za mało dni w biurze"
                    : officeFit === "city_mismatch"
                      ? "inne miasto niż biuro"
                      : null;
                const inPipe = pipelineSet.has(c.id);
                const roleLine =
                  [c.current_title, c.current_company]
                    .filter(Boolean)
                    .join(" · ") ||
                  c.competence_category ||
                  "—";
                const city = formatCandidateLocation(c.location);
                const checked = selectedIds.has(c.id);
                const isSel = effSelectedId === c.id;
                const scoreColor =
                  pct == null
                    ? "bg-muted text-muted-foreground"
                    : pct >= 80
                      ? "bg-success-muted text-success-muted-foreground"
                      : pct >= 60
                        ? "bg-warning-muted text-warning-muted-foreground"
                        : "bg-muted text-muted-foreground";

                return (
                  <div
                    key={c.id}
                    onClick={() => setSelectedId(c.id)}
                    className={
                      "flex cursor-pointer items-center gap-3 rounded-xl border p-3 transition-shadow hover:shadow-xs " +
                      (assignBlocked
                        ? "border-destructive/30 bg-destructive/5 "
                        : "border-border bg-card dark:bg-muted ") +
                      (isSel ? "ring-2 ring-primary ring-offset-1 ring-offset-background" : "")
                    }
                  >
                    {!readOnly && (
                      <input
                        type="checkbox"
                        checked={checked}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => {
                          e.stopPropagation();
                          setSelectedIds((prev) => {
                            const next = new Set(prev);
                            if (next.has(c.id)) next.delete(c.id);
                            else next.add(c.id);
                            return next;
                          });
                        }}
                        disabled={assignBlocked}
                        className="h-4 w-4 shrink-0 accent-primary disabled:opacity-40"
                        aria-label={`Zaznacz ${fullName}`}
                      />
                    )}
                    <span className="w-5 shrink-0 text-center text-xs font-bold tabular-nums text-muted-foreground">
                      {idx + 1}
                    </span>
                    <div
                      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white ${avatarColor}`}
                    >
                      {initials || "?"}
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-foreground">
                            {fullName}
                          </div>
                          <div className="truncate text-xs text-muted-foreground">
                            {roleLine}
                            {city ? ` · ${city}` : ""}
                          </div>
                        </div>
                        <span
                          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-bold tabular-nums ${scoreColor}`}
                          title={pct == null ? "Ocena niepełna" : "Wynik dopasowania (0–100)"}
                        >
                          {pct == null ? "Ocena niepełna" : pct}
                        </span>
                      </div>

                      {canVerify && <div className="mt-2"><RequirementVerificationDialog jobId={jobId} candidateId={c.id} candidateName={fullName} onSaved={() => { void fullSearch.refresh(); }} /></div>}
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
                        {mustTotal > 0 && (
                          <span
                            className="inline-flex items-center gap-1 text-muted-foreground"
                            title={`Pokrycie wymagań must: ${mustHit} z ${mustTotal}`}
                          >
                            <span className="inline-flex gap-0.5">
                              {Array.from({ length: Math.min(mustTotal, 6) }).map(
                                (_, i) => (
                                  <span
                                    key={i}
                                    className={
                                      "h-1.5 w-2 rounded-sm " +
                                      (i < mustHit
                                        ? "bg-success"
                                        : "bg-muted-foreground/25")
                                    }
                                  />
                                ),
                              )}
                            </span>
                            {mustHit}/{mustTotal} must
                          </span>
                        )}
                        {rate != null && (
                          <span
                            className={
                              "font-medium tabular-nums " +
                              (rateBand === "over"
                                ? "text-destructive"
                                : rateBand === "in"
                                  ? "text-success"
                                  : "text-muted-foreground")
                            }
                            title={
                              budgetHourly != null
                                ? `Budżet do ${Math.round(budgetHourly)} PLN/h`
                                : "Brak budżetu oferty do porównania"
                            }
                          >
                            {formatMatchingRate(c)}
                          </span>
                        )}
                        {officeFitLabel && (
                          <span
                            className="font-medium text-destructive"
                            title="Rubryka biura (0278): deklaracja kandydata nie pokrywa wymogu oferty"
                          >
                            {officeFitLabel}
                          </span>
                        )}
                        {inPipe && (
                          <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-primary">
                            w procesie
                          </span>
                        )}
                        {elig && (
                          <span
                            className={
                              "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 font-medium " +
                              (assignBlocked
                                ? "border border-destructive/30 bg-destructive/10 text-destructive"
                                : "border border-warning/25 bg-warning-muted text-warning-muted-foreground")
                            }
                            title={elig.reason}
                          >
                            <AlertCircle className="h-3 w-3 shrink-0" />
                            {elig.reason}
                          </span>
                        )}
                      </div>
                    </div>

                    <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                  </div>
                );
              })}
            </div>
          )}

          {/* Narzędzia diagnostyczne AI — tylko admin (dawna sekcja „legacy"). */}
          {isAdmin && !readOnly && (
            <details className="rounded-lg border border-dashed border-border bg-muted/30 p-2 text-xs">
              <summary className="cursor-pointer select-none text-muted-foreground">
                Narzędzia AI (admin) — kryteria, scoring, embedding
              </summary>
              <div className="pt-2">
                <JobAIActions
                  jobId={jobId}
                  onDone={() => refetch()}
                  readOnly={readOnly}
                />
              </div>
            </details>
          )}
        </div>

        {/* ── Prawy dok: Dopasowanie ───────────────────────────────── */}
        <aside className="lg:col-span-2 xl:col-span-1 xl:sticky xl:top-4 xl:self-start">
          <JobMatchDock
            match={selectedMatch}
            jobId={jobId}
            jobTitle={job?.title ?? null}
            budgetHourly={budgetHourly}
            requiredSkills={requiredSkills}
            niceSkills={niceSkills}
            inPipeline={
              selectedMatch?.candidate
                ? pipelineSet.has(selectedMatch.candidate.id)
                : false
            }
            readOnly={readOnly}
            added={addedIds}
            addingId={addingId}
            shortlistingId={shortlistingId}
            onAddPipeline={(cid, name) =>
              addToPipelineMutation.mutate({ candidateId: cid, fullName: name })
            }
            onShortlist={(cid, name) =>
              shortlistMutation.mutate({ candidateId: cid, fullName: name })
            }
            onEmail={(cand) => setEmailTarget(cand)}
            onClose={() => setSelectedId(null)}
          />
        </aside>
      </div>
        </>
      )}

      {/* Email modal */}
      {!readOnly && emailTarget && (
        <EmailTemplateModal
          candidate={emailTarget}
          job={job}
          onClose={() => setEmailTarget(null)}
        />
      )}
    </div>
  );
}

// ── Dok „Dopasowanie" (prawa kolumna warsztatu C2) ───────────────────────────

// Wiersz pokrycia wymagania (✓/✗ + tag must/nice) w doku.
function CoverageRow({
  label,
  tag,
  hit = false,
}: {
  label: string;
  tag: "must" | "nice";
  hit?: boolean;
}) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span
        className={
          "flex h-4 w-4 shrink-0 items-center justify-center rounded-full " +
          (hit
            ? "bg-success-muted text-success-muted-foreground"
            : "bg-destructive/10 text-destructive")
        }
      >
        {hit ? <Check className="h-2.5 w-2.5" /> : <X className="h-2.5 w-2.5" />}
      </span>
      <span className={hit ? "text-foreground" : "text-muted-foreground"}>
        {label}
      </span>
      <span
        className={
          "ml-auto rounded px-1 py-0.5 text-[10px] " +
          (tag === "must"
            ? "bg-primary/10 text-primary"
            : "bg-muted text-muted-foreground")
        }
      >
        {tag}
      </span>
    </div>
  );
}

function JobMatchDock({
  match,
  jobId,
  jobTitle,
  budgetHourly,
  requiredSkills,
  niceSkills,
  inPipeline,
  readOnly,
  added,
  addingId,
  shortlistingId,
  onAddPipeline,
  onShortlist,
  onEmail,
  onClose,
}: {
  match: any | null;
  jobId: number;
  jobTitle: string | null;
  budgetHourly: number | null;
  requiredSkills: string[];
  niceSkills: string[];
  inPipeline: boolean;
  readOnly: boolean;
  added: Set<number>;
  addingId: number | null;
  shortlistingId: number | null;
  onAddPipeline: (candidateId: number, fullName: string) => void;
  onShortlist: (candidateId: number, fullName: string) => void;
  onEmail: (candidate: any) => void;
  onClose: () => void;
}) {
  const [showJustification, setShowJustification] = useState(false);
  const candidateId: number | null = match?.candidate?.id ?? null;
  // Zwiń pełne uzasadnienie AI przy zmianie zaznaczonego kandydata — drogi LLM
  // liczy się dopiero po jawnym rozwinięciu.
  useEffect(() => {
    setShowJustification(false);
  }, [candidateId]);

  if (!match) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
        <Sparkles className="mx-auto mb-2 h-6 w-6 opacity-40" />
        Wybierz kandydata z rankingu, aby zobaczyć rozbiór dopasowania.
      </div>
    );
  }

  const c = match.candidate;
  const fullName = `${c.name} ${c.lastname}`.trim();
  const pct = match.match_score == null ? null : Math.round(match.match_score * 100);
  const elig = match.eligibility as
    | { reason: string; assignment_allowed: boolean }
    | null
    | undefined;
  const assignBlocked = elig?.assignment_allowed === false;
  const isAdded = added.has(c.id);
  const rate = c.expected_rate_hourly as number | null | undefined;
  const rateBand = matchingRateBand(match.rate_fit);
  const officeFit = match.office_fit;
  const officeFitLabel =
    officeFit === "days_exceeded"
      ? "za mało dni w biurze"
      : officeFit === "city_mismatch"
        ? "inne miasto niż biuro"
        : officeFit === "ok"
          ? "spełnia wymóg biura"
          : null;
  const mustMatching: string[] = match.matching_skills ?? [];
  const mustGaps: string[] = match.gaps ?? [];
  const niceMatching: string[] = match.nice_matching ?? [];
  const niceGaps: string[] = match.nice_gaps ?? [];
  const missingMust: string[] = match.missing_must ?? [];
  const gaugeColor =
    pct == null
      ? "text-muted-foreground"
      : pct >= 80
        ? "text-success"
        : pct >= 60
          ? "text-warning"
          : "text-muted-foreground";
  const city = formatCandidateLocation(c.location);
  const roleLine =
    [c.current_title, c.current_company].filter(Boolean).join(" · ") ||
    c.competence_category ||
    "";

  return (
    <div className="space-y-4 rounded-xl border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-primary">
            Dopasowanie
          </div>
          <div className="truncate text-sm font-semibold text-foreground">
            {fullName}
          </div>
          {(roleLine || city) && (
            <div className="truncate text-xs text-muted-foreground">
              {roleLine}
              {roleLine && city ? " · " : ""}
              {city}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-accent"
          aria-label="Zamknij dok"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div>
        <div className="flex items-end gap-2">
          <span className={`text-3xl font-bold tabular-nums ${gaugeColor}`}>
            {pct == null ? "Ocena niepełna" : pct}
          </span>
          <span className="pb-1 text-xs text-muted-foreground">
            {pct == null ? "" : "/ 100 · dopasowanie do tej rekrutacji"}
          </span>
        </div>
        <div className="mt-1 h-2 overflow-hidden rounded-full bg-muted">
          <div
            className={
              "h-2 rounded-full " +
              (pct == null
                ? "bg-muted-foreground/30"
                : pct >= 80
                  ? "bg-success"
                  : pct >= 60
                    ? "bg-warning"
                    : "bg-muted-foreground/40")
            }
            style={{ width: `${pct ?? 0}%` }}
          />
        </div>
        <p className="mt-1.5 text-[11px] text-muted-foreground">
          Wynik to głównie podobieństwo semantyczne CV do oferty; pokrycie
          wymagań must to jeden ze składników.
        </p>
      </div>

      {elig && (
        <div
          className={
            "flex items-start gap-1.5 rounded-md border px-2.5 py-1.5 text-[11px] " +
            (assignBlocked
              ? "border-destructive/30 bg-destructive/10 text-destructive"
              : "border-warning/25 bg-warning-muted text-warning-muted-foreground")
          }
        >
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{elig.reason}</span>
        </div>
      )}

      {(requiredSkills.length > 0 || niceSkills.length > 0) && (
        <div className="space-y-1.5">
          <div className="text-xs font-semibold text-foreground">
            Pokrycie wymagań · {mustMatching.length} z {requiredSkills.length} must
          </div>
          {missingMust.length > 0 && (
            <div
              className="rounded-md border border-destructive/25 bg-destructive/5 px-2 py-1 text-[11px] text-destructive"
              title="Bramka dealbreakera (0278): bez tych technologii kandydat jest ukrywany na pozostałych powierzchniach rankingu — ta lista jest węższa niż pełne pokrycie wymagań poniżej."
            >
              Bramka must-have: brak {missingMust.join(", ")}
            </div>
          )}
          <div className="space-y-1">
            {mustMatching.map((s) => (
              <CoverageRow key={`m-${s}`} label={s} tag="must" hit />
            ))}
            {mustGaps.map((s) => (
              <CoverageRow key={`mg-${s}`} label={`${s} — brak potwierdzenia`} tag="must" />
            ))}
            {niceMatching.map((s) => (
              <CoverageRow key={`n-${s}`} label={s} tag="nice" hit />
            ))}
            {niceGaps.map((s) => (
              <CoverageRow key={`ng-${s}`} label={`${s} — brak potwierdzenia`} tag="nice" />
            ))}
          </div>
        </div>
      )}

      <div className="space-y-1.5">
        <div className="text-xs font-semibold text-foreground">
          Warunki wobec oferty
        </div>
        <div className="grid grid-cols-[80px_minmax(0,1fr)] gap-x-2 gap-y-1 text-xs">
          <span className="text-muted-foreground">Stawka</span>
          <span>
            {rate != null ? (
              <span
                className={
                  "font-medium tabular-nums " +
                  (rateBand === "over"
                    ? "text-destructive"
                    : rateBand === "in"
                      ? "text-success"
                      : "text-foreground")
                }
              >
                {formatMatchingRate(c)}
                {budgetHourly != null && (
                  <span className="ml-1 font-normal text-muted-foreground">
                    {rateBand === "unknown"
                      ? "· do weryfikacji"
                      : rateBand === "over"
                      ? `· powyżej budżetu ${Math.round(budgetHourly)}`
                      : `· w budżecie do ${Math.round(budgetHourly)}`}
                  </span>
                )}
              </span>
            ) : (
              <span className="text-muted-foreground">brak danych</span>
            )}
          </span>
          <span className="text-muted-foreground">Lokalizacja</span>
          <span className="text-foreground">{city || "—"}</span>
          {officeFitLabel && (
            <>
              <span className="text-muted-foreground">Biuro</span>
              <span
                className={
                  "font-medium " +
                  (officeFit === "ok" ? "text-success" : "text-destructive")
                }
              >
                {officeFitLabel}
              </span>
            </>
          )}
          <span className="text-muted-foreground">Etap</span>
          <span>
            {inPipeline ? (
              <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[11px] text-primary">
                w procesie
              </span>
            ) : (
              <span className="text-muted-foreground">poza procesem</span>
            )}
          </span>
        </div>
      </div>

      {c.ai_summary && (
        <div className="space-y-1">
          <div className="text-xs font-semibold text-foreground">Podsumowanie</div>
          <p className="line-clamp-4 text-xs leading-relaxed text-muted-foreground">
            {c.ai_summary}
          </p>
        </div>
      )}

      {!readOnly && (
        <div className="flex flex-wrap gap-2 border-t border-border pt-3">
          <button
            onClick={() => onAddPipeline(c.id, fullName)}
            disabled={addingId === c.id || isAdded || assignBlocked}
            title={assignBlocked ? elig?.reason : undefined}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {assignBlocked ? (
              <>
                <AlertCircle className="h-3 w-3" /> Nie można dodać
              </>
            ) : isAdded ? (
              <>
                <Check className="h-3 w-3" /> W pipeline
              </>
            ) : (
              <>
                <Plus className="h-3 w-3" />
                {addingId === c.id ? "Dodawanie…" : "Dodaj do pipeline"}
              </>
            )}
          </button>
          <button
            onClick={() => onShortlist(c.id, fullName)}
            disabled={shortlistingId === c.id || assignBlocked}
            title={assignBlocked ? elig?.reason : "Ocena przed pipeline"}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
          >
            <UserCheck className="h-3 w-3" />
            {shortlistingId === c.id ? "Dodawanie…" : "Na shortlistę"}
          </button>
          <button
            onClick={() => onEmail(c)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted"
          >
            <Mail className="h-3 w-3" /> Wyślij
          </button>
          <Link
            href={`/candidates/${c.id}?${encodeJobBackRef(jobId).toString()}`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted"
          >
            <ExternalLink className="h-3 w-3" /> Profil
          </Link>
        </div>
      )}

      <div className="border-t border-border pt-3">
        {showJustification ? (
          <DopasowanieTab
            candidateId={c.id}
            recruitments={[{ job_id: jobId, job_title: jobTitle }]}
            defaultJobId={jobId}
            readOnly={readOnly}
          />
        ) : (
          <button
            onClick={() => setShowJustification(true)}
            className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline"
          >
            <Sparkles className="h-3 w-3" /> Pełne uzasadnienie AI
          </button>
        )}
      </div>
    </div>
  );
}

// ── Recruitment type config ───────────────────────────────────────────────────

const RECRUITMENT_TYPE_CONFIG: Record<
  string,
  { label: string; variant: "soft" | "success" | "warning" }
> = {
  body_leasing: { label: "Body Leasing", variant: "soft" },
  sales_project: { label: "Sprzedaż", variant: "success" },
  tender: { label: "Przetarg", variant: "warning" },
};

// ── Kroki 05 i 06 za granicą `next/dynamic` ──────────────────────────────────
//
// `/jobs/[id]` to gorąca trasa, a stanowisko „CV do klienta" wciąga cały
// `CVGeneratorStandaloneV2` (1800 linii: combobox, dropzone, modale podglądu
// i udostępniania). Bez tej granicy za jego wagę płaciłoby KAŻDE otwarcie
// rekrutacji, także wtedy, gdy nikt nie zajrzy do kroku 06. Oba stanowiska
// renderują się dopiero po kliknięciu kroku na listwie — dokładnie ten sam
// wzorzec, którego pilnuje `heavy-bundle-boundaries.test.ts` dla TipTapa
// i rechartsa.
const ScreeningWorkbench = dynamic(
  () =>
    import("@/components/v2/jobs/ScreeningWorkbench").then(
      (m) => m.ScreeningWorkbench,
    ),
  { ssr: false },
);
const CvHandoffWorkbench = dynamic(
  () =>
    import("@/components/v2/jobs/CvHandoffWorkbench").then(
      (m) => m.CvHandoffWorkbench,
    ),
  { ssr: false },
);

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function JobDetailPage() {
  const { id } = useParams();
  const searchParams = useSearchParams();
  const openTab = useTabsStore((s) => s.openTab);
  const queryClient = useQueryClient();
  // Legacy AI Matching (M3-UI-01): trzy równoległe rankingi na jednym ekranie
  // dezorientują — sekcja legacy (+ operacyjne akcje "Przelicz scoring" /
  // "Embed all jobs") zostaje wyłącznie dla admina jako widok diagnostyczny.
  const authUser = useAuthStore((s) => s.user);
  const impersonating = useAuthStore((s) => s.realUser !== null);
  const isAdmin = hasRole(authUser, "admin");
  const canWritePipeline =
    !impersonating && hasSectionAccess(authUser, "pipeline", "write");
  // PATCH /api/jobs/{id} to TacPlus — a TacPlus nie obejmuje HoR. Przez rejestr,
  // żeby nie hodować drugiej listy ról obok niego (F-19).
  const canUpdateJob = useCapability("job.update");
  // POST /api/invite-links → RecruiterPlus. Ta sama capability bramkuje akcję
  // na liście ofert — bez niej read-only `user` widział tu przycisk wiodący
  // prosto w 403 (audyt F-19).
  const canCreateInviteLink = useCapability("invite_link.create");
  const [showAIWriter, setShowAIWriter] = useState(false);
  const [showEditJob, setShowEditJob] = useState(false);
  const [showInviteLink, setShowInviteLink] = useState(false);
  const [showAddCandidates, setShowAddCandidates] = useState(false);
  // Opis oferty potrafi mieć kilkaset linii — domyślnie zwinięty, żeby nagłówek
  // nie spychał pipeline'u poza ekran.
  const [showFullDescription, setShowFullDescription] = useState(false);
  const [activeTab, setActiveTab] = useState<JobDetailTab>("pipeline");
  // Zwijanie nagłówka oferty (przyciski + właściciele + opis) — daje pipeline'owi
  // więcej miejsca. Preferencja globalna w localStorage, więc trzyma się między
  // ofertami i sesjami.
  const [headerCollapsed, setHeaderCollapsed] = useLocalStorageFlag(
    JOB_HEADER_COLLAPSED_STORAGE_KEY,
    JOB_HEADER_COLLAPSED_DEFAULT,
  );

  // Deep link z notyfikacji ?tab=chat → otwórz zakładkę Chat od razu.
  // ?tab=similar (notyfikacja „Podobny request — gotowi kandydaci”) →
  // zakładka AI Matching; scroll + glow robi sama HistoricalCandidatesSection.
  // ?tab=champion (dok „Gotowość zlecenia" na /jobs, akcja „Otwórz" przy
  // pozycji Profil Championa) → "champion" jest już literałem `JobDetailTab`,
  // więc mapowanie jest tożsamościowe — bez tego link lądował po cichu na
  // domyślnym Pipeline zamiast na Championie.
  useEffect(() => {
    const tab = searchParams?.get("tab");
    if (tab === "chat") {
      setActiveTab("chat");
    } else if (tab === "similar") {
      setActiveTab("ai-matching");
    } else if (tab === "champion") {
      setActiveTab("champion");
    } else if (tab === "screening" || tab === "cv") {
      // Kroki 05/06 — deep-link tożsamościowy, jak „champion".
      setActiveTab(tab);
    } else if (tab === "interviews") {
      // Kroki 07 i 08 (flow C2) — mapowanie tożsamościowe, jak „champion".
      setActiveTab("interviews");
    } else if (tab === "contract") {
      setActiveTab("contract");
    }
  }, [searchParams]);

  // Unread badge dla taba Chat
  const { data: chatUnread } = useQuery({
    queryKey: ["job-chat-unread", id],
    queryFn: async () => (await jobChatApi.getUnreadCount(Number(id))).data,
    enabled: !!id,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });

  // Phase 13: when redirected from AddJobModal with ?highlight=ai-proposals,
  // switch to the AI matching tab. Scroll + glow + query-param cleanup for the
  // "Rekomendowani" card now live in SourcingHub (krok 03, PR 2/7) — ono
  // renderuje się dopiero po przełączeniu zakładki, więc to jest wszystko,
  // czego strona sama musi dopilnować.
  useEffect(() => {
    if (searchParams?.get("highlight") !== "ai-proposals") return;
    setActiveTab("ai-matching");
  }, [searchParams]);

  const {
    data: job,
    isLoading: jobLoading,
    isError: jobIsError,
    error: jobError,
    refetch: refetchJob,
  } = useQuery({
    queryKey: ["job", id],
    queryFn: () => api.get(`/api/jobs/${id}`).then((r) => r.data),
  });

  const {
    data: kanban,
    isLoading: kanbanLoading,
    // Kroki 05–08 renderują pipeline z TEGO zapytania. Bez przekazania im
    // błędu 403/500 wyglądałby stamtąd jak „nikt nie jest u klienta" — czyli
    // dokładnie ten wzorzec, przez który brak uprawnień czytało się jako
    // utratę danych (F-20).
    isError: kanbanIsError,
    error: kanbanError,
    isSuccess: kanbanIsSuccess,
    refetch: refetchKanban,
  } = useQuery({
    queryKey: ["kanban", id],
    queryFn: () => api.get(`/api/pipeline/kanban/${id}`).then((r) => r.data),
  });

  // Kroki 05–08 (Screening, CV do klienta, Rozmowy, Umowa) czytają TE SAME
  // kolumny co listwa kroków — bez własnego zapytania (program „flow w języku
  // C2", PR 6/7 i 7/7).
  const kanbanColumns = useMemo(
    () => (kanban?.columns ?? []) as KanbanColumn[],
    [kanban],
  );
  const invalidateKanban = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["kanban", id] });
    queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
  }, [queryClient, id]);

  // AI match scores (0-100) for pipeline candidates → score ring on kanban cards.
  // Fetched in parallel with the kanban (cache-first server-side) so cards paint
  // immediately and the rings fill in when scores resolve.
  const { data: pipelineScores, isLoading: scoresLoading } = useQuery({
    queryKey: ["pipeline-scores", id],
    queryFn: () => matchingApi.pipelineScores(Number(id)).then((r) => r.data),
    enabled: activeTab === "pipeline" && !!id,
    staleTime: 5 * 60_000,
  });
  const scoreMap = useMemo(() => {
    const m = new Map<number, number>();
    const s = pipelineScores?.scores;
    if (s) {
      for (const [cid, score] of Object.entries(s)) m.set(Number(cid), score);
    }
    return m;
  }, [pipelineScores]);

  // Kroki 07 i 08 czytają `kanbanColumns` zadeklarowane wyżej — jedno źródło
  // (`["kanban", id]`) karmi tablicę ORAZ cztery zakładki kroków 05–08.
  //
  // Liczenie przeniesione do `lib/pipeline-flow.ts`, bo klaster KPI w jobbarze
  // pyta o TE SAME zbiory. Trzy idiomy „ile jest w kolumnie" (`col.count`,
  // `items.length`, `items.length ?? count`) żyły dotąd obok siebie w jednym
  // pliku — a listwa kroków i jobbar stoją na ekranie jeden pod drugim, więc
  // rozjazd o jedną kartę byłby widoczny jako dwie różne liczby pod tą samą
  // nazwą.
  const flowCounts = useMemo(() => {
    if (!kanban) return undefined;
    return {
      interviews: countInterviewStages(kanbanColumns),
      contract: countContractStages(kanbanColumns),
    };
  }, [kanban, kanbanColumns]);

  // ── Jobbar: podtytuł i klaster KPI (makieta „flow w języku C2", k2–k8) ────
  //
  // Ranking C2 czytany WYŁĄCZNIE z cache'u (`enabled: false`). Własne zapytanie
  // odpalałoby Qdranta przy każdym wejściu na dowolną zakładkę rekrutacji —
  // także tam, gdzie rankingu nikt nie ogląda. Brak w cache'u = „—", nie zero.
  //
  // The full-search publisher shares actor-scoped population totals. Incomplete
  // measurements keep the strong-match count unknown without hiding coverage.
  const { data: ranking = null } = useQuery<FullSearchSummary | null>({
    queryKey: ["full-search-summary", authUser?.id, Number(id)],
    queryFn: async () => null,
    enabled: false,
  });
  const headerKpis = useMemo(
    () =>
      buildJobHeaderKpis({
        tab: activeTab,
        columns: kanban ? kanbanColumns : null,
        ranking,
      }),
    [activeTab, kanban, kanbanColumns, ranking],
  );
  const headerSubtitle = useMemo(() => {
    if (!job) return [];
    return buildJobHeaderSubtitle({
      location: job.location,
      remotePolicy: job.remote_policy,
      rateBudgetHourly: job.rate_budget_hourly,
      salaryMin: job.salary_min,
      salaryMax: job.salary_max,
      deadline: job.deadline,
      ownerName: job.primary_owner?.name,
      // Hiring manager tylko w kroku 07 — tam jest decydentem, a nie jedną
      // z ośmiu rzeczy w linijce, którą trzeba przeczytać w całości.
      hiringManagerName:
        activeTab === "interviews" ? job.hiring_manager_name : null,
      // Obsada tylko w kroku 08 — to jedyny krok, na którym pytanie „ilu
      // z ilu" jest pytaniem o zakończenie rekrutacji.
      hired:
        activeTab === "contract" && kanban ? countHired(kanbanColumns) : null,
      headcount: activeTab === "contract" ? job.headcount : null,
    });
  }, [job, activeTab, kanban, kanbanColumns]);

  // Auto-open tab when job data loads
  useEffect(() => {
    if (job) {
      openTab("job", Number(id), job.title);
    }
  }, [job, id, openTab]);

  const handleUseDescription = useCallback(async (description: string) => {
    if (!canWritePipeline) return;
    await api.patch(`/api/jobs/${id}`, { description });
    await queryClient.invalidateQueries({ queryKey: ["job", id] });
  }, [canWritePipeline, id, queryClient]);

  // 403 (brak uprawnień) i 5xx (awaria) NIE mogą udawać „nie znaleziono" —
  // to dokładnie ten wzorzec, przez który 403 na GET czytało się jako utratę
  // danych (audyt F-20).
  const jobViewState = resolveViewState({
    isLoading: jobLoading,
    isError: jobIsError,
    error: jobError,
    isEmpty: !job,
  });
  if (jobViewState === "loading")
    return <div className="p-6 text-muted-foreground">Ładowanie...</div>;
  if (jobViewState !== "ready")
    return (
      <div className="p-6">
        <QueryStateNotice
          state={jobViewState === "empty" ? "not_found" : jobViewState}
          description={
            jobViewState === "forbidden"
              ? "Nie masz uprawnień do tej rekrutacji. Rekrutacja istnieje — poproś o dodanie Cię do jej zespołu albo o rozszerzenie roli."
              : undefined
          }
          onRetry={() => void refetchJob()}
        />
      </div>
    );

  return (
    <div className="space-y-2">
      <JobDetailCompactHeader
        title={job.title}
        clientName={job.client_name}
        referenceNumber={job.reference_number}
        badges={
          <>
            {job.recruitment_type &&
            RECRUITMENT_TYPE_CONFIG[job.recruitment_type] ? (
              <Badge
                variant={
                  RECRUITMENT_TYPE_CONFIG[job.recruitment_type].variant
                }
              >
                {RECRUITMENT_TYPE_CONFIG[job.recruitment_type].label}
              </Badge>
            ) : null}
            <Badge
              variant={
                job.status === "published"
                  ? "success"
                  : job.status === "draft"
                    ? "neutral"
                    : "danger"
              }
            >
              {job.status === "published"
                ? "Aktywna"
                : job.status === "draft"
                  ? "Szkic"
                  : job.status}
            </Badge>
            {!canWritePipeline ? (
              <Badge variant="info">Tylko odczyt</Badge>
            ) : null}
          </>
        }
        // Jedna linia faktów zamiast rzędu odznak z ikonami (makieta k2–k8).
        // Nic z dawnego rzędu nie znika: lokalizacja, widełki i deadline są
        // w niej dalej — dochodzą tryb pracy, sufit budżetu kandydackiego
        // i właściciel, którego nagłówek dotąd w ogóle nie pokazywał.
        subtitle={
          headerSubtitle.length > 0 ? (
            <span className="text-[12px]">{headerSubtitle.join(" · ")}</span>
          ) : undefined
        }
        kpis={headerKpis}
        presence={
          <ActiveViewers
            resourceType="job"
            resourceId={Number.isFinite(Number(id)) ? Number(id) : null}
          />
        }
        activeTab={activeTab}
        onTabChange={setActiveTab}
        onAddCandidate={canWritePipeline ? () => setShowAddCandidates(true) : undefined}
        onEdit={
          canWritePipeline && canUpdateJob
            ? () => setShowEditJob(true)
            : undefined
        }
        onWriteAnnouncement={
          canWritePipeline && canUpdateJob
            ? () => setShowAIWriter(true)
            : undefined
        }
        onGenerateInviteLink={
          canWritePipeline &&
          job.status === "published" &&
          canCreateInviteLink
            ? () => setShowInviteLink(true)
            : undefined
        }
        chatUnreadCount={chatUnread?.unread_count ?? 0}
        // Licznik „w procesie" na listwie kroków — ten sam wzór co
        // StageFocusNavigator (suma kolumn nie-terminalnych). Kanban ładuje się
        // dopiero na zakładce Pipeline; do tego czasu listwa nie pokazuje liczby.
        // Liczy `countInProcess`, czyli TA SAMA funkcja, której używa KPI
        // „w procesie" w jobbarze — te dwie liczby stoją na ekranie jedna pod
        // drugą i muszą być tą samą liczbą.
        pipelineCount={kanban ? countInProcess(kanbanColumns) : undefined}
        // Kroki 05/06 — liczniki z tych samych kolumn co „Pipeline". Dopóki
        // kanban się nie wczytał, listwa nie pokazuje liczby (zero znaczyłoby
        // „nikogo tu nie ma", a to jeszcze nie wiadomo).
        screeningCount={
          kanban
            ? selectScreeningQueue(kanbanColumns).length +
              selectPendingVerifications(kanbanColumns).length
            : undefined
        }
        cvCount={kanban ? selectVerifiedQueue(kanbanColumns).length : undefined}
        // Kroki 07 i 08 (flow C2, PR 7/7) — liczone z TEGO SAMEGO kanbana co
        // Pipeline, więc listwa nie dokłada ani jednego zapytania. `undefined`
        // dopóki kanban się nie wczyta: zero czytałoby się jako „nikt nie jest
        // u klienta", a to inna wiadomość niż „jeszcze nie wiem".
        interviewsCount={flowCounts?.interviews}
        contractCount={flowCounts?.contract}
        contextOpen={!headerCollapsed}
        onContextOpenChange={(open) => setHeaderCollapsed(!open)}
        contextContent={
          <>
            {/* Krok 02 „Zlecenie i Champion" (program „flow w języku C2",
                PR 5/7) przeniósł Właściciela/Współpracowników, Hiring
                Managera i Priority Work do zakładki doku „Zespół i
                priorytet" — na TYM kroku ten panel byłby duplikatem tej
                samej mutowalnej treści w dwóch miejscach na ekranie
                jednocześnie. Na pozostałych krokach (Pipeline, Pozyskiwanie,
                …) panel „Zespół i priorytet" w nagłówku zostaje bez zmian. */}
            {activeTab === "champion" ? (
              <p className="text-xs text-muted-foreground">
                Właściciela, hiring managera i Priority Work znajdziesz teraz
                w zakładce „Zespół i priorytet" doku obok Profilu Championa.
              </p>
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
                <JobOwnershipPanel
                  jobId={Number(id)}
                  jobTitle={job.title}
                  primaryOwner={job.primary_owner ?? null}
                  collaborators={job.collaborators ?? []}
                />
                <HiringManagerPicker
                  jobId={Number(id)}
                  clientId={job.client_id ?? null}
                  value={job.hiring_manager_contact_id ?? null}
                  valueName={job.hiring_manager_name ?? null}
                  canEdit={canWritePipeline && canUpdateJob}
                  onSaved={() =>
                    queryClient.invalidateQueries({ queryKey: ["job", id] })
                  }
                />
              </div>
            )}
            {job.description ? (
              <div className="border-t border-border pt-3">
                <button
                  type="button"
                  onClick={() => setShowFullDescription((value) => !value)}
                  className="text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
                >
                  {showFullDescription ? "Ukryj opis ▲" : "Pokaż opis ▼"}
                </button>
                {showFullDescription ? (
                  <div className="mt-2 whitespace-pre-line text-sm text-muted-foreground">
                    {job.description}
                  </div>
                ) : null}
              </div>
            ) : null}
            {activeTab !== "champion" && <JobPriorityContext jobId={Number(id)} />}
          </>
        }
      />

      {/* Edit Job Modal */}
      {canWritePipeline && showEditJob && job && (
        <EditJobModal
          job={job}
          onClose={() => setShowEditJob(false)}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ["job", id] });
            setShowEditJob(false);
          }}
        />
      )}

      {/* AI Writer Modal */}
      {canWritePipeline && showAIWriter && (
        <AIJobWriterModal
          job={job}
          onClose={() => setShowAIWriter(false)}
          onUse={handleUseDescription}
        />
      )}

      {/* Invite Link Modal — pre-selected current job */}
      <GenerateInviteLinkV2
        open={canWritePipeline && showInviteLink}
        onOpenChange={setShowInviteLink}
        defaultJobId={Number(id)}
      />

      {/* Quick search + bulk-add candidates to this job */}
      <AddCandidatesQuickModal
        open={canWritePipeline && showAddCandidates}
        onClose={() => setShowAddCandidates(false)}
        jobId={Number(id)}
        jobTitle={job.title}
      />

      {/* Tab Content */}
      {activeTab === "pipeline" && (
        <div>
          {kanbanLoading ? (
            <div className="text-muted-foreground">Ładowanie pipeline...</div>
          ) : (
            <KanbanBoardV2
              columns={kanban?.columns ?? []}
              offTemplate={kanban?.off_template ?? null}
              jobId={Number(id)}
              jobTitle={job?.title}
              scoreMap={scoreMap}
              scoresLoading={scoresLoading}
              headerCollapsed={headerCollapsed}
              readOnly={!canWritePipeline}
              // Fala 3: SLA klienta na kolumnie Screening i w lewej kolumnie —
              // ten sam klucz zapytania karty klienta co krok 06 (zero nowych
              // requestów). Bez klienta tablica mówi „nie ustawiono".
              clientId={job?.client_id ?? null}
            />
          )}
        </div>
      )}

      {activeTab === "history" && (
        <RequestHistorySection
          jobId={Number(id)}
          clientId={job?.client_id ?? null}
          readOnly={!canWritePipeline}
        />
      )}

      {activeTab === "ai-matching" && (
        // Krok 03 „Pozyskiwanie" (program „Flow w języku C2", PR 2/7): rama
        // czterech kart-źródeł nad C2. „Kandydaci z podobnych projektów" i
        // „Rekomendowani" — dotąd bloki NAD rankingiem — są teraz kartą/
        // reveal-em wewnątrz SourcingHub; ono też dokłada kompaktową Historię
        // requestu pod ramą. C2 (AIMatchingSection) jedzie jako `children`,
        // dokładnie tak jak dziś — bez żadnych zmian.
        <SourcingHub
          jobId={Number(id)}
          job={job}
          readOnly={!canWritePipeline}
          onTabChange={setActiveTab}
          searchSummary={ranking}
        >
          {/* Warsztat dopasowań C2 — „kto pasuje do tej oferty". Widoczny dla
              wszystkich ról; akcje respektują readOnly. Narzędzia AI (kryteria,
              scoring, embedding) są wewnątrz, zwinięte, tylko dla admina. */}
          <AIMatchingSection
            jobId={Number(id)}
            job={job}
            readOnly={!canWritePipeline}
            isAdmin={isAdmin}
          />
        </SourcingHub>
      )}

      {activeTab === "manual-search" && job && (
        <ManualSearchTab
          jobId={Number(id)}
          job={job}
          readOnly={!canWritePipeline}
          onBulkAdded={() => {
            queryClient.invalidateQueries({ queryKey: ["kanban", id] });
            queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
          }}
        />
      )}

      {activeTab === "portals" && (
        <PostingsSection jobId={Number(id)} readOnly={!canWritePipeline} />
      )}

      {activeTab === "champion" && (
        // Krok 02 „Zlecenie i Champion" (program „flow w języku C2", PR 5/7):
        // sam layout kroku, jak C2 — lewa kolumna nawiguje po sekcjach
        // Championa, środek jest teraz pełną szerokością (bez `max-w`), a
        // dok „Gotowość" (`variant="champion"`) niesie weryfikację/briefing/
        // rekomendowane wyszukiwania/zespół i priorytet/handoff, które do tej
        // pory siedziały nad formularzem i w panelu nagłówka.
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_360px]">
          <aside className="lg:sticky lg:top-4 lg:self-start">
            <ChampionSectionNav jobId={Number(id)} />
          </aside>

          <div className="min-w-0 space-y-4">
            <JobSummaryCard
              job={job}
              onEdit={
                canWritePipeline && canUpdateJob
                  ? () => setShowEditJob(true)
                  : undefined
              }
            />
            <ChampionProfileEditor
              jobId={Number(id)}
              clientId={job?.client_id ?? null}
              // Backend PUT /champion-profile is DeliveryLeadPlus — mirror it so a
              // recruiter sees a read-only Champion instead of filling a form that
              // 403s on save (P1-02).
              canEdit={
                canWritePipeline &&
                (isAdmin || hasRole(authUser, "delivery_lead"))
              }
            />
          </div>

          <aside className="lg:col-span-2 xl:col-span-1 xl:sticky xl:top-4 xl:self-start">
            <JobReadinessDock jobId={Number(id)} variant="champion" />
          </aside>
        </div>
      )}

      {/* Krok 05 „Screening" (program „flow w języku C2", PR 6/7) — kolejka,
          arkusz Championa inline i dok weryfikacji stawki. Arkusz jako modal
          na tablicy Pipeline ZOSTAJE bez zmian. */}
      {activeTab === "screening" && (
        <ScreeningWorkbench
          jobId={Number(id)}
          jobBudgetMax={
            typeof job?.salary_max === "number" ? job.salary_max : null
          }
          columns={kanbanColumns}
          isLoading={kanbanLoading}
          isError={kanbanIsError}
          error={kanbanError}
          isSuccess={kanbanIsSuccess}
          onRetry={() => void refetchKanban()}
          onMoved={invalidateKanban}
          readOnly={!canWritePipeline}
          onTabChange={setActiveTab}
          // Fala 3: „SLA <klient>: N d" w nagłówku kolejki i „dzień X z Y SLA"
          // — z karty klienta (ten sam klucz zapytania co krok 06).
          clientId={job?.client_id ?? null}
          clientName={job?.client_name ?? null}
        />
      )}

      {/* Krok 06 „CV do klienta" — reguły klienta przed generacją, generator
          osadzony z prefillem i jedna akcja wysyłki. */}
      {activeTab === "cv" && (
        <CvHandoffWorkbench
          jobId={Number(id)}
          jobTitle={job?.title}
          clientId={job?.client_id ?? null}
          columns={kanbanColumns}
          isLoading={kanbanLoading}
          isError={kanbanIsError}
          error={kanbanError}
          isSuccess={kanbanIsSuccess}
          onRetry={() => void refetchKanban()}
          onMoved={invalidateKanban}
          readOnly={!canWritePipeline}
        />
      )}

      {activeTab === "questions" && (
        <QuestionBankTab
          jobId={Number(id)}
          clientId={job?.client_id ?? null}
          readOnly={!canWritePipeline}
        />
      )}

      {/* Krok 07 „Rozmowy i decyzja" (flow C2, PR 7/7). Kolumny kanbana idą
          propsem — zakładka nie pobiera pipeline'u drugi raz. */}
      {activeTab === "interviews" && (
        <JobInterviewsTab
          jobId={Number(id)}
          jobTitle={job?.title}
          columns={kanbanColumns}
          columnsLoading={kanbanLoading}
          columnsError={kanbanIsError ? (kanbanError ?? true) : undefined}
          columnsSuccess={kanbanIsSuccess}
          onColumnsRetry={() => void refetchKanban()}
          readOnly={!canWritePipeline}
        />
      )}

      {/* Krok 08 „Umowa". `canCloseJob` to `job.update` — lustro `TacPlus`,
          tej samej bramki co `POST /api/jobs/{id}/close`. */}
      {activeTab === "contract" && (
        <JobContractTab
          jobId={Number(id)}
          jobTitle={job?.title ?? `Rekrutacja #${id}`}
          clientId={job?.client_id ?? null}
          columns={kanbanColumns}
          columnsLoading={kanbanLoading}
          columnsError={kanbanIsError ? (kanbanError ?? true) : undefined}
          columnsSuccess={kanbanIsSuccess}
          onColumnsRetry={() => void refetchKanban()}
          readOnly={!canWritePipeline}
          canCloseJob={canUpdateJob}
        />
      )}

      {activeTab === "chat" && (
        <JobChatTab jobId={Number(id)} readOnly={!canWritePipeline} />
      )}
    </div>
  );
}

// ── Manual search tab ────────────────────────────────────────────────────────

interface JobLite {
  id: number;
  title: string;
  description?: string | null;
  requirements?: string | null;
  seniority?: string | null;
  must_skills?: unknown;
  nice_skills?: unknown;
  competence_category_id?: number | null;
  salary_min?: number | null;
  salary_max?: number | null;
  location?: string | null;
}

interface ManualSearchTabProps {
  jobId: number;
  job: JobLite;
  onBulkAdded?: () => void;
  readOnly?: boolean;
}

/**
 * Embeds CandidateSearchView with the job's metadata pre-filled into the
 * filters. The user lands on a results list already scoped to the job and
 * can bulk-add hits straight into the pipeline. Already-added candidates
 * are excluded server-side via ``exclude_in_job_id``.
 */
function ManualSearchTab({
  jobId,
  job,
  onBulkAdded,
  readOnly = false,
}: ManualSearchTabProps) {
  const initial = buildJobSearchPrefill(job);

  return (
    <CandidateSearchView
      initial={initial}
      addToJob={{ id: jobId, title: job.title }}
      onBulkAdded={onBulkAdded}
      readOnly={readOnly}
    />
  );
}
