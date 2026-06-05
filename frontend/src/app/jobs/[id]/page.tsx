"use client";

import { useEffect, useState, useCallback } from "react";
import { usePathname, useParams, useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import api, { postingsApi, aiWriterApi, matchingApi, phase3Api, recommendationsApi } from "@/lib/api";
import { KanbanBoardV2 } from "@/components/v2/pages/KanbanBoardV2";
import { EditJobModal } from "@/components/AppShell";
import { SuggestedCandidatesWidget } from "@/components/SuggestedCandidatesWidget";
import { HistoricalCandidatesSection } from "@/components/HistoricalCandidatesSection";
import { RequestHistorySection } from "@/components/RequestHistorySection";
import { ChampionProfileEditor } from "@/components/ChampionProfileEditor";
import { QuestionBankTab } from "@/components/prep/QuestionBankTab";
import { CriteriaPreviewV2 as CriteriaPreviewModal } from "@/components/v2/modals/CriteriaPreviewV2";
import { JobOwnershipPanel } from "@/components/v2/jobs/JobOwnershipPanel";
import JobChatTab from "@/components/v2/pages/JobChatTab";
import { jobChatApi } from "@/lib/api";
import { ArrowLeft, MapPin, Banknote, Calendar, Globe, Trash2, ExternalLink, Plus, Radio, Wand2, X, Copy, Check, PencilLine, Sparkles, UserCheck, AlertCircle, Mail, Link2, MessageCircle, History, Search, UserPlus } from "lucide-react";
import { AddCandidatesQuickModal } from "@/components/v2/modals/AddCandidatesQuickModal";
import { CandidateSearchView } from "@/components/v2/pages/CandidateSearchView";
import type { CandidateSearchRequest } from "@/lib/candidate-search-api";
import { GenerateInviteLinkV2 } from "@/components/v2/modals/GenerateInviteLinkV2";
import { DeleteButton } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import Link from "next/link";
import { formatDate } from "@/lib/utils";
import { encodeJobBackRef } from "@/lib/url-filters";
import { useTabsStore } from "@/store/tabs";
import { ActiveViewers } from "@/components/v2/presence/ActiveViewers";
import { LocationInput } from "@/components/v2/filters/LocationInput";
import { formatCandidateLocation } from "@/components/v2/pages/candidate-list-helpers";

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
  nofluffjobs: { label: "NoFluffJobs",  color: "bg-destructive/15 text-destructive",        dotColor: "bg-destructive/100" },
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
      <div className="bg-card rounded-xl shadow-xl w-full max-w-md p-6">
        <h2 className="text-lg font-bold mb-1">Opublikuj ogłoszenie</h2>
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
                <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${config.dotColor}`} />
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

function PostingsSection({ jobId }: { jobId: number }) {
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
        <div className="flex gap-2">
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
        </div>
      </div>

      {/* Simulation notice */}
      <div className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4">
        ⚠️ Integracja z portalami w przygotowaniu — dane symulowane
      </div>

      {/* Table */}
      {postings.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground">
          <Globe className="w-10 h-10 mx-auto mb-2 opacity-30" />
          <p className="text-sm">Brak publikacji. Opublikuj ogłoszenie na portalach rekrutacyjnych.</p>
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
                <th className="text-center py-2 px-3 text-muted-foreground font-medium">Akcje</th>
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
                        <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${portalCfg.dotColor}`} />
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
                          className="text-primary hover:text-primary/80 inline-flex items-center gap-1"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="py-2.5 px-3 text-center">
                      <DeleteButton onConfirm={() => deleteMutation.mutate(posting.id)} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Publish modal */}
      {showModal && (
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

function AIJobWriterModal({
  job,
  onClose,
  onUse,
}: {
  job: any;
  onClose: () => void;
  onUse: (desc: string) => void;
}) {
  const [title, setTitle] = useState(job?.title || "");
  const [clientName, setClientName] = useState(job?.client?.name || "");
  const [seniority, setSeniority] = useState("senior");
  const [requirements, setRequirements] = useState(job?.requirements || "");
  const [generated, setGenerated] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const handleGenerate = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const { data } = await aiWriterApi.generateJobDescription({
        title,
        client_name: clientName || undefined,
        requirements: requirements || undefined,
        seniority,
      });
      setGenerated(data.description);
    } catch (e: any) {
      setError(e.response?.data?.detail || "Błąd generowania ogłoszenia");
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopy = async () => {
    if (!generated) return;
    await navigator.clipboard.writeText(generated);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4 overflow-y-auto">
      <div className="bg-card rounded-2xl shadow-xl w-full max-w-2xl my-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border dark:border-border">
          <div className="flex items-center gap-2">
            <Wand2 className="w-5 h-5 text-primary" />
            <h2 className="text-lg font-bold text-foreground">AI Ogłoszenie</h2>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-muted-foreground">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          {/* Form */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-muted-foreground mb-1">Tytuł stanowiska</label>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="np. Angular Developer"
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-muted-foreground mb-1">Klient</label>
              <input
                value={clientName}
                onChange={(e) => setClientName(e.target.value)}
                placeholder="np. Nordea"
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-muted-foreground mb-1">Poziom seniority</label>
            <div className="flex gap-2">
              {["junior", "mid", "senior", "lead"].map((s) => (
                <button
                  key={s}
                  onClick={() => setSeniority(s)}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors capitalize ${
                    seniority === s
                      ? "bg-primary text-white"
                      : "border border-border text-muted-foreground hover:bg-muted"
                  }`}
                >
                  {s === "lead" ? "Lead" : s.charAt(0).toUpperCase() + s.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-muted-foreground mb-1">
              Wymagania / kluczowe umiejętności
            </label>
            <textarea
              value={requirements}
              onChange={(e) => setRequirements(e.target.value)}
              rows={4}
              placeholder="Angular 14+&#10;RxJS&#10;TypeScript&#10;Agile/Scrum&#10;Komunikatywny angielski"
              className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus-visible:ring-ring"
            />
            <p className="text-xs text-muted-foreground mt-0.5">Wpisz wymagania po jednym w linii</p>
          </div>

          {error && (
            <div className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          <button
            onClick={handleGenerate}
            disabled={!title.trim() || isLoading}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-primary text-white font-medium rounded-lg hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            {isLoading ? (
              <>
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Generuję...
              </>
            ) : (
              <>
                <Wand2 className="w-4 h-4" />
                Generuj ogłoszenie
              </>
            )}
          </button>

          {/* Generated output */}
          {generated && (
            <div className="border border-border rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 bg-muted border-b border-border dark:border-border">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Wygenerowane ogłoszenie
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={handleCopy}
                    className="flex items-center gap-1.5 px-2.5 py-1 text-xs border border-border rounded-lg hover:bg-card text-muted-foreground transition-colors"
                  >
                    {copied ? (
                      <><Check className="w-3.5 h-3.5 text-emerald-500" /> Skopiowano</>
                    ) : (
                      <><Copy className="w-3.5 h-3.5" /> Kopiuj</>
                    )}
                  </button>
                  <button
                    onClick={() => { onUse(generated); onClose(); }}
                    className="flex items-center gap-1.5 px-2.5 py-1 text-xs bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
                  >
                    Użyj jako opis
                  </button>
                </div>
              </div>
              <div className="p-4 max-h-72 overflow-y-auto">
                <pre className="text-xs text-foreground whitespace-pre-wrap font-sans leading-relaxed">
                  {generated}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Phase 4: AI criteria / scoring actions ──────────────────────────────────

function JobAIActions({ jobId, onDone }: { jobId: number; onDone: () => void }) {
  const [busy, setBusy] = useState<null | "criteria" | "recompute" | "embed-all">(null);
  const [last, setLast] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  const run = async (kind: "criteria" | "recompute" | "embed-all") => {
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
          `Embedding ofert: requested=${d.requested}, embedded=${d.embedded}, failed=${d.failed}`
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

  return (
    <div className="rounded-lg border border-dashed border-primary/30 dark:border-primary/90 bg-primary/10 dark:bg-primary/10 p-3">
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-xs font-semibold text-muted-foreground dark:text-muted-foreground mr-2">
          AI / Scoring:
        </span>
        <button
          onClick={() => setShowPreview(true)}
          disabled={!!busy}
          className="text-xs px-3 py-1.5 rounded-md bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50"
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
          title="Jednorazowo: wylicza embeddingi dla wszystkich ofert bez vector ID"
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

function MatchScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = pct >= 80 ? "bg-green-500" : pct >= 60 ? "bg-yellow-500" : "bg-destructive/100";
  const textColor = pct >= 80 ? "text-green-700" : pct >= 60 ? "text-yellow-700" : "text-destructive";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-muted dark:bg-muted rounded-full h-2 overflow-hidden">
        <div className={`h-2 rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-xs font-bold w-10 text-right ${textColor}`}>{pct}%</span>
    </div>
  );
}

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

function AIMatchingSection({ jobId, job }: { jobId: number; job: any }) {
  const queryClient = useQueryClient();
  const [emailTarget, setEmailTarget] = useState<any>(null);
  // Location filter — restricts matches to candidates whose location matches.
  // Pre-fill from the job's own location when it has one (rare for imported
  // jobs), otherwise the recruiter types a city (e.g. "Warszawa").
  const [locationFilter, setLocationFilter] = useState<string>(
    () => formatCandidateLocation(job?.location) ?? "",
  );

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["ai-matches", jobId, locationFilter.trim()],
    queryFn: () =>
      matchingApi
        .getMatches(jobId, { location: locationFilter.trim() || undefined })
        .then((r) => r.data),
    staleTime: 60_000,
  });

  const addToPipelineMutation = useMutation({
    mutationFn: ({ candidateId, jobId }: { candidateId: number; jobId: number }) =>
      api.post("/api/pipeline/move", { candidate_id: candidateId, job_id: jobId, stage: "sourced" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
    },
  });

  const matches = data?.matches ?? [];
  const searchType = data?.search_type;
  const requiredSkills = data?.required_skills ?? [];
  // Server echoes the effective location filter it applied (param, or the
  // job's own location). Non-empty → results are location-restricted.
  const locationActive = Boolean(data?.location_filter);

  return (
    <div className="space-y-4">
      {/* Phase 4: AI criteria + scoring actions */}
      <JobAIActions jobId={jobId} onDone={() => refetch()} />

      {/* Header info + location filter */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2 min-w-0 flex-wrap">
          <span className="text-sm text-muted-foreground whitespace-nowrap">
            {isLoading ? (
              "Wyszukiwanie..."
            ) : (
              <>
                Znaleziono <strong>{matches.length}</strong> pasujących kandydatów
              </>
            )}
          </span>
          {searchType === "semantic" && (
            <span className="text-[10px] px-2 py-0.5 bg-primary/15 text-primary rounded-full font-medium">Semantic AI</span>
          )}
          {searchType === "tag_fallback" && (
            <span className="text-[10px] px-2 py-0.5 bg-muted text-muted-foreground rounded-full font-medium">Tag-based</span>
          )}
          {locationActive && (
            <span className="text-[10px] px-2 py-0.5 bg-emerald-100 text-emerald-700 rounded-full font-medium inline-flex items-center gap-1">
              <MapPin className="w-3 h-3" /> {data?.location_filter}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <div className="w-52">
            <LocationInput
              value={locationFilter}
              onChange={setLocationFilter}
              placeholder="Lokalizacja (np. Warszawa)"
            />
          </div>
          <button onClick={() => refetch()} className="text-xs text-primary hover:underline whitespace-nowrap">
            Odśwież
          </button>
        </div>
      </div>

      {requiredSkills.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <span className="text-xs text-muted-foreground mr-1">Wymagane:</span>
          {requiredSkills.map((s: string) => (
            <span key={s} className="text-[11px] px-2 py-0.5 bg-primary/10 text-primary border border-primary/20 rounded-full">{s}</span>
          ))}
        </div>
      )}

      {isLoading ? (
        <div className="flex flex-col items-center py-16 text-muted-foreground gap-3">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-sm">Wyszukiwanie pasujących kandydatów...</p>
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
          <AlertCircle className="w-10 h-10 text-red-400" />
          <p className="text-sm">Błąd podczas wyszukiwania kandydatów</p>
          <button onClick={() => refetch()} className="text-sm text-primary hover:underline mt-1">Spróbuj ponownie</button>
        </div>
      ) : matches.length === 0 ? (
        <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
          <UserCheck className="w-12 h-12 opacity-30" />
          <p className="text-sm">
            {locationActive
              ? `Brak pasujących kandydatów w lokalizacji „${data?.location_filter}"`
              : "Brak pasujących kandydatów w bazie"}
          </p>
          <p className="text-xs text-muted-foreground">
            {locationActive
              ? "Zmień lub wyczyść filtr lokalizacji powyżej"
              : "Dodaj kandydatów do systemu i uruchom indeksowanie"}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {matches.map((match: any, idx: number) => {
            const c = match.candidate;
            const fullName = `${c.name} ${c.lastname}`.trim();
            const initials = fullName.split(" ").map((w: string) => w[0]).slice(0, 2).join("").toUpperCase();
            const AVATAR_COLORS = ["bg-primary","bg-violet-600","bg-emerald-600","bg-rose-500","bg-amber-500","bg-cyan-600"];
            const avatarColor = AVATAR_COLORS[(fullName.charCodeAt(0) + (fullName.charCodeAt(1) || 0)) % AVATAR_COLORS.length];

            return (
              <div key={c.id} className="flex items-start gap-4 p-4 bg-card dark:bg-muted rounded-xl border border-border dark:border-border hover:shadow-sm transition-shadow">
                {/* Rank */}
                <div className="flex-shrink-0 w-6 h-6 rounded-full bg-muted dark:bg-muted flex items-center justify-center text-xs font-bold text-muted-foreground">
                  {idx + 1}
                </div>

                {/* Avatar */}
                <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-semibold text-sm flex-shrink-0 ${avatarColor}`}>
                  {initials || "?"}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0 space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <Link href={`/candidates/${c.id}?${encodeJobBackRef(jobId).toString()}`} className="font-semibold text-foreground dark:text-foreground hover:text-primary text-sm">
                        {fullName}
                      </Link>
                      {c.competence_category && (
                        <p className="text-xs text-muted-foreground mt-0.5">{c.competence_category}</p>
                      )}
                      {formatCandidateLocation(c.location) && (
                        <p className="text-xs text-muted-foreground mt-0.5 inline-flex items-center gap-1">
                          <MapPin className="w-3 h-3 flex-shrink-0" />
                          {formatCandidateLocation(c.location)}
                        </p>
                      )}
                    </div>
                    <div className="w-32 flex-shrink-0">
                      <MatchScoreBar score={match.match_score} />
                    </div>
                  </div>

                  {/* Skills badges */}
                  {(match.matching_skills.length > 0 || match.gaps.length > 0) && (
                    <div className="flex flex-wrap gap-1.5">
                      {match.matching_skills.map((s: string) => (
                        <span key={s} className="text-[11px] px-2 py-0.5 bg-green-100 text-green-700 rounded-full font-medium">✓ {s}</span>
                      ))}
                      {match.gaps.map((s: string) => (
                        <span key={s} className="text-[11px] px-2 py-0.5 border border-red-300 text-destructive rounded-full">✗ {s}</span>
                      ))}
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={() => addToPipelineMutation.mutate({ candidateId: c.id, jobId })}
                      disabled={addToPipelineMutation.isPending}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50 transition-colors"
                    >
                      <Plus className="w-3 h-3" />
                      Dodaj do pipeline
                    </button>
                    <button
                      onClick={() => setEmailTarget(c)}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border text-muted-foreground rounded-lg hover:bg-muted transition-colors"
                    >
                      <Mail className="w-3 h-3" />
                      Wyślij wiadomość
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Email modal */}
      {emailTarget && (
        <EmailTemplateModal
          candidate={emailTarget}
          job={job}
          onClose={() => setEmailTarget(null)}
        />
      )}
    </div>
  );
}

// ── Recruitment type config ───────────────────────────────────────────────────

const RECRUITMENT_TYPE_CONFIG: Record<string, { label: string; color: string }> = {
  body_leasing: { label: "Body Leasing", color: "bg-primary/15 text-primary" },
  sales_project: { label: "Sprzedaż",    color: "bg-green-100 text-green-700" },
  tender:        { label: "Przetarg",    color: "bg-orange-100 text-orange-700" },
};

// ── Main Page ─────────────────────────────────────────────────────────────────

type PageTab =
  | "pipeline"
  | "history"
  | "ai-matching"
  | "manual-search"
  | "portals"
  | "champion"
  | "questions"
  | "chat";

export default function JobDetailPage() {
  const { id } = useParams();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const openTab = useTabsStore((s) => s.openTab);
  const queryClient = useQueryClient();
  const [showAIWriter, setShowAIWriter] = useState(false);
  const [showEditJob, setShowEditJob] = useState(false);
  const [showInviteLink, setShowInviteLink] = useState(false);
  const [showAddCandidates, setShowAddCandidates] = useState(false);
  const [activeTab, setActiveTab] = useState<PageTab>("pipeline");
  const [proposalsHighlight, setProposalsHighlight] = useState(false);

  // Deep link z notyfikacji ?tab=chat → otwórz zakładkę Chat od razu.
  useEffect(() => {
    if (searchParams?.get("tab") === "chat") {
      setActiveTab("chat");
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
  // switch to the AI matching tab, scroll to the widget, and glow the panel
  // briefly so the recruiter sees AI has taken over.
  useEffect(() => {
    if (searchParams?.get("highlight") !== "ai-proposals") return;
    setActiveTab("ai-matching");
    setProposalsHighlight(true);
    // Let React paint the new tab before scrolling.
    const scrollTimer = window.setTimeout(() => {
      const el = document.getElementById("ai-proposals-section");
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 150);
    const glowTimer = window.setTimeout(() => setProposalsHighlight(false), 3000);
    const cleanupTimer = window.setTimeout(() => {
      if (pathname) router.replace(pathname, { scroll: false });
    }, 3200);
    return () => {
      window.clearTimeout(scrollTimer);
      window.clearTimeout(glowTimer);
      window.clearTimeout(cleanupTimer);
    };
  }, [searchParams, pathname, router]);

  const { data: job, isLoading: jobLoading } = useQuery({
    queryKey: ["job", id],
    queryFn: () => api.get(`/api/jobs/${id}`).then((r) => r.data),
  });

  const { data: kanban, isLoading: kanbanLoading } = useQuery({
    queryKey: ["kanban", id],
    queryFn: () => api.get(`/api/pipeline/kanban/${id}`).then((r) => r.data),
  });

  // Auto-open tab when job data loads
  useEffect(() => {
    if (job) {
      openTab("job", Number(id), job.title);
    }
  }, [job, id, openTab]);

  const handleUseDescription = useCallback(async (description: string) => {
    try {
      await api.patch(`/api/jobs/${id}`, { description });
      queryClient.invalidateQueries({ queryKey: ["job", id] });
    } catch (e) {
      // silent — user can copy manually
    }
  }, [id, queryClient]);

  if (jobLoading) return <div className="p-6 text-muted-foreground">Ładowanie...</div>;
  if (!job) return <div className="p-6 text-destructive">Nie znaleziono oferty</div>;

  return (
    <div className="space-y-6">
      <Link href="/jobs" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="w-4 h-4" /> Wróć do ofert
      </Link>

      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6">
        <div className="flex items-start justify-between flex-wrap gap-3">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-bold">{job.title}</h1>
              {job.reference_number && (
                <span
                  className="font-mono text-xs px-2 py-0.5 rounded-md bg-muted text-muted-foreground border border-border"
                  title="Numer referencyjny oferty"
                >
                  {job.reference_number}
                </span>
              )}
            </div>
            <div className="flex gap-4 mt-2 text-sm text-muted-foreground">
              {job.location && (
                <span className="flex items-center gap-1">
                  <MapPin className="w-3.5 h-3.5" /> {job.location}
                </span>
              )}
              {(job.salary_min || job.salary_max) && (
                <span className="flex items-center gap-1">
                  <Banknote className="w-3.5 h-3.5" />
                  {job.salary_min?.toLocaleString()}–{job.salary_max?.toLocaleString()} PLN
                </span>
              )}
              {job.deadline && (
                <span className="flex items-center gap-1">
                  <Calendar className="w-3.5 h-3.5" /> {formatDate(job.deadline)}
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0 flex-wrap">
            <ActiveViewers
              resourceType="job"
              resourceId={Number.isFinite(Number(id)) ? Number(id) : null}
              className="mr-1"
            />
            <button
              onClick={() => setShowAddCandidates(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors shadow-sm"
              data-testid="open-add-candidates"
              title="Wyszukaj kandydatów po imieniu i nazwisku i dodaj ich do pipeline"
            >
              <UserPlus className="w-3.5 h-3.5" />
              Dodaj kandydata
            </button>
            <button
              onClick={() => setShowEditJob(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-card dark:bg-muted border border-border dark:border-border text-foreground text-sm font-medium rounded-lg hover:bg-muted transition-colors shadow-sm"
            >
              <PencilLine className="w-3.5 h-3.5 text-muted-foreground" />
              Edytuj
            </button>
            <button
              onClick={() => setShowAIWriter(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors shadow-sm"
            >
              <Wand2 className="w-3.5 h-3.5" />
              AI Ogłoszenie
            </button>
            {job.status === "published" && (
              <button
                onClick={() => setShowInviteLink(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-card dark:bg-muted border border-border dark:border-border text-foreground text-sm font-medium rounded-lg hover:bg-muted transition-colors shadow-sm"
                title="Wygeneruj indywidualny link aplikacyjny dla tej oferty"
              >
                <Link2 className="w-3.5 h-3.5 text-primary" />
                Wygeneruj link
              </button>
            )}
            {job.recruitment_type && RECRUITMENT_TYPE_CONFIG[job.recruitment_type] && (
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${RECRUITMENT_TYPE_CONFIG[job.recruitment_type].color}`}>
                {RECRUITMENT_TYPE_CONFIG[job.recruitment_type].label}
              </span>
            )}
            <span className={`px-3 py-1 rounded-full text-sm font-medium ${
              job.status === "published" ? "bg-green-100 text-green-700" :
              job.status === "draft" ? "bg-muted text-muted-foreground" : "bg-destructive/15 text-destructive"
            }`}>
              {job.status}
            </span>
          </div>
        </div>

        <div className="mt-4 border-t border-border dark:border-border pt-4">
          <JobOwnershipPanel
            jobId={Number(id)}
            jobTitle={job.title}
            primaryOwner={job.primary_owner ?? null}
            collaborators={job.collaborators ?? []}
          />
        </div>

        {job.hiring_manager_name && (
          <div className="mt-3 flex items-center gap-2 text-sm">
            <span className="text-xs uppercase tracking-wider text-muted-foreground">
              Hiring manager (klient):
            </span>
            {job.hiring_manager_contact_id && job.client_id ? (
              <Link
                href={`/clients/${job.client_id}?tab=zespol`}
                className="font-medium text-violet-600 hover:underline"
              >
                {job.hiring_manager_name}
              </Link>
            ) : (
              <span className="font-medium">{job.hiring_manager_name}</span>
            )}
          </div>
        )}

        {job.description && (
          <div className="mt-4 text-sm text-muted-foreground whitespace-pre-line">{job.description}</div>
        )}
      </div>

      {/* Edit Job Modal */}
      {showEditJob && job && (
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
      {showAIWriter && (
        <AIJobWriterModal
          job={job}
          onClose={() => setShowAIWriter(false)}
          onUse={handleUseDescription}
        />
      )}

      {/* Invite Link Modal — pre-selected current job */}
      <GenerateInviteLinkV2
        open={showInviteLink}
        onOpenChange={setShowInviteLink}
        defaultJobId={Number(id)}
      />

      {/* Quick search + bulk-add candidates to this job */}
      <AddCandidatesQuickModal
        open={showAddCandidates}
        onClose={() => setShowAddCandidates(false)}
        jobId={Number(id)}
        jobTitle={job.title}
      />

      {/* Tabs */}
      <div className="border-b border-border dark:border-border">
        <div className="flex gap-1">
          <button
            onClick={() => setActiveTab("pipeline")}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors",
              activeTab === "pipeline"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            Pipeline kandydatów
          </button>
          <button
            onClick={() => setActiveTab("history")}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors",
              activeTab === "history"
                ? "border-amber-600 text-amber-600"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
            data-testid="tab-history"
          >
            <History className="w-4 h-4" />
            Historia
          </button>
          <button
            onClick={() => setActiveTab("ai-matching")}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors",
              activeTab === "ai-matching"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            <Sparkles className="w-4 h-4" />
            AI Matching
          </button>
          <button
            onClick={() => setActiveTab("manual-search")}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors",
              activeTab === "manual-search"
                ? "border-violet-600 text-violet-600"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
            data-testid="tab-manual-search"
          >
            <Search className="w-4 h-4" />
            Wyszukaj manualnie
          </button>
          <button
            onClick={() => setActiveTab("portals")}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors",
              activeTab === "portals"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            Portale ogłoszeniowe
          </button>
          <button
            onClick={() => setActiveTab("champion")}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors",
              activeTab === "champion"
                ? "border-purple-600 text-purple-600"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
            data-testid="tab-champion"
          >
            <Sparkles className="w-4 h-4" />
            Profil Championa
          </button>
          <button
            onClick={() => setActiveTab("questions")}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors",
              activeTab === "questions"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
            data-testid="tab-questions"
          >
            Baza pytań
          </button>
          <button
            onClick={() => setActiveTab("chat")}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors relative",
              activeTab === "chat"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
            data-testid="tab-chat"
          >
            <MessageCircle className="w-4 h-4" />
            Chat
            {chatUnread && chatUnread.unread_count > 0 && (
              <span className="ml-1 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-semibold rounded-full bg-destructive/100 text-white">
                {chatUnread.unread_count > 99 ? "99+" : chatUnread.unread_count}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Tab Content */}
      {activeTab === "pipeline" && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm text-muted-foreground">
              Dodaj kandydatów do tej rekrutacji przeszukując bazę po imieniu i nazwisku.
            </p>
            <button
              onClick={() => setShowAddCandidates(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors shadow-sm"
              data-testid="open-add-candidates-pipeline"
            >
              <UserPlus className="w-3.5 h-3.5" />
              Dodaj kandydata
            </button>
          </div>
          {kanbanLoading ? (
            <div className="text-muted-foreground">Ładowanie pipeline...</div>
          ) : (
            <KanbanBoardV2 columns={kanban?.columns ?? []} jobId={Number(id)} />
          )}
        </div>
      )}

      {activeTab === "history" && (
        <RequestHistorySection
          jobId={Number(id)}
          clientId={job?.client_id ?? null}
        />
      )}

      {activeTab === "ai-matching" && (
        <div className="space-y-4">
          <HistoricalCandidatesSection jobId={Number(id)} />
          <div
            className={cn(
              "rounded-lg transition-shadow",
              proposalsHighlight &&
                "ring-2 ring-violet-400 ring-offset-2 ring-offset-white dark:ring-offset-gray-900 shadow-lg",
            )}
          >
            <SuggestedCandidatesWidget jobId={Number(id)} />
          </div>
          <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6">
            <div className="flex items-center gap-2 mb-6">
              <Sparkles className="w-5 h-5 text-primary" />
              <h2 className="text-lg font-semibold">Klasyczne AI Matching (legacy)</h2>
              <span className="text-xs text-muted-foreground ml-1">Prosty semantic + tag fallback</span>
            </div>
            <AIMatchingSection jobId={Number(id)} job={job} />
          </div>
        </div>
      )}

      {activeTab === "manual-search" && job && (
        <ManualSearchTab
          jobId={Number(id)}
          job={job}
          onBulkAdded={() =>
            queryClient.invalidateQueries({ queryKey: ["kanban", id] })
          }
        />
      )}

      {activeTab === "portals" && (
        <PostingsSection jobId={Number(id)} />
      )}

      {activeTab === "champion" && (
        <ChampionProfileEditor
          jobId={Number(id)}
          clientId={job?.client_id ?? null}
        />
      )}

      {activeTab === "questions" && (
        <QuestionBankTab
          jobId={Number(id)}
          clientId={job?.client_id ?? null}
        />
      )}

      {activeTab === "chat" && <JobChatTab jobId={Number(id)} />}
    </div>
  );
}

// ── Manual search tab ────────────────────────────────────────────────────────

interface JobLite {
  id: number;
  title: string;
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
}

/**
 * Embeds CandidateSearchView with the job's metadata pre-filled into the
 * filters. The user lands on a results list already scoped to the job and
 * can bulk-add hits straight into the pipeline. Already-added candidates
 * are excluded server-side via ``exclude_in_job_id``.
 */
function ManualSearchTab({ jobId, job, onBulkAdded }: ManualSearchTabProps) {
  const skillsFromList = (raw: unknown): string[] => {
    if (!Array.isArray(raw)) return [];
    return raw
      .map((s) => {
        if (typeof s === "string") return s;
        if (s && typeof s === "object" && "name" in s) {
          const name = (s as { name?: unknown }).name;
          return typeof name === "string" ? name : null;
        }
        return null;
      })
      .filter((s): s is string => Boolean(s))
      .slice(0, 10);
  };

  const initial: Partial<CandidateSearchRequest> = {
    q: job.title,
    competence_category_ids: job.competence_category_id
      ? [job.competence_category_id]
      : [],
    skills_must: skillsFromList(job.must_skills),
    skills_any: skillsFromList(job.nice_skills),
    salary_min: job.salary_min ?? null,
    salary_max: job.salary_max ?? null,
    location_cities: job.location ? [job.location] : [],
    sort: "relevance",
  };

  return (
    <CandidateSearchView
      initial={initial}
      addToJob={{ id: jobId, title: job.title }}
      onBulkAdded={onBulkAdded}
    />
  );
}
