"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import api, { postingsApi, aiWriterApi, matchingApi, phase3Api, recommendationsApi } from "@/lib/api";
import { KanbanBoard } from "@/components/KanbanBoard";
import { EditJobModal } from "@/components/AppShell";
import { SuggestedCandidatesWidget } from "@/components/SuggestedCandidatesWidget";
import { ArrowLeft, MapPin, Banknote, Calendar, Globe, Trash2, ExternalLink, Plus, Radio, Wand2, X, Copy, Check, PencilLine, Sparkles, UserCheck, AlertCircle, Mail } from "lucide-react";
import { DeleteButton } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import Link from "next/link";
import { formatDate } from "@/lib/utils";
import { useTabsStore } from "@/store/tabs";

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
  linkedin:    { label: "LinkedIn",     color: "bg-blue-100 text-blue-700",      dotColor: "bg-blue-500" },
  nofluffjobs: { label: "NoFluffJobs",  color: "bg-red-100 text-red-700",        dotColor: "bg-red-500" },
  bulldogjob:  { label: "BulldogJob",   color: "bg-yellow-100 text-yellow-700",  dotColor: "bg-yellow-500" },
};

const ALL_PORTALS: Portal[] = ["pracuj_pl", "justjoinit", "linkedin", "nofluffjobs", "bulldogjob"];

const STATUS_CONFIG: Record<PostingStatus, { label: string; className: string }> = {
  draft:     { label: "Szkic",       className: "bg-gray-100 text-gray-600" },
  published: { label: "Aktywne",     className: "bg-green-100 text-green-700" },
  expired:   { label: "Wygasłe",     className: "bg-red-100 text-red-600" },
  removed:   { label: "Usunięte",    className: "bg-gray-200 text-gray-500" },
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
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
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
                    ? "opacity-50 cursor-not-allowed border-gray-100 bg-gray-50"
                    : isSelected
                    ? "border-blue-400 bg-blue-50"
                    : "border-gray-200 hover:border-gray-300"
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
          <label className="text-sm text-gray-600 whitespace-nowrap">Czas trwania:</label>
          <select
            className="text-sm border border-gray-200 rounded-lg px-3 py-1.5"
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
            className="flex-1 px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50"
          >
            Anuluj
          </button>
          <button
            onClick={() => selected.length > 0 && publishMutation.mutate(selected)}
            disabled={selected.length === 0 || publishMutation.isPending}
            className="flex-1 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
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

  if (isLoading) return <div className="text-gray-400 text-sm">Ładowanie publikacji...</div>;

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Globe className="w-5 h-5 text-blue-500" />
          <h2 className="text-lg font-semibold">Portale ogłoszeniowe</h2>
          <span className="text-xs text-gray-400 ml-1">({postings.length})</span>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => publishAllMutation.mutate()}
            disabled={publishAllMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 text-gray-600 disabled:opacity-50"
          >
            <Radio className="w-3.5 h-3.5" />
            Publikuj na wszystkich
          </button>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
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
        <div className="text-center py-8 text-gray-400">
          <Globe className="w-10 h-10 mx-auto mb-2 opacity-30" />
          <p className="text-sm">Brak publikacji. Opublikuj ogłoszenie na portalach rekrutacyjnych.</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 dark:border-gray-700">
                <th className="text-left py-2 px-3 text-gray-500 font-medium">Portal</th>
                <th className="text-left py-2 px-3 text-gray-500 font-medium">Status</th>
                <th className="text-left py-2 px-3 text-gray-500 font-medium">Data publ.</th>
                <th className="text-left py-2 px-3 text-gray-500 font-medium">Wygaśnięcie</th>
                <th className="text-right py-2 px-3 text-gray-500 font-medium">Wyświetlenia</th>
                <th className="text-right py-2 px-3 text-gray-500 font-medium">Aplikacje</th>
                <th className="text-center py-2 px-3 text-gray-500 font-medium">Link</th>
                <th className="text-center py-2 px-3 text-gray-500 font-medium">Akcje</th>
              </tr>
            </thead>
            <tbody>
              {postings.map((posting) => {
                const portalCfg = PORTAL_CONFIG[posting.portal];
                const statusCfg = STATUS_CONFIG[posting.status];
                return (
                  <tr key={posting.id} className="border-b border-gray-50 hover:bg-gray-50">
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
                    <td className="py-2.5 px-3 text-gray-500">
                      {posting.published_at ? formatDate(posting.published_at) : "—"}
                    </td>
                    <td className="py-2.5 px-3 text-gray-500">
                      {posting.expires_at ? formatDate(posting.expires_at) : "—"}
                    </td>
                    <td className="py-2.5 px-3 text-right font-medium">
                      {posting.views.toLocaleString()}
                    </td>
                    <td className="py-2.5 px-3 text-right font-medium text-blue-600">
                      {posting.applications}
                    </td>
                    <td className="py-2.5 px-3 text-center">
                      {posting.url ? (
                        <a
                          href={posting.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-500 hover:text-blue-700 inline-flex items-center gap-1"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      ) : (
                        <span className="text-gray-300">—</span>
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
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl my-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <Wand2 className="w-5 h-5 text-blue-600" />
            <h2 className="text-lg font-bold text-gray-900">AI Ogłoszenie</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          {/* Form */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Tytuł stanowiska</label>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="np. Angular Developer"
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Klient</label>
              <input
                value={clientName}
                onChange={(e) => setClientName(e.target.value)}
                placeholder="np. Nordea"
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">Poziom seniority</label>
            <div className="flex gap-2">
              {["junior", "mid", "senior", "lead"].map((s) => (
                <button
                  key={s}
                  onClick={() => setSeniority(s)}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors capitalize ${
                    seniority === s
                      ? "bg-blue-600 text-white"
                      : "border border-gray-200 text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  {s === "lead" ? "Lead" : s.charAt(0).toUpperCase() + s.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">
              Wymagania / kluczowe umiejętności
            </label>
            <textarea
              value={requirements}
              onChange={(e) => setRequirements(e.target.value)}
              rows={4}
              placeholder="Angular 14+&#10;RxJS&#10;TypeScript&#10;Agile/Scrum&#10;Komunikatywny angielski"
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p className="text-xs text-gray-400 mt-0.5">Wpisz wymagania po jednym w linii</p>
          </div>

          {error && (
            <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          <button
            onClick={handleGenerate}
            disabled={!title.trim() || isLoading}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
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
            <div className="border border-gray-200 rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 bg-gray-50 border-b border-gray-200 dark:border-gray-700">
                <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
                  Wygenerowane ogłoszenie
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={handleCopy}
                    className="flex items-center gap-1.5 px-2.5 py-1 text-xs border border-gray-200 rounded-lg hover:bg-white text-gray-600 transition-colors"
                  >
                    {copied ? (
                      <><Check className="w-3.5 h-3.5 text-emerald-500" /> Skopiowano</>
                    ) : (
                      <><Copy className="w-3.5 h-3.5" /> Kopiuj</>
                    )}
                  </button>
                  <button
                    onClick={() => { onUse(generated); onClose(); }}
                    className="flex items-center gap-1.5 px-2.5 py-1 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                  >
                    Użyj jako opis
                  </button>
                </div>
              </div>
              <div className="p-4 max-h-72 overflow-y-auto">
                <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
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
    <div className="rounded-lg border border-dashed border-blue-300 dark:border-blue-700 bg-blue-50/50 dark:bg-blue-900/10 p-3">
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-xs font-semibold text-gray-600 dark:text-gray-300 mr-2">
          AI / Scoring:
        </span>
        <button
          onClick={() => run("criteria")}
          disabled={!!busy}
          className="text-xs px-3 py-1.5 rounded-md bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50"
          data-testid="refresh-criteria"
        >
          {busy === "criteria" ? "Generuję…" : "✨ Odśwież kryteria (AI)"}
        </button>
        <button
          onClick={() => run("recompute")}
          disabled={!!busy}
          className="text-xs px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
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
        <div className="mt-2 text-xs text-gray-600 dark:text-gray-300">{last}</div>
      )}
    </div>
  );
}

// ── AI Matching Section ───────────────────────────────────────────────────────

function MatchScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = pct >= 80 ? "bg-green-500" : pct >= 60 ? "bg-yellow-500" : "bg-red-500";
  const textColor = pct >= 80 ? "text-green-700" : pct >= 60 ? "text-yellow-700" : "text-red-600";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-100 dark:bg-gray-700 rounded-full h-2 overflow-hidden">
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
  const subject = `Oferta pracy: ${job.title}`;
  const body = `Dzień dobry ${candidate.name},\n\nZwracam się do Pana/Pani w imieniu B2B.net S.A. z ofertą stanowiska:\n\n**${job.title}**\n\nNa podstawie Pana/Pani profilu uważam, że ta rola idealnie odpowiada Pana/Pani kompetencjom.\n\nCzy byłby Pan/Pani zainteresowany/a rozmową wstępną?\n\nPozdrawiam,\nZespół Rekrutacji B2B.net`;

  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(`Temat: ${subject}\n\n${body}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const mailtoLink = `mailto:${candidate.email || ""}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-bold text-gray-900 dark:text-gray-100">Wyślij wiadomość do {fullName}</h3>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase">Temat</label>
            <p className="text-sm mt-1 p-2 bg-gray-50 dark:bg-gray-700 rounded">{subject}</p>
          </div>
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase">Treść</label>
            <pre className="text-sm mt-1 p-3 bg-gray-50 dark:bg-gray-700 rounded whitespace-pre-wrap font-sans">{body}</pre>
          </div>
          <div className="flex gap-2 pt-2">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-3 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50"
            >
              {copied ? <><Check className="w-4 h-4 text-green-500" /> Skopiowano</> : <><Copy className="w-4 h-4" /> Kopiuj</>}
            </button>
            {candidate.email && (
              <a
                href={mailtoLink}
                className="flex items-center gap-1.5 px-3 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
              >
                <Mail className="w-4 h-4" />
                Otwórz w kliencie email
              </a>
            )}
            <button onClick={onClose} className="ml-auto px-3 py-2 text-sm text-gray-500 hover:text-gray-700">
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

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["ai-matches", jobId],
    queryFn: () => matchingApi.getMatches(jobId, 10).then((r) => r.data),
    staleTime: 60_000,
  });

  const addToPipelineMutation = useMutation({
    mutationFn: ({ candidateId, jobId }: { candidateId: number; jobId: number }) =>
      api.post("/api/pipeline/move", { candidate_id: candidateId, job_id: jobId, stage: "sourced" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
    },
  });

  if (isLoading) {
    return (
      <div className="flex flex-col items-center py-16 text-gray-400 gap-3">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-sm">Wyszukiwanie pasujących kandydatów...</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center py-12 text-gray-400 gap-2">
        <AlertCircle className="w-10 h-10 text-red-400" />
        <p className="text-sm">Błąd podczas wyszukiwania kandydatów</p>
        <button onClick={() => refetch()} className="text-sm text-blue-600 hover:underline mt-1">Spróbuj ponownie</button>
      </div>
    );
  }

  const matches = data?.matches ?? [];
  const searchType = data?.search_type;
  const requiredSkills = data?.required_skills ?? [];

  return (
    <div className="space-y-4">
      {/* Phase 4: AI criteria + scoring actions */}
      <JobAIActions jobId={jobId} onDone={() => refetch()} />

      {/* Header info */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500">
            Znaleziono <strong>{matches.length}</strong> pasujących kandydatów
          </span>
          {searchType === "semantic" && (
            <span className="text-[10px] px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full font-medium">Semantic AI</span>
          )}
          {searchType === "tag_fallback" && (
            <span className="text-[10px] px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full font-medium">Tag-based</span>
          )}
        </div>
        <button onClick={() => refetch()} className="text-xs text-blue-600 hover:underline">
          Odśwież
        </button>
      </div>

      {requiredSkills.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <span className="text-xs text-gray-500 mr-1">Wymagane:</span>
          {requiredSkills.map((s: string) => (
            <span key={s} className="text-[11px] px-2 py-0.5 bg-blue-50 text-blue-700 border border-blue-200 rounded-full">{s}</span>
          ))}
        </div>
      )}

      {matches.length === 0 ? (
        <div className="flex flex-col items-center py-12 text-gray-400 gap-2">
          <UserCheck className="w-12 h-12 opacity-30" />
          <p className="text-sm">Brak pasujących kandydatów w bazie</p>
          <p className="text-xs text-gray-400">Dodaj kandydatów do systemu i uruchom indeksowanie</p>
        </div>
      ) : (
        <div className="space-y-3">
          {matches.map((match: any, idx: number) => {
            const c = match.candidate;
            const fullName = `${c.name} ${c.lastname}`.trim();
            const initials = fullName.split(" ").map((w: string) => w[0]).slice(0, 2).join("").toUpperCase();
            const AVATAR_COLORS = ["bg-blue-600","bg-violet-600","bg-emerald-600","bg-rose-500","bg-amber-500","bg-cyan-600"];
            const avatarColor = AVATAR_COLORS[(fullName.charCodeAt(0) + (fullName.charCodeAt(1) || 0)) % AVATAR_COLORS.length];

            return (
              <div key={c.id} className="flex items-start gap-4 p-4 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 hover:shadow-sm transition-shadow">
                {/* Rank */}
                <div className="flex-shrink-0 w-6 h-6 rounded-full bg-gray-100 dark:bg-gray-700 flex items-center justify-center text-xs font-bold text-gray-500">
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
                      <Link href={`/candidates/${c.id}`} className="font-semibold text-gray-900 dark:text-gray-100 hover:text-blue-600 text-sm">
                        {fullName}
                      </Link>
                      {c.competence_category && (
                        <p className="text-xs text-gray-500 mt-0.5">{c.competence_category}</p>
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
                        <span key={s} className="text-[11px] px-2 py-0.5 border border-red-300 text-red-500 rounded-full">✗ {s}</span>
                      ))}
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={() => addToPipelineMutation.mutate({ candidateId: c.id, jobId })}
                      disabled={addToPipelineMutation.isPending}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
                    >
                      <Plus className="w-3 h-3" />
                      Dodaj do pipeline
                    </button>
                    <button
                      onClick={() => setEmailTarget(c)}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-gray-200 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
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
  body_leasing: { label: "Body Leasing", color: "bg-blue-100 text-blue-700" },
  sales_project: { label: "Sprzedaż",    color: "bg-green-100 text-green-700" },
  tender:        { label: "Przetarg",    color: "bg-orange-100 text-orange-700" },
};

// ── Main Page ─────────────────────────────────────────────────────────────────

type PageTab = "pipeline" | "ai-matching" | "portals";

export default function JobDetailPage() {
  const { id } = useParams();
  const openTab = useTabsStore((s) => s.openTab);
  const queryClient = useQueryClient();
  const [showAIWriter, setShowAIWriter] = useState(false);
  const [showEditJob, setShowEditJob] = useState(false);
  const [activeTab, setActiveTab] = useState<PageTab>("pipeline");

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

  if (jobLoading) return <div className="p-6 text-gray-400">Ładowanie...</div>;
  if (!job) return <div className="p-6 text-red-500">Nie znaleziono oferty</div>;

  return (
    <div className="space-y-6">
      <Link href="/jobs" className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800">
        <ArrowLeft className="w-4 h-4" /> Wróć do ofert
      </Link>

      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
        <div className="flex items-start justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold">{job.title}</h1>
            <div className="flex gap-4 mt-2 text-sm text-gray-500">
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
            <button
              onClick={() => setShowEditJob(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors shadow-sm"
            >
              <PencilLine className="w-3.5 h-3.5 text-gray-500" />
              Edytuj
            </button>
            <button
              onClick={() => setShowAIWriter(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
            >
              <Wand2 className="w-3.5 h-3.5" />
              AI Ogłoszenie
            </button>
            {job.recruitment_type && RECRUITMENT_TYPE_CONFIG[job.recruitment_type] && (
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${RECRUITMENT_TYPE_CONFIG[job.recruitment_type].color}`}>
                {RECRUITMENT_TYPE_CONFIG[job.recruitment_type].label}
              </span>
            )}
            <span className={`px-3 py-1 rounded-full text-sm font-medium ${
              job.status === "published" ? "bg-green-100 text-green-700" :
              job.status === "draft" ? "bg-gray-100 text-gray-600" : "bg-red-100 text-red-700"
            }`}>
              {job.status}
            </span>
          </div>
        </div>

        {job.description && (
          <div className="mt-4 text-sm text-gray-600 whitespace-pre-line">{job.description}</div>
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

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-gray-700">
        <div className="flex gap-1">
          <button
            onClick={() => setActiveTab("pipeline")}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors",
              activeTab === "pipeline"
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            )}
          >
            Pipeline kandydatów
          </button>
          <button
            onClick={() => setActiveTab("ai-matching")}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors",
              activeTab === "ai-matching"
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            )}
          >
            <Sparkles className="w-4 h-4" />
            AI Matching
          </button>
          <button
            onClick={() => setActiveTab("portals")}
            className={cn(
              "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors",
              activeTab === "portals"
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            )}
          >
            Portale ogłoszeniowe
          </button>
        </div>
      </div>

      {/* Tab Content */}
      {activeTab === "pipeline" && (
        <div>
          {kanbanLoading ? (
            <div className="text-gray-400">Ładowanie pipeline...</div>
          ) : (
            <KanbanBoard columns={kanban?.columns ?? []} jobId={Number(id)} />
          )}
        </div>
      )}

      {activeTab === "ai-matching" && (
        <div className="space-y-4">
          <SuggestedCandidatesWidget jobId={Number(id)} />
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
            <div className="flex items-center gap-2 mb-6">
              <Sparkles className="w-5 h-5 text-blue-500" />
              <h2 className="text-lg font-semibold">Klasyczne AI Matching (legacy)</h2>
              <span className="text-xs text-gray-400 ml-1">Prosty semantic + tag fallback</span>
            </div>
            <AIMatchingSection jobId={Number(id)} job={job} />
          </div>
        </div>
      )}

      {activeTab === "portals" && (
        <PostingsSection jobId={Number(id)} />
      )}
    </div>
  );
}
