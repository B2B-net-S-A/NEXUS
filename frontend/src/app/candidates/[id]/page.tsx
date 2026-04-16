"use client";

import { useState, useEffect, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  ArrowLeft,
  MapPin,
  Mail,
  Phone,
  Briefcase,
  Calendar,
  Tag,
  User,
  Clock,
  FileText,
  History,
  Activity,
  MessageSquare,
  Info,
  Sparkles,
  ChevronDown,
  ChevronUp,
  UserPlus,
  PencilLine,
  Star,
  GitBranch,
  StickyNote,
  Upload,
  Linkedin,
  AlertCircle,
  Send,
  PhoneCall,
  PhoneIncoming,
  PhoneOutgoing,
  PhoneMissed,
  Plus,
  X,
  BookOpen,
  CheckCircle2,
  Printer,
} from "lucide-react";
import { SendEmailModal } from "@/components/SendEmailModal";
import { CVGeneratorModal } from "@/components/CVGeneratorModal";
import { EditCandidateModal } from "@/components/AppShell";
import { SuggestedJobsWidget } from "@/components/SuggestedJobsWidget";
import { CandidatePipelinesWidget } from "@/components/CandidatePipelinesWidget";
import Link from "next/link";
import { formatDate, formatCurrency, formatRelativeTime, cn } from "@/lib/utils";
import { useTabsStore } from "@/store/tabs";
import { prepKitApi, talentPoolsApi } from "@/lib/api";

// ── Constants ───────────────────────────────────────────────────────────────

const SKILL_LEVEL_COLORS: Record<string, string> = {
  expert: "bg-blue-100 text-blue-700",
  senior: "bg-green-100 text-green-700",
  mid: "bg-yellow-100 text-yellow-700",
  junior: "bg-gray-100 text-gray-600",
};

const STATUS_COLORS: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-700 border border-emerald-200",
  passive: "bg-amber-100 text-amber-700 border border-amber-200",
  blacklisted: "bg-red-100 text-red-700 border border-red-200",
};

const STATUS_LABELS: Record<string, string> = {
  active: "Aktywny",
  passive: "Pasywny",
  blacklisted: "Zablokowany",
};

const SOURCE_COLORS: Record<string, string> = {
  linkedin: "bg-blue-600 text-white",
  pracuj: "bg-green-600 text-white",
  jjit: "bg-pink-500 text-white",
  referral: "bg-purple-500 text-white",
  database: "bg-gray-600 text-white",
  manual: "bg-gray-400 text-white",
};

const SOURCE_LABELS: Record<string, string> = {
  linkedin: "LinkedIn",
  pracuj: "Pracuj.pl",
  jjit: "JustJoin.it",
  referral: "Polecenie",
  database: "Baza ATS",
  manual: "Manualnie",
};

const TIMELINE_ICONS: Record<string, React.ReactNode> = {
  note: <StickyNote className="w-3.5 h-3.5" />,
  stage_change: <GitBranch className="w-3.5 h-3.5" />,
  activity: <Activity className="w-3.5 h-3.5" />,
  user_activity: <User className="w-3.5 h-3.5" />,
};

const TIMELINE_COLORS: Record<string, string> = {
  note: "bg-blue-500",
  stage_change: "bg-emerald-500",
  activity: "bg-purple-500",
  user_activity: "bg-orange-400",
};

const TIMELINE_ACTION_LABELS: Record<string, string> = {
  candidate_added: "Dodano kandydata",
  stage_changed: "Zmiana etapu",
  call_made: "Rozmowa telefoniczna",
  screening_done: "Screening",
  interview_scheduled: "Umówiono rozmowę",
  placement_closed: "Placement zamknięty",
  note_added: "Dodano notatkę",
  cv_uploaded: "Wgranie CV",
  created: "Dodano do systemu",
  updated: "Zaktualizowano profil",
  hired: "Zatrudniono",
  stage_change: "Zmiana etapu",
};

// ── Avatar helper ────────────────────────────────────────────────────────────

const AVATAR_COLORS = [
  "bg-blue-600", "bg-violet-600", "bg-emerald-600",
  "bg-rose-500", "bg-amber-500", "bg-cyan-600",
];

function getAvatarColor(name: string): string {
  const code = name.charCodeAt(0) + (name.charCodeAt(1) || 0);
  return AVATAR_COLORS[code % AVATAR_COLORS.length];
}

// ── Types ────────────────────────────────────────────────────────────────────

type TabId = "profil" | "timeline" | "rekrutacje" | "screeningi" | "pliki" | "notatki" | "rozmowy";

// ── Call types ───────────────────────────────────────────────────────────────

interface CallRecord {
  id: number;
  candidate_id: number;
  user_id: number | null;
  direction: "inbound" | "outbound";
  duration_seconds: number | null;
  status: "completed" | "missed" | "voicemail" | "failed";
  transcript: string | null;
  summary: string | null;
  recording_url: string | null;
  cloudtalk_call_id: string | null;
  created_at: string;
}

function formatCallDuration(seconds: number | null): string {
  if (!seconds) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

const CALL_STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  completed: { label: "Zrealizowana", color: "bg-green-100 text-green-700" },
  missed:    { label: "Nieodebrana",  color: "bg-red-100 text-red-600" },
  voicemail: { label: "Poczta głos.", color: "bg-amber-100 text-amber-700" },
  failed:    { label: "Błąd",         color: "bg-gray-100 text-gray-500" },
};

// ── Main Component ───────────────────────────────────────────────────────────

export default function CandidateDetailPage() {
  const routeParams = useParams();
  const id = routeParams?.id;
  const router = useRouter();
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<TabId>("profil");
  const [aiExpanded, setAiExpanded] = useState(true);
  const [showScreeningForm, setShowScreeningForm] = useState(false);
  const [expandedScreenings, setExpandedScreenings] = useState<Set<number>>(new Set());
  const [noteText, setNoteText] = useState("");
  const [noteSubmitting, setNoteSubmitting] = useState(false);
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [expandedTranscripts, setExpandedTranscripts] = useState<Set<number>>(new Set());
  const [callLogging, setCallLogging] = useState(false);
  const [prepKitJobId, setPrepKitJobId] = useState<number | null>(null);
  const [prepKitData, setPrepKitData] = useState<any | null>(null);
  const [prepKitLoading, setPrepKitLoading] = useState(false);
  const [prepKitError, setPrepKitError] = useState<string | null>(null);
  const [showPoolDropdown, setShowPoolDropdown] = useState(false);
  const [poolAddingId, setPoolAddingId] = useState<number | null>(null);
  const [poolAddSuccess, setPoolAddSuccess] = useState<number | null>(null);
  const [showCVGenerator, setShowCVGenerator] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editToast, setEditToast] = useState<string | null>(null);

  // ── Queries ────────────────────────────────────────────────────────────────

  const openTab = useTabsStore((s) => s.openTab);

  const { data: candidate, isLoading } = useQuery({
    queryKey: ["candidate", id],
    queryFn: () => api.get(`/api/candidates/${id}`).then((r) => r.data),
  });

  // Auto-open tab when candidate data loads
  useEffect(() => {
    if (candidate) {
      const fullName = `${candidate.name} ${candidate.lastname}`.trim();
      openTab("candidate", Number(id), fullName);
    }
  }, [candidate, id, openTab]);

  const { data: timeline, isLoading: timelineLoading } = useQuery({
    queryKey: ["candidate-timeline", id],
    queryFn: () =>
      api.get(`/api/candidates/${id}/timeline?limit=50`).then((r) => r.data),
    enabled: activeTab === "timeline" || activeTab === "notatki",
  });

  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ["candidate-history", id],
    queryFn: () =>
      api.get(`/api/candidates/${id}/history`).then((r) => r.data),
    enabled: activeTab === "rekrutacje",
  });

  const { data: calls = [], isLoading: callsLoading, refetch: refetchCalls } = useQuery<CallRecord[]>({
    queryKey: ["candidate-calls", id],
    queryFn: () => api.get(`/api/candidates/${id}/calls`).then((r) => r.data),
    enabled: activeTab === "rozmowy",
  });

  const { data: screenings = [], isLoading: screeningsLoading, refetch: refetchScreenings } = useQuery<any[]>({
    queryKey: ["candidate-screenings", id],
    queryFn: () => api.get(`/api/candidates/${id}/screenings`).then((r) => r.data),
    enabled: activeTab === "screeningi",
  });

  const { data: aiProfile } = useQuery<any>({
    queryKey: ["candidate-ai-profile", id],
    queryFn: () => api.get(`/api/candidates/${id}/ai-profile`).then((r) => r.data),
    enabled: !!id,
  });

  const { data: talentPools = [] } = useQuery<any[]>({
    queryKey: ["talent-pools"],
    queryFn: () => talentPoolsApi.list().then((r) => r.data),
  });

  const { data: candidatePoolIds = [], refetch: refetchPoolIds } = useQuery<any>({
    queryKey: ["candidate-pool-ids", id],
    queryFn: () => talentPoolsApi.getPoolsForCandidate(Number(id)).then((r) => r.data),
    enabled: !!id,
  });

  const historyForPrepKit = useQuery({
    queryKey: ["candidate-history-always", id],
    queryFn: () => api.get(`/api/candidates/${id}/history`).then((r) => r.data),
    enabled: !!id,
  });

  const createScreeningMutation = useMutation({
    mutationFn: (data: object) => api.post("/api/screenings", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["candidate-screenings", id] });
      queryClient.invalidateQueries({ queryKey: ["candidate-ai-profile", id] });
      setShowScreeningForm(false);
    },
  });

  // ── Note mutation ──────────────────────────────────────────────────────────

  const handleAddNote = async () => {
    if (!noteText.trim()) return;
    setNoteSubmitting(true);
    try {
      await api.post("/api/notes/", {
        candidate_id: Number(id),
        content: noteText.trim(),
        note_type: "general",
      });
      setNoteText("");
      queryClient.invalidateQueries({ queryKey: ["candidate-timeline", id] });
    } catch (e) {
      // silent
    } finally {
      setNoteSubmitting(false);
    }
  };

  // ── Log call ──────────────────────────────────────────────────────────────
  const handleLogCall = async () => {
    setCallLogging(true);
    try {
      await api.post("/api/calls", {
        candidate_id: Number(id),
        direction: "outbound",
        status: "completed",
      });
      refetchCalls();
    } catch (e) {
      // silent
    } finally {
      setCallLogging(false);
    }
  };

  // ── Prep Kit ──────────────────────────────────────────────────────────────
  const handleGeneratePrepKit = async (jobId: number) => {
    setPrepKitLoading(true);
    setPrepKitError(null);
    setPrepKitJobId(jobId);
    try {
      const { data } = await prepKitApi.generate(jobId, Number(id));
      setPrepKitData(data);
    } catch (e: any) {
      setPrepKitError(e.response?.data?.detail || "Błąd generowania Prep Kit");
    } finally {
      setPrepKitLoading(false);
    }
  };

  // ── Add to Pool ───────────────────────────────────────────────────────────
  const handleAddToPool = async (poolId: number) => {
    setPoolAddingId(poolId);
    try {
      await talentPoolsApi.addCandidate(poolId, Number(id));
      setPoolAddSuccess(poolId);
      refetchPoolIds();
      setTimeout(() => setPoolAddSuccess(null), 2000);
    } catch (e: any) {
      // Already in pool or other error — ignore silently
    } finally {
      setPoolAddingId(null);
    }
  };

  // ── Loading/error states ───────────────────────────────────────────────────

  if (isLoading)
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <div className="w-6 h-6 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mr-3" />
        Ładowanie profilu...
      </div>
    );
  if (!candidate)
    return (
      <div className="flex items-center gap-2 p-6 text-red-500">
        <AlertCircle className="w-5 h-5" /> Nie znaleziono kandydata
      </div>
    );

  // ── Derived values ─────────────────────────────────────────────────────────

  const source = candidate.source?.toLowerCase();
  const fullName = `${candidate.name} ${candidate.lastname}`;
  const initials = `${candidate.name.charAt(0)}${candidate.lastname.charAt(0)}`.toUpperCase();
  const avatarColor = getAvatarColor(fullName);

  const tabs: { id: TabId; label: string; icon: React.ReactNode }[] = [
    { id: "profil",     label: "Profil",     icon: <User className="w-4 h-4" /> },
    { id: "timeline",   label: "Timeline",   icon: <Activity className="w-4 h-4" /> },
    { id: "rekrutacje", label: "Rekrutacje", icon: <Briefcase className="w-4 h-4" /> },
    { id: "screeningi", label: "Screeningi", icon: <Sparkles className="w-4 h-4" /> },
    { id: "rozmowy",    label: "Rozmowy",    icon: <PhoneCall className="w-4 h-4" /> },
    { id: "pliki",      label: "Pliki",      icon: <FileText className="w-4 h-4" /> },
    { id: "notatki",    label: "Notatki",    icon: <MessageSquare className="w-4 h-4" /> },
  ];

  const notes = timeline?.timeline?.filter((t: any) => t.type === "note") ?? [];

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4 max-w-5xl">
      {/* Back link */}
      <Link
        href="/candidates"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> Wróć do kandydatów
      </Link>

      {/* ── HEADER CARD ── */}
      <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
        {/* Top accent bar */}
        <div className="h-1.5 bg-gradient-to-r from-blue-600 via-violet-500 to-blue-400" />

        <div className="p-6">
          <div className="flex items-start gap-5 flex-wrap">
            {/* Avatar */}
            <div className="flex-shrink-0">
              {candidate.avatar_url ? (
                <img
                  src={candidate.avatar_url}
                  alt={fullName}
                  className="w-20 h-20 rounded-2xl object-cover border-2 border-gray-100 shadow"
                />
              ) : (
                <div
                  className={cn(
                    "w-20 h-20 rounded-2xl flex items-center justify-center text-2xl font-bold text-white shadow",
                    avatarColor
                  )}
                >
                  {initials}
                </div>
              )}
            </div>

            {/* Name + contacts + actions */}
            <div className="flex-1 min-w-0">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                {/* Name block */}
                <div>
                  <h1 className="text-2xl font-bold text-gray-900">{fullName}</h1>
                  {candidate.competence_category && (
                    <p className="text-sm text-blue-600 font-medium mt-0.5">
                      {candidate.competence_category}
                    </p>
                  )}
                </div>

                {/* Action buttons */}
                <div className="flex items-center gap-2 flex-wrap">
                  <button
                    onClick={() => alert("Funkcja w przygotowaniu")}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
                  >
                    <UserPlus className="w-3.5 h-3.5" />
                    Dodaj do rekrutacji
                  </button>

                  <button
                    onClick={() => setShowCVGenerator(true)}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 transition-colors shadow-sm"
                  >
                    <FileText className="w-3.5 h-3.5" />
                    Generuj CV
                  </button>

                  {/* Prep Kit button — show if candidate has pipeline */}
                  {historyForPrepKit.data?.jobs?.length > 0 && (
                    <div className="relative">
                      <button
                        onClick={() => {
                          // Take first job from history
                          const firstJob = historyForPrepKit.data.jobs[0];
                          handleGeneratePrepKit(firstJob.job_id);
                        }}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-600 text-white text-sm font-medium rounded-lg hover:bg-violet-700 transition-colors shadow-sm"
                      >
                        <BookOpen className="w-3.5 h-3.5" />
                        Prep Kit
                      </button>
                    </div>
                  )}

                  {/* Dodaj do puli button */}
                  <div className="relative">
                    <button
                      onClick={() => setShowPoolDropdown((v) => !v)}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-500 text-white text-sm font-medium rounded-lg hover:bg-amber-600 transition-colors shadow-sm"
                    >
                      <Star className="w-3.5 h-3.5" />
                      Dodaj do puli
                    </button>
                    {showPoolDropdown && (
                      <div className="absolute right-0 top-full mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg z-10 min-w-48 py-1">
                        {talentPools.length === 0 ? (
                          <div className="px-4 py-2 text-xs text-gray-400">Brak pul talentów</div>
                        ) : (
                          talentPools.map((pool: any) => {
                            const alreadyIn = (candidatePoolIds?.pool_ids || []).includes(pool.id);
                            const isAdding = poolAddingId === pool.id;
                            const isSuccess = poolAddSuccess === pool.id;
                            return (
                              <button
                                key={pool.id}
                                onClick={() => {
                                  if (!alreadyIn) handleAddToPool(pool.id);
                                  setShowPoolDropdown(false);
                                }}
                                disabled={alreadyIn || isAdding}
                                className={cn(
                                  "w-full text-left px-4 py-2 text-sm flex items-center gap-2 transition-colors",
                                  alreadyIn
                                    ? "text-gray-400 cursor-default"
                                    : "text-gray-700 hover:bg-gray-50"
                                )}
                              >
                                <Star
                                  className={cn(
                                    "w-3.5 h-3.5",
                                    alreadyIn ? "text-amber-400 fill-amber-400" : "text-gray-400"
                                  )}
                                />
                                {pool.name}
                                {alreadyIn && (
                                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 ml-auto" />
                                )}
                              </button>
                            );
                          })
                        )}
                      </div>
                    )}
                  </div>
                  {candidate.phone && (
                    <a
                      href={`tel:${candidate.phone}`}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors shadow-sm"
                    >
                      <Phone className="w-3.5 h-3.5 text-emerald-500" />
                      Zadzwoń
                    </a>
                  )}
                  {candidate.email && (
                    <>
                      <a
                        href={`mailto:${candidate.email}`}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors shadow-sm"
                      >
                        <Mail className="w-3.5 h-3.5 text-blue-500" />
                        Email
                      </a>
                      <button
                        onClick={() => setEmailModalOpen(true)}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 border border-blue-200 text-blue-700 text-sm font-medium rounded-lg hover:bg-blue-100 transition-colors shadow-sm"
                      >
                        <Send className="w-3.5 h-3.5" />
                        Wyślij email
                      </button>
                    </>
                  )}
                  <button
                    onClick={() => setShowEditModal(true)}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors shadow-sm"
                  >
                    <PencilLine className="w-3.5 h-3.5 text-gray-500" />
                    Edytuj
                  </button>
                </div>
              </div>

              {/* Contact row */}
              <div className="flex flex-wrap gap-4 mt-3 text-sm text-gray-600">
                {candidate.email && (
                  <a
                    href={`mailto:${candidate.email}`}
                    className="flex items-center gap-1.5 hover:text-blue-600 transition-colors"
                  >
                    <Mail className="w-3.5 h-3.5 text-gray-400" />
                    {candidate.email}
                  </a>
                )}
                {candidate.phone && (
                  <a
                    href={`tel:${candidate.phone}`}
                    className="flex items-center gap-1.5 hover:text-emerald-600 transition-colors"
                  >
                    <Phone className="w-3.5 h-3.5 text-gray-400" />
                    {candidate.phone}
                  </a>
                )}
                {candidate.location && (
                  <span className="flex items-center gap-1.5 text-gray-500">
                    <MapPin className="w-3.5 h-3.5 text-gray-400" />
                    {candidate.location}
                  </span>
                )}
                {candidate.linkedin && (
                  <a
                    href={
                      candidate.linkedin.startsWith("http")
                        ? candidate.linkedin
                        : `https://${candidate.linkedin}`
                    }
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-blue-600 hover:underline"
                  >
                    <Linkedin className="w-3.5 h-3.5" />
                    LinkedIn
                  </a>
                )}
              </div>

              {/* Badges row */}
              <div className="flex flex-wrap items-center gap-2 mt-3">
                {source && SOURCE_LABELS[source] && (
                  <span
                    className={cn(
                      "px-2.5 py-0.5 rounded-full text-xs font-semibold",
                      SOURCE_COLORS[source] || "bg-gray-200 text-gray-700"
                    )}
                  >
                    {SOURCE_LABELS[source]}
                  </span>
                )}
                <span
                  className={cn(
                    "px-2.5 py-0.5 rounded-full text-xs font-semibold",
                    STATUS_COLORS[candidate.status] || "bg-gray-100 text-gray-600"
                  )}
                >
                  {STATUS_LABELS[candidate.status] || candidate.status}
                </span>
              </div>
            </div>
          </div>

          {/* Tags row */}
          {candidate.tags && candidate.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-4 pt-4 border-t border-gray-100">
              {candidate.tags.map((tag: string, i: number) => (
                <span
                  key={i}
                  className="px-2.5 py-0.5 bg-blue-50 text-blue-700 border border-blue-100 rounded-full text-xs font-medium"
                >
                  #{tag}
                </span>
              ))}
            </div>
          )}

          {/* Quick stats row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4 pt-4 border-t border-gray-100">
            {candidate.salary_expectation && (
              <div className="bg-gray-50 rounded-xl p-3">
                <p className="text-xs text-gray-400 font-medium uppercase tracking-wide">
                  Oczekiwania
                </p>
                <p className="font-bold text-gray-900 mt-0.5">
                  {formatCurrency(candidate.salary_expectation)}{" "}
                  <span className="font-normal text-gray-500 text-sm">
                    {candidate.salary_currency || "PLN"}
                  </span>
                </p>
              </div>
            )}
            {candidate.notice_period != null && (
              <div className="bg-gray-50 rounded-xl p-3">
                <p className="text-xs text-gray-400 font-medium uppercase tracking-wide">
                  Wypowiedzenie
                </p>
                <p className="font-bold text-gray-900 mt-0.5">
                  {candidate.notice_period === 0
                    ? "Natychmiast"
                    : `${candidate.notice_period} dni`}
                </p>
              </div>
            )}
            {candidate.availability_date && (
              <div className="bg-gray-50 rounded-xl p-3">
                <p className="text-xs text-gray-400 font-medium uppercase tracking-wide">
                  Dostępność
                </p>
                <p className="font-bold text-gray-900 mt-0.5">
                  {formatDate(candidate.availability_date)}
                </p>
              </div>
            )}
            {candidate.competence_category && (
              <div className="bg-gray-50 rounded-xl p-3">
                <p className="text-xs text-gray-400 font-medium uppercase tracking-wide">
                  Kategoria
                </p>
                <p className="font-bold text-gray-900 mt-0.5 truncate">
                  {candidate.competence_category}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* AI Summary */}
        {candidate.ai_summary && (
          <div className="mx-6 mb-3 rounded-xl border border-violet-100 bg-violet-50/50 overflow-hidden">
            <button
              onClick={() => setAiExpanded((v) => !v)}
              className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-semibold text-violet-700"
            >
              <span className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-violet-500" />
                AI Summary
              </span>
              {aiExpanded ? (
                <ChevronUp className="w-4 h-4 text-violet-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-violet-400" />
              )}
            </button>
            {aiExpanded && (
              <div className="px-4 pb-4">
                <p className="text-sm text-violet-800 italic leading-relaxed">
                  {candidate.ai_summary}
                </p>
              </div>
            )}
          </div>
        )}

        {/* AI Profile (from screenings) */}
        {aiProfile && aiProfile.screening_count > 0 && (
          <div className="mx-6 mb-6 rounded-xl border border-blue-100 bg-blue-50/40 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-blue-500" />
              <span className="text-sm font-bold text-blue-800">AI Profil — {aiProfile.screening_count} screeningów</span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
              {aiProfile.overall_impression_avg && (
                <div className="bg-white rounded-lg p-2 text-center">
                  <p className="text-gray-400 mb-0.5">Wrażenie śr.</p>
                  <p className="font-bold text-gray-800 text-base">{aiProfile.overall_impression_avg}/5</p>
                </div>
              )}
              {aiProfile.readiness_avg && (
                <div className="bg-white rounded-lg p-2 text-center">
                  <p className="text-gray-400 mb-0.5">Gotowość śr.</p>
                  <p className="font-bold text-gray-800 text-base">{aiProfile.readiness_avg}/5</p>
                </div>
              )}
              {aiProfile.salary_trend.length > 0 && (
                <div className="bg-white rounded-lg p-2 text-center">
                  <p className="text-gray-400 mb-0.5">Ostatnie oczek.</p>
                  <p className="font-bold text-gray-800 text-sm">
                    {aiProfile.salary_trend[aiProfile.salary_trend.length - 1].expectation?.toLocaleString("pl-PL")} PLN
                  </p>
                </div>
              )}
              {aiProfile.counteroffer_risk_distribution.high > 0 && (
                <div className="bg-red-50 border border-red-100 rounded-lg p-2 text-center">
                  <p className="text-red-400 mb-0.5">Counteroffer</p>
                  <p className="font-bold text-red-700 text-sm">Ryzyko!</p>
                </div>
              )}
            </div>
            {aiProfile.warnings.length > 0 && (
              <div className="space-y-1">
                {aiProfile.warnings.map((w: string, i: number) => (
                  <div key={i} className="flex items-start gap-1.5 text-xs text-red-700 bg-red-50 border border-red-100 rounded-lg px-2 py-1.5">
                    <AlertCircle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                    {w}
                  </div>
                ))}
              </div>
            )}
            {aiProfile.verified_skills_aggregate.length > 0 && (
              <div>
                <p className="text-xs text-blue-600 font-semibold mb-1.5">Potwierdzone umiejętności:</p>
                <div className="flex flex-wrap gap-1.5">
                  {aiProfile.verified_skills_aggregate.filter((s: any) => s.level === "confirmed").map((s: any, i: number) => (
                    <span key={i} className="px-2 py-0.5 bg-blue-600 text-white rounded-full text-xs font-medium">
                      {s.skill}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── SEND EMAIL MODAL ── */}
      {emailModalOpen && candidate.email && (
        <SendEmailModal
          candidateId={Number(id)}
          candidateName={fullName}
          candidateEmail={candidate.email}
          onClose={() => setEmailModalOpen(false)}
        />
      )}

      {/* ── EDIT CANDIDATE MODAL ── */}
      {showEditModal && candidate && (
        <EditCandidateModal
          candidate={candidate}
          onClose={() => setShowEditModal(false)}
          onSuccess={(msg) => {
            setEditToast(msg);
            setTimeout(() => setEditToast(null), 3000);
            queryClient.invalidateQueries({ queryKey: ["candidate", id] });
            setShowEditModal(false);
          }}
        />
      )}

      {/* Edit toast */}
      {editToast && (
        <div className="fixed bottom-6 right-6 z-[200] flex items-center gap-3 px-5 py-3.5 rounded-xl shadow-xl text-white text-sm font-medium bg-green-600">
          {editToast}
          <button onClick={() => setEditToast(null)} className="ml-1 opacity-70 hover:opacity-100">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* ── CV GENERATOR MODAL ── */}
      {showCVGenerator && (
        <CVGeneratorModal
          candidateId={Number(id)}
          candidateName={fullName}
          onClose={() => setShowCVGenerator(false)}
        />
      )}

      {/* ── PREP KIT MODAL ── */}
      {(prepKitData || prepKitLoading || prepKitError) && (
        <PrepKitModal
          candidateName={fullName}
          isLoading={prepKitLoading}
          error={prepKitError}
          data={prepKitData}
          onClose={() => { setPrepKitData(null); setPrepKitError(null); setPrepKitJobId(null); }}
        />
      )}

      {/* ── TABS ── */}
      <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
        {/* Sticky tab bar */}
        <div className="sticky top-0 z-10 bg-white flex border-b border-gray-200 dark:border-gray-700 overflow-x-auto shadow-sm">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex items-center gap-2 px-5 py-3.5 text-sm font-medium transition-all duration-150 whitespace-nowrap flex-shrink-0",
                activeTab === tab.id
                  ? "border-b-2 border-blue-600 text-blue-600 bg-blue-50/40"
                  : "text-gray-500 hover:text-gray-800 hover:bg-gray-50"
              )}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>

        <div className="p-6 animate-in fade-in duration-200">
          {/* ── PROFIL TAB ── */}
          {activeTab === "profil" && (
            <div className="space-y-7">
              {/* Skills */}
              {candidate.skills && candidate.skills.length > 0 && (
                <section>
                  <SectionTitle>Umiejętności</SectionTitle>
                  <div className="flex flex-wrap gap-2 mt-3">
                    {candidate.skills.map((skill: any, i: number) => (
                      <div
                        key={i}
                        className="flex items-center gap-1.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl px-3 py-2 shadow-sm"
                      >
                        <span className="text-sm font-medium text-gray-800">
                          {skill.name}
                        </span>
                        {skill.level && (
                          <span
                            className={cn(
                              "text-xs px-1.5 py-0.5 rounded-md font-medium",
                              SKILL_LEVEL_COLORS[skill.level] ||
                                "bg-gray-100 text-gray-600"
                            )}
                          >
                            {skill.level}
                          </span>
                        )}
                        {skill.years && (
                          <span className="text-xs text-gray-400">
                            {skill.years}l
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Experience */}
              {candidate.experience && candidate.experience.length > 0 && (
                <section>
                  <SectionTitle>Doświadczenie zawodowe</SectionTitle>
                  <div className="space-y-3 mt-3">
                    {candidate.experience.map((exp: any, i: number) => (
                      <div
                        key={i}
                        className="flex gap-4 p-4 bg-gray-50 rounded-xl border border-gray-100"
                      >
                        <div className="flex-shrink-0 w-9 h-9 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl flex items-center justify-center shadow-sm">
                          <Briefcase className="w-4 h-4 text-gray-400" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="font-semibold text-gray-900">{exp.role}</p>
                          <p className="text-sm text-gray-600 mt-0.5">
                            {exp.company}
                          </p>
                          {(exp.start || exp.end) && (
                            <p className="text-xs text-gray-400 mt-1 flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              {exp.start} — {exp.end || "Teraz"}
                            </p>
                          )}
                          {exp.desc && (
                            <p className="text-sm text-gray-500 mt-2 leading-relaxed">
                              {exp.desc}
                            </p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Education */}
              {candidate.education && candidate.education.length > 0 && (
                <section>
                  <SectionTitle>Edukacja</SectionTitle>
                  <div className="space-y-2 mt-3">
                    {candidate.education.map((edu: any, i: number) => (
                      <div
                        key={i}
                        className="p-4 bg-gray-50 rounded-xl border border-gray-100"
                      >
                        <p className="font-semibold text-gray-900">
                          {edu.school}
                        </p>
                        {edu.degree && (
                          <p className="text-sm text-gray-600 mt-0.5">
                            {edu.degree}
                            {edu.field ? ` — ${edu.field}` : ""}
                          </p>
                        )}
                        {edu.year && (
                          <p className="text-xs text-gray-400 mt-1">{edu.year}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Languages */}
              {candidate.languages && candidate.languages.length > 0 && (
                <section>
                  <SectionTitle>Języki</SectionTitle>
                  <div className="flex flex-wrap gap-2 mt-3">
                    {candidate.languages.map((lang: any, i: number) => (
                      <span
                        key={i}
                        className="px-3 py-1.5 bg-purple-50 text-purple-700 border border-purple-100 rounded-xl text-sm font-medium"
                      >
                        {lang.lang}{lang.level ? ` — ${lang.level}` : ""}
                      </span>
                    ))}
                  </div>
                </section>
              )}

              {/* Empty state */}
              {(!candidate.skills || candidate.skills.length === 0) &&
                (!candidate.experience || candidate.experience.length === 0) &&
                (!candidate.education || candidate.education.length === 0) && (
                  <div className="text-center py-10 text-gray-400">
                    <User className="w-10 h-10 mx-auto mb-3 opacity-30" />
                    <p>Brak szczegółowych danych profilu</p>
                  </div>
                )}
            </div>
          )}

          {/* ── TIMELINE TAB ── */}
          {activeTab === "timeline" && (
            <div>
              {timelineLoading ? (
                <LoadingSpinner text="Ładowanie timeline..." />
              ) : !timeline || timeline.timeline.length === 0 ? (
                <EmptyState icon={<Activity className="w-10 h-10" />} text="Brak aktywności dla tego kandydata" />
              ) : (
                <TimelineFeed items={timeline.timeline} />
              )}
            </div>
          )}

          {/* ── REKRUTACJE TAB ── */}
          {activeTab === "rekrutacje" && (
            <div className="space-y-6">
              {/* Phase 3: multi-pipeline current view */}
              <CandidatePipelinesWidget candidateId={Number(id)} />
              {/* Phase 2: AI-suggested jobs */}
              <SuggestedJobsWidget candidateId={Number(id)} />

              {historyLoading ? (
                <LoadingSpinner text="Ładowanie historii rekrutacji..." />
              ) : !history ? null : (
                <>
                  {history.jobs.length > 0 ? (
                    <section>
                      <SectionTitle>Procesy rekrutacyjne</SectionTitle>
                      <div className="space-y-3 mt-3">
                        {history.jobs.map((job: any) => (
                          <JobHistoryCard key={job.job_id} job={job} />
                        ))}
                      </div>
                    </section>
                  ) : (
                    <EmptyState
                      icon={<Briefcase className="w-10 h-10" />}
                      text="Kandydat nie brał udziału w żadnych procesach rekrutacyjnych"
                    />
                  )}

                  {history.contracts.length > 0 && (
                    <section>
                      <SectionTitle>Kontrakty</SectionTitle>
                      <div className="space-y-2 mt-3">
                        {history.contracts.map((c: any) => (
                          <ContractCard key={c.contract_id} contract={c} />
                        ))}
                      </div>
                    </section>
                  )}
                </>
              )}
            </div>
          )}

          {/* ── SCREENINGI TAB ── */}
          {activeTab === "screeningi" && (
            <ScreeningiTab
              candidateId={Number(id)}
              screenings={screenings}
              isLoading={screeningsLoading}
              showForm={showScreeningForm}
              setShowForm={setShowScreeningForm}
              createMutation={createScreeningMutation}
              expandedScreenings={expandedScreenings}
              setExpandedScreenings={setExpandedScreenings}
            />
          )}

          {/* ── ROZMOWY TAB ── */}
          {activeTab === "rozmowy" && (
            <div className="space-y-4">
              {/* CloudTalk placeholder notice */}
              <div className="flex items-center gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-4 py-2.5">
                <PhoneCall className="w-4 h-4 flex-shrink-0 text-amber-500" />
                <span>Integracja z CloudTalk w przygotowaniu — rozmowy logowane ręcznie lub przez webhook</span>
              </div>

              {/* Zadzwoń button */}
              {candidate.phone && (
                <div className="flex items-center gap-3">
                  <a
                    href={`tel:${candidate.phone}`}
                    onClick={handleLogCall}
                    className="flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 transition-colors shadow-sm"
                  >
                    <PhoneOutgoing className="w-4 h-4" />
                    Zadzwoń ({candidate.phone})
                  </a>
                  <span className="text-xs text-gray-400">
                    Kliknięcie otworzy telefon i zaloguje rozmowę
                  </span>
                </div>
              )}

              {/* Calls list */}
              {callsLoading ? (
                <LoadingSpinner text="Ładowanie historii rozmów..." />
              ) : calls.length === 0 ? (
                <EmptyState
                  icon={<PhoneCall className="w-10 h-10" />}
                  text="Brak historii rozmów z tym kandydatem"
                />
              ) : (
                <div className="space-y-3">
                  <SectionTitle>Historia rozmów ({calls.length})</SectionTitle>
                  {calls.map((call) => {
                    const statusCfg = CALL_STATUS_CONFIG[call.status] || { label: call.status, color: "bg-gray-100 text-gray-600" };
                    const isExpanded = expandedTranscripts.has(call.id);
                    return (
                      <div key={call.id} className="border border-gray-200 rounded-xl p-4 hover:border-gray-300 transition-colors">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex items-center gap-3">
                            {call.direction === "outbound" ? (
                              <div className="w-8 h-8 rounded-full bg-blue-50 flex items-center justify-center flex-shrink-0">
                                <PhoneOutgoing className="w-4 h-4 text-blue-600" />
                              </div>
                            ) : (
                              <div className="w-8 h-8 rounded-full bg-emerald-50 flex items-center justify-center flex-shrink-0">
                                <PhoneIncoming className="w-4 h-4 text-emerald-600" />
                              </div>
                            )}
                            <div>
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-sm font-medium text-gray-900">
                                  {call.direction === "outbound" ? "↗ Wychodzące" : "↙ Przychodzące"}
                                </span>
                                <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusCfg.color}`}>
                                  {statusCfg.label}
                                </span>
                                {call.duration_seconds != null && call.duration_seconds > 0 && (
                                  <span className="text-xs text-gray-500 flex items-center gap-1">
                                    <Clock className="w-3 h-3" />
                                    {formatCallDuration(call.duration_seconds)}
                                  </span>
                                )}
                              </div>
                              <p className="text-xs text-gray-400 mt-0.5">
                                {new Date(call.created_at).toLocaleString("pl-PL")}
                              </p>
                            </div>
                          </div>
                        </div>

                        {call.summary && (
                          <p className="text-sm text-gray-600 mt-3 pl-11 leading-relaxed">{call.summary}</p>
                        )}

                        {call.transcript && (
                          <div className="mt-3 pl-11">
                            <button
                              onClick={() => {
                                setExpandedTranscripts((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(call.id)) next.delete(call.id);
                                  else next.add(call.id);
                                  return next;
                                });
                              }}
                              className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 font-medium"
                            >
                              {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                              {isExpanded ? "Ukryj transkrypt" : "Pokaż transkrypt"}
                            </button>
                            {isExpanded && (
                              <div className="mt-2 p-3 bg-gray-50 rounded-lg border border-gray-100 text-xs text-gray-600 font-mono leading-relaxed whitespace-pre-wrap max-h-60 overflow-y-auto">
                                {call.transcript}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* ── PLIKI TAB ── */}
          {activeTab === "pliki" && (
            <PlikiTab candidateId={Number(id)} candidate={candidate} queryClient={queryClient} />
          )}

          {/* ── NOTATKI TAB ── */}
          {activeTab === "notatki" && (
            <div className="space-y-5">
              {/* Add note form */}
              <section>
                <SectionTitle>Dodaj notatkę</SectionTitle>
                <div className="mt-3 space-y-2">
                  <textarea
                    value={noteText}
                    onChange={(e) => setNoteText(e.target.value)}
                    placeholder="Dodaj notatkę... np. wrażenia po rozmowie, kluczowe informacje, uwagi do procesu rekrutacji"
                    rows={6}
                    className="w-full px-4 py-3 border border-gray-200 rounded-xl text-sm resize-y min-h-[120px] focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-shadow bg-gray-50 focus:bg-white"
                  />
                  <div className="flex justify-end">
                    <button
                      onClick={handleAddNote}
                      disabled={!noteText.trim() || noteSubmitting}
                      className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {noteSubmitting ? (
                        <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      ) : (
                        <StickyNote className="w-3.5 h-3.5" />
                      )}
                      Zapisz notatkę
                    </button>
                  </div>
                </div>
              </section>

              {/* Notes list */}
              <section>
                <SectionTitle>Historia notatek</SectionTitle>
                {timelineLoading ? (
                  <LoadingSpinner text="Ładowanie notatek..." />
                ) : notes.length === 0 ? (
                  <EmptyState
                    icon={<MessageSquare className="w-10 h-10" />}
                    text="Brak notatek dla tego kandydata"
                  />
                ) : (
                  <div className="space-y-3 mt-3">
                    {notes.map((note: any, i: number) => (
                      <div
                        key={`note-${note.id}-${i}`}
                        className="p-4 bg-amber-50 border border-amber-100 rounded-xl"
                      >
                        <div className="flex items-start justify-between gap-2 mb-2">
                          <div className="flex items-center gap-2">
                            <StickyNote className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
                            <span className="text-xs font-semibold text-amber-700 capitalize">
                              {note.note_type || "ogólna"}
                            </span>
                          </div>
                          <span className="text-xs text-gray-400 flex-shrink-0">
                            {note.timestamp
                              ? new Date(note.timestamp).toLocaleString("pl-PL")
                              : "—"}
                          </span>
                        </div>
                        <p className="text-sm text-gray-700 leading-relaxed">
                          {note.content}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
      {children}
    </h3>
  );
}

function LoadingSpinner({ text }: { text: string }) {
  return (
    <div className="flex items-center justify-center py-12 text-gray-400 gap-2">
      <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
      {text}
    </div>
  );
}

function EmptyState({
  icon,
  text,
}: {
  icon: React.ReactNode;
  text: string;
}) {
  return (
    <div className="text-center py-12 text-gray-300">
      <div className="flex justify-center mb-3 opacity-40">{icon}</div>
      <p className="text-sm text-gray-400">{text}</p>
    </div>
  );
}

function TimelineFeed({ items }: { items: any[] }) {
  const TIMELINE_ITEM_LABEL = (item: any): string => {
    if (item.type === "note")
      return `Notatka${item.note_type ? ` — ${item.note_type}` : ""}`;
    if (item.type === "stage_change")
      return `Etap: ${item.stage}${item.job_title ? ` (${item.job_title})` : ""}`;
    if (item.type === "activity")
      return TIMELINE_ACTION_LABELS[item.action] || item.action;
    if (item.type === "user_activity")
      return TIMELINE_ACTION_LABELS[item.action_type] || item.action_type;
    return item.type;
  };

  return (
    <div className="relative">
      <div className="absolute left-5 top-0 bottom-0 w-px bg-gray-100" />
      <div className="space-y-3">
        {items.map((item: any, i: number) => (
          <div
            key={`${item.type}-${item.id}-${i}`}
            className="relative flex gap-4 pl-12"
          >
            {/* Dot */}
            <div
              className={cn(
                "absolute left-3 w-5 h-5 rounded-full border-2 border-white flex items-center justify-center shadow-sm mt-2 text-white",
                TIMELINE_COLORS[item.type] || "bg-gray-400"
              )}
            >
              {TIMELINE_ICONS[item.type] || <Activity className="w-3 h-3" />}
            </div>

            <div className="flex-1 bg-gray-50 rounded-xl p-4 border border-gray-100">
              <div className="flex items-start justify-between gap-2 mb-1">
                <span className="font-medium text-sm text-gray-800">
                  {TIMELINE_ITEM_LABEL(item)}
                </span>
                <span className="text-xs text-gray-400 flex-shrink-0" title={item.timestamp ? new Date(item.timestamp).toLocaleString("pl-PL") : undefined}>
                  {item.timestamp ? formatRelativeTime(item.timestamp) : "—"}
                </span>
              </div>
              {item.content && (
                <p className="text-sm text-gray-600 mt-1">{item.content}</p>
              )}
              {item.notes && (
                <p className="text-sm text-gray-500 mt-1 italic">{item.notes}</p>
              )}
              {item.rating && (
                <div className="flex gap-0.5 mt-1">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <Star
                      key={n}
                      className={cn(
                        "w-3.5 h-3.5",
                        n <= item.rating
                          ? "text-amber-400 fill-amber-400"
                          : "text-gray-200 fill-gray-200"
                      )}
                    />
                  ))}
                </div>
              )}
              {item.details && Object.keys(item.details).length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-gray-400">
                  {Object.entries(item.details)
                    .filter(([k]) => !["bulk"].includes(k))
                    .map(([k, v]) => (
                      <span key={k}>
                        {k}:{" "}
                        <span className="font-medium text-gray-600">
                          {String(v)}
                        </span>
                      </span>
                    ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function JobHistoryCard({ job }: { job: any }) {
  const stageColors: Record<string, string> = {
    hired: "bg-green-100 text-green-700",
    rejected: "bg-red-100 text-red-700",
    offer: "bg-blue-100 text-blue-700",
    interview: "bg-purple-100 text-purple-700",
    screening: "bg-amber-100 text-amber-700",
  };

  return (
    <div className="border border-gray-200 rounded-xl p-4 hover:border-blue-200 transition-colors">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <Link
            href={`/jobs/${job.job_id}`}
            className="font-semibold text-blue-600 hover:underline"
          >
            {job.job_title}
          </Link>
          <p className="text-xs text-gray-400 mt-0.5">
            <Calendar className="w-3 h-3 inline mr-1" />
            {job.first_seen
              ? new Date(job.first_seen).toLocaleDateString("pl-PL")
              : "—"}{" "}
            —{" "}
            {job.last_seen
              ? new Date(job.last_seen).toLocaleDateString("pl-PL")
              : "—"}
          </p>
        </div>
        {job.latest_stage && (
          <span
            className={cn(
              "px-2.5 py-1 rounded-lg text-xs font-semibold flex-shrink-0",
              stageColors[job.latest_stage] || "bg-gray-100 text-gray-600"
            )}
          >
            {job.latest_stage}
          </span>
        )}
      </div>
      {job.stages && job.stages.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {job.stages.map((s: any, i: number) => (
            <span
              key={i}
              className="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded-lg"
            >
              {s.stage}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function ContractCard({ contract: c }: { contract: any }) {
  return (
    <div className="flex items-center justify-between p-4 bg-gray-50 rounded-xl border border-gray-100">
      <div>
        <p className="font-semibold text-gray-900">{c.client_name}</p>
        <p className="text-xs text-gray-400 mt-0.5">
          {c.start_date} — {c.end_date || "trwa"}
        </p>
      </div>
      <div className="text-right">
        {c.rate_client && (
          <p className="font-bold text-emerald-600">
            {formatCurrency(c.rate_client)}{" "}
            <span className="text-xs font-normal text-gray-400">{c.currency}</span>
          </p>
        )}
        <span
          className={cn(
            "text-xs px-2 py-0.5 rounded-lg font-medium",
            c.status === "active"
              ? "bg-green-100 text-green-700"
              : "bg-gray-100 text-gray-600"
          )}
        >
          {c.status}
        </span>
      </div>
    </div>
  );
}

// ── Prep Kit Modal ────────────────────────────────────────────────────────────

function PrepKitModal({
  candidateName,
  isLoading,
  error,
  data,
  onClose,
}: {
  candidateName: string;
  isLoading: boolean;
  error: string | null;
  data: any | null;
  onClose: () => void;
}) {
  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 overflow-y-auto">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl my-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-violet-600" />
            <h2 className="text-lg font-bold text-gray-900">Prep Kit — {candidateName}</h2>
          </div>
          <div className="flex items-center gap-2">
            {data && (
              <button
                onClick={handlePrint}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 text-gray-600"
              >
                <Printer className="w-3.5 h-3.5" />
                Drukuj
              </button>
            )}
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="p-6">
          {isLoading && (
            <div className="flex flex-col items-center justify-center py-12 text-gray-400 gap-3">
              <div className="w-8 h-8 border-3 border-violet-400 border-t-transparent rounded-full animate-spin border-[3px]" />
              <p className="text-sm">Generuję Prep Kit...</p>
            </div>
          )}

          {error && (
            <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {error}
            </div>
          )}

          {data && (
            <div className="space-y-5 print:space-y-4">
              {/* Client Overview */}
              <PrepKitSection icon="📋" title="O kliencie" color="blue">
                <p className="text-sm text-gray-700 whitespace-pre-line leading-relaxed">
                  {data.client_overview}
                </p>
              </PrepKitSection>

              {/* Likely Questions */}
              <PrepKitSection icon="❓" title="Prawdopodobne pytania" color="purple">
                <ul className="space-y-1.5">
                  {data.likely_questions.map((q: string, i: number) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                      <span className="text-purple-400 font-bold flex-shrink-0 mt-0.5">{i + 1}.</span>
                      {q}
                    </li>
                  ))}
                </ul>
              </PrepKitSection>

              {/* Strengths */}
              <PrepKitSection icon="💪" title="Mocne strony kandydata" color="green">
                <ul className="space-y-1.5">
                  {data.candidate_strengths.map((s: string, i: number) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                      <span className="text-emerald-500 flex-shrink-0 mt-0.5">✓</span>
                      {s}
                    </li>
                  ))}
                </ul>
              </PrepKitSection>

              {/* Gaps */}
              <PrepKitSection icon="⚠️" title="Potencjalne luki / zagrożenia" color="amber">
                <ul className="space-y-1.5">
                  {data.candidate_gaps.map((g: string, i: number) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                      <span className="text-amber-500 flex-shrink-0 mt-0.5">!</span>
                      {g}
                    </li>
                  ))}
                </ul>
              </PrepKitSection>

              {/* Selling Points */}
              <PrepKitSection icon="✨" title="Selling points (argumenty dla kandydata)" color="cyan">
                <ul className="space-y-1.5">
                  {data.selling_points.map((sp: string, i: number) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                      <span className="text-cyan-500 flex-shrink-0 mt-0.5">★</span>
                      {sp}
                    </li>
                  ))}
                </ul>
              </PrepKitSection>

              {/* Strategy */}
              <PrepKitSection icon="🎯" title="Rekomendowana strategia" color="violet">
                <p className="text-sm text-gray-700 leading-relaxed">
                  {data.recommended_strategy}
                </p>
              </PrepKitSection>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function PrepKitSection({
  icon,
  title,
  color,
  children,
}: {
  icon: string;
  title: string;
  color: "blue" | "purple" | "green" | "amber" | "cyan" | "violet";
  children: React.ReactNode;
}) {
  const colorMap = {
    blue:   "bg-blue-50 border-blue-200",
    purple: "bg-purple-50 border-purple-200",
    green:  "bg-emerald-50 border-emerald-200",
    amber:  "bg-amber-50 border-amber-200",
    cyan:   "bg-cyan-50 border-cyan-200",
    violet: "bg-violet-50 border-violet-200",
  };
  const titleColorMap = {
    blue:   "text-blue-800",
    purple: "text-purple-800",
    green:  "text-emerald-800",
    amber:  "text-amber-800",
    cyan:   "text-cyan-800",
    violet: "text-violet-800",
  };

  return (
    <div className={cn("rounded-xl border p-4", colorMap[color])}>
      <h3 className={cn("text-sm font-bold mb-2 flex items-center gap-2", titleColorMap[color])}>
        <span>{icon}</span>
        {title}
      </h3>
      {children}
    </div>
  );
}

// ── Pliki Tab ─────────────────────────────────────────────────────────────────

function PlikiTab({ candidateId, candidate, queryClient }: {
  candidateId: number;
  candidate: any;
  queryClient: any;
}) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const uploadFile = async (file: File) => {
    if (file.size > 10 * 1024 * 1024) {
      setUploadError("Plik jest zbyt duży. Maksymalny rozmiar to 10 MB.");
      return;
    }
    setUploading(true);
    setUploadError(null);
    setUploadSuccess(null);
    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/candidates/${candidateId}/cv`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err?.detail || "Błąd przesyłania pliku");
      }
      setUploadSuccess(`Plik "${file.name}" został przesłany pomyślnie`);
      queryClient.invalidateQueries({ queryKey: ["candidate", candidateId] });
    } catch (e: any) {
      setUploadError(e.message || "Błąd przesyłania pliku");
    } finally {
      setUploading(false);
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadFile(file);
    e.target.value = "";
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) uploadFile(file);
  };

  const handleDownload = () => {
    if (!candidate.cv_filename) return;
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    const url = `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/candidates/${candidateId}/cv-download`;
    const a = document.createElement("a");
    a.href = url;
    a.download = candidate.cv_filename;
    if (token) {
      // Fetch with auth and download
      fetch(url, { headers: { Authorization: `Bearer ${token}` } })
        .then(res => res.blob())
        .then(blob => {
          const blobUrl = URL.createObjectURL(blob);
          a.href = blobUrl;
          a.click();
          URL.revokeObjectURL(blobUrl);
        })
        .catch(() => window.open(url));
    } else {
      a.click();
    }
  };

  return (
    <div className="space-y-4">
      <SectionTitle>Dokumenty i CV</SectionTitle>

      {uploadError && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-4 py-2 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {uploadError}
        </div>
      )}
      {uploadSuccess && (
        <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-2">
          ✓ {uploadSuccess}
        </div>
      )}

      {candidate.cv_filename ? (
        <div className="flex items-center gap-3 p-4 bg-gray-50 rounded-xl border border-gray-200">
          <div className="w-10 h-10 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl flex items-center justify-center shadow-sm flex-shrink-0">
            <FileText className="w-5 h-5 text-blue-500" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-medium text-gray-900 truncate">{candidate.cv_filename}</p>
            {candidate.cv_parsed_at && (
              <p className="text-xs text-gray-400 mt-0.5">Wgrano: {formatDate(candidate.cv_parsed_at)}</p>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className="text-xs bg-green-100 text-green-700 px-2 py-1 rounded-lg font-medium">CV</span>
            <button
              onClick={handleDownload}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 text-gray-600 transition-colors"
            >
              <Upload className="w-3.5 h-3.5 rotate-180" />
              Pobierz
            </button>
          </div>
        </div>
      ) : (
        <EmptyState icon={<FileText className="w-10 h-10" />} text="Brak przesłanego CV" />
      )}

      {/* Upload dropzone */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.doc,.docx"
        className="hidden"
        onChange={handleFileInput}
      />
      <div
        onClick={() => !uploading && fileInputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`mt-4 border-2 border-dashed rounded-xl p-8 flex flex-col items-center gap-3 transition-colors cursor-pointer ${
          dragOver
            ? "border-blue-400 bg-blue-50 text-blue-600"
            : uploading
            ? "border-gray-200 text-gray-300 cursor-not-allowed"
            : "border-gray-200 text-gray-400 hover:border-blue-300 hover:text-blue-400"
        }`}
      >
        {uploading ? (
          <>
            <div className="w-8 h-8 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            <p className="text-sm font-medium text-blue-500">Przesyłanie...</p>
          </>
        ) : (
          <>
            <Upload className="w-8 h-8" />
            <p className="text-sm font-medium">
              {dragOver ? "Upuść plik tutaj" : "Przeciągnij plik lub kliknij, aby wgrać CV"}
            </p>
            <p className="text-xs">PDF, DOC, DOCX — max 10 MB</p>
          </>
        )}
      </div>
    </div>
  );
}

// ── Screeningi Tab ─────────────────────────────────────────────────────────────

const MOTIVATION_LABELS: Record<string, string> = {
  money: "💰 Pieniądze",
  growth: "📈 Rozwój",
  project: "🚀 Projekt",
  team: "👥 Zespół",
  work_mode: "🏠 Tryb pracy",
  stability: "🛡️ Stabilność",
  technology: "💻 Technologia",
  location: "📍 Lokalizacja",
};

const MOTIVATION_COLORS: Record<string, string> = {
  money: "bg-yellow-100 text-yellow-700 border-yellow-200",
  growth: "bg-green-100 text-green-700 border-green-200",
  project: "bg-blue-100 text-blue-700 border-blue-200",
  team: "bg-purple-100 text-purple-700 border-purple-200",
  work_mode: "bg-teal-100 text-teal-700 border-teal-200",
  stability: "bg-gray-100 text-gray-700 border-gray-200",
  technology: "bg-cyan-100 text-cyan-700 border-cyan-200",
  location: "bg-orange-100 text-orange-700 border-orange-200",
};

const SCREENING_TYPE_LABELS: Record<string, string> = {
  initial_screening: "Screening wstępny",
  prep_call: "Prep call",
  follow_up: "Follow-up",
};

const COUNTEROFFER_COLORS: Record<string, string> = {
  low: "bg-green-100 text-green-700",
  medium: "bg-amber-100 text-amber-700",
  high: "bg-red-100 text-red-700",
};

const SKILL_LEVEL_MAP: Record<string, { label: string; color: string }> = {
  confirmed: { label: "Potwierdzona", color: "bg-blue-600 text-white" },
  basic: { label: "Podstawowa", color: "bg-gray-200 text-gray-700" },
  none: { label: "Brak", color: "bg-red-100 text-red-600" },
};

interface ScreeningiTabProps {
  candidateId: number;
  screenings: any[];
  isLoading: boolean;
  showForm: boolean;
  setShowForm: (v: boolean) => void;
  createMutation: any;
  expandedScreenings: Set<number>;
  setExpandedScreenings: (fn: (prev: Set<number>) => Set<number>) => void;
}

function ScreeningiTab({
  candidateId,
  screenings,
  isLoading,
  showForm,
  setShowForm,
  createMutation,
  expandedScreenings,
  setExpandedScreenings,
}: ScreeningiTabProps) {
  const [form, setForm] = useState({
    screening_type: "initial_screening",
    motivation_primary: "",
    motivation_secondary: "",
    salary_expectation: "",
    salary_currency: "PLN",
    salary_negotiable: false,
    red_flags: "",
    personality_notes: "",
    readiness_to_change: "",
    counteroffer_risk: "",
    closing_strategy: "",
    overall_impression: "",
    verified_skills: [] as { skill: string; level: string; notes: string }[],
  });

  const [newSkill, setNewSkill] = useState({ skill: "", level: "confirmed", notes: "" });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    createMutation.mutate({
      candidate_id: candidateId,
      screening_type: form.screening_type,
      motivation_primary: form.motivation_primary || null,
      motivation_secondary: form.motivation_secondary || null,
      salary_expectation: form.salary_expectation ? parseInt(form.salary_expectation) : null,
      salary_currency: form.salary_currency,
      salary_negotiable: form.salary_negotiable,
      red_flags: form.red_flags || null,
      personality_notes: form.personality_notes || null,
      readiness_to_change: form.readiness_to_change ? parseInt(form.readiness_to_change) : null,
      counteroffer_risk: form.counteroffer_risk || null,
      closing_strategy: form.closing_strategy || null,
      overall_impression: form.overall_impression ? parseInt(form.overall_impression) : null,
      verified_skills: form.verified_skills,
    });
  };

  const toggleExpanded = (id: number) => {
    setExpandedScreenings((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">Ustrukturyzowane notatki ze screeningów</p>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Dodaj screening
        </button>
      </div>

      {/* Add screening form */}
      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="bg-blue-50 border border-blue-200 rounded-xl p-5 space-y-4"
        >
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-blue-900">Nowy screening</h3>
            <button type="button" onClick={() => setShowForm(false)} className="text-blue-400 hover:text-blue-600">
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Type */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-gray-600 block mb-1">Typ screeningu</label>
              <select
                value={form.screening_type}
                onChange={(e) => setForm({ ...form, screening_type: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="initial_screening">Screening wstępny</option>
                <option value="prep_call">Prep call</option>
                <option value="follow_up">Follow-up</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-600 block mb-1">Ogólne wrażenie (1-5)</label>
              <select
                value={form.overall_impression}
                onChange={(e) => setForm({ ...form, overall_impression: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">—</option>
                {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
          </div>

          {/* Motivation */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-gray-600 block mb-1">Motywacja główna</label>
              <select
                value={form.motivation_primary}
                onChange={(e) => setForm({ ...form, motivation_primary: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">—</option>
                {Object.entries(MOTIVATION_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-600 block mb-1">Motywacja dodatkowa</label>
              <select
                value={form.motivation_secondary}
                onChange={(e) => setForm({ ...form, motivation_secondary: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">—</option>
                {Object.entries(MOTIVATION_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
          </div>

          {/* Salary */}
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <label className="text-xs font-semibold text-gray-600 block mb-1">Oczekiwania finansowe</label>
              <input
                type="number"
                value={form.salary_expectation}
                onChange={(e) => setForm({ ...form, salary_expectation: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="np. 20000"
              />
            </div>
            <div className="flex items-end pb-1.5">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.salary_negotiable}
                  onChange={(e) => setForm({ ...form, salary_negotiable: e.target.checked })}
                  className="w-4 h-4 rounded accent-blue-600"
                />
                <span className="text-sm text-gray-700">Do negocjacji</span>
              </label>
            </div>
          </div>

          {/* Readiness + Counteroffer */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-gray-600 block mb-1">Gotowość do zmiany (1-5)</label>
              <select
                value={form.readiness_to_change}
                onChange={(e) => setForm({ ...form, readiness_to_change: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">—</option>
                {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-600 block mb-1">Ryzyko counteroffer</label>
              <select
                value={form.counteroffer_risk}
                onChange={(e) => setForm({ ...form, counteroffer_risk: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">—</option>
                <option value="low">Niskie</option>
                <option value="medium">Średnie</option>
                <option value="high">Wysokie</option>
              </select>
            </div>
          </div>

          {/* Skills */}
          <div>
            <label className="text-xs font-semibold text-gray-600 block mb-1">Zweryfikowane umiejętności</label>
            <div className="space-y-1.5 mb-2">
              {form.verified_skills.map((sk, i) => (
                <div key={i} className="flex items-center gap-2 text-xs bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg px-2 py-1.5">
                  <span className="font-medium text-gray-700">{sk.skill}</span>
                  <span className={cn("px-1.5 py-0.5 rounded text-xs", SKILL_LEVEL_MAP[sk.level]?.color)}>
                    {SKILL_LEVEL_MAP[sk.level]?.label}
                  </span>
                  {sk.notes && <span className="text-gray-400">{sk.notes}</span>}
                  <button
                    type="button"
                    onClick={() => setForm({ ...form, verified_skills: form.verified_skills.filter((_, j) => j !== i) })}
                    className="ml-auto text-gray-300 hover:text-red-400"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                value={newSkill.skill}
                onChange={(e) => setNewSkill({ ...newSkill, skill: e.target.value })}
                placeholder="Umiejętność"
                className="flex-1 border border-gray-200 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
              <select
                value={newSkill.level}
                onChange={(e) => setNewSkill({ ...newSkill, level: e.target.value })}
                className="border border-gray-200 rounded-lg px-2 py-1.5 text-xs focus:outline-none"
              >
                <option value="confirmed">Potwierdzona</option>
                <option value="basic">Podstawowa</option>
                <option value="none">Brak</option>
              </select>
              <button
                type="button"
                onClick={() => {
                  if (newSkill.skill) {
                    setForm({ ...form, verified_skills: [...form.verified_skills, { ...newSkill }] });
                    setNewSkill({ skill: "", level: "confirmed", notes: "" });
                  }
                }}
                className="px-2 py-1.5 bg-blue-600 text-white rounded-lg text-xs hover:bg-blue-700"
              >
                <Plus className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="text-xs font-semibold text-gray-600 block mb-1">Red flags</label>
            <textarea
              value={form.red_flags}
              onChange={(e) => setForm({ ...form, red_flags: e.target.value })}
              rows={2}
              className="w-full border border-red-100 bg-red-50/30 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-red-300 resize-none"
              placeholder="Wpisz ostrzeżenia..."
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-gray-600 block mb-1">Notatki osobowościowe</label>
            <textarea
              value={form.personality_notes}
              onChange={(e) => setForm({ ...form, personality_notes: e.target.value })}
              rows={2}
              className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-gray-600 block mb-1">Strategia zamknięcia</label>
            <textarea
              value={form.closing_strategy}
              onChange={(e) => setForm({ ...form, closing_strategy: e.target.value })}
              rows={2}
              className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            />
          </div>

          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setShowForm(false)} className="px-3 py-1.5 text-sm text-gray-600">
              Anuluj
            </button>
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-lg disabled:opacity-50"
            >
              {createMutation.isPending ? "Zapisuję..." : "Zapisz screening"}
            </button>
          </div>
        </form>
      )}

      {/* Screenings list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-10 text-gray-400">
          <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mr-2" />
          Ładowanie screeningów...
        </div>
      ) : screenings.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <Sparkles className="w-10 h-10 mx-auto mb-3 opacity-40" />
          <p className="text-sm">Brak screeningów dla tego kandydata</p>
        </div>
      ) : (
        <div className="space-y-3">
          {screenings.map((s: any) => {
            const isExpanded = expandedScreenings.has(s.id);
            const typeLabel = SCREENING_TYPE_LABELS[s.screening_type] || s.screening_type;
            return (
              <div key={s.id} className="border border-gray-200 rounded-xl overflow-hidden">
                {/* Header */}
                <button
                  onClick={() => toggleExpanded(s.id)}
                  className="w-full flex items-start justify-between p-4 hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-start gap-3 text-left">
                    <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5">
                      <Sparkles className="w-4 h-4 text-blue-600" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-semibold text-gray-900">{typeLabel}</span>
                        {s.overall_impression && (
                          <div className="flex gap-0.5">
                            {[1,2,3,4,5].map((n) => (
                              <Star
                                key={n}
                                className={cn("w-3 h-3", n <= s.overall_impression ? "text-amber-400 fill-amber-400" : "text-gray-200 fill-gray-200")}
                              />
                            ))}
                          </div>
                        )}
                        {s.counteroffer_risk && (
                          <span className={cn("px-1.5 py-0.5 rounded-full text-xs font-medium", COUNTEROFFER_COLORS[s.counteroffer_risk])}>
                            Counteroffer: {s.counteroffer_risk === "low" ? "Niskie" : s.counteroffer_risk === "medium" ? "Średnie" : "Wysokie"}
                          </span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-2 mt-1.5">
                        {s.motivation_primary && (
                          <span className={cn("px-2 py-0.5 rounded-full text-xs font-medium border", MOTIVATION_COLORS[s.motivation_primary] || "bg-gray-100 text-gray-600")}>
                            {MOTIVATION_LABELS[s.motivation_primary]}
                          </span>
                        )}
                        {s.motivation_secondary && (
                          <span className={cn("px-2 py-0.5 rounded-full text-xs font-medium border opacity-70", MOTIVATION_COLORS[s.motivation_secondary] || "bg-gray-100 text-gray-600")}>
                            {MOTIVATION_LABELS[s.motivation_secondary]}
                          </span>
                        )}
                        {s.salary_expectation && (
                          <span className="px-2 py-0.5 bg-gray-100 text-gray-700 rounded-full text-xs font-medium">
                            {s.salary_expectation.toLocaleString("pl-PL")} {s.salary_currency}
                            {s.salary_negotiable && " (neg.)"}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-400 mt-1">
                        {new Date(s.created_at).toLocaleDateString("pl-PL", { day: "numeric", month: "long", year: "numeric" })}
                      </p>
                    </div>
                  </div>
                  <ChevronDown className={cn("w-4 h-4 text-gray-400 transition-transform flex-shrink-0 mt-1", isExpanded && "rotate-180")} />
                </button>

                {/* Expanded details */}
                {isExpanded && (
                  <div className="px-4 pb-4 pt-0 border-t border-gray-100 space-y-3">
                    {/* Skills table */}
                    {s.verified_skills && s.verified_skills.length > 0 && (
                      <div>
                        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Zweryfikowane umiejętności</p>
                        <div className="overflow-hidden rounded-lg border border-gray-200">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="bg-gray-50 text-gray-500">
                                <th className="text-left px-3 py-2 font-medium">Umiejętność</th>
                                <th className="text-left px-3 py-2 font-medium">Poziom</th>
                                <th className="text-left px-3 py-2 font-medium">Notatki</th>
                              </tr>
                            </thead>
                            <tbody>
                              {s.verified_skills.map((sk: any, i: number) => (
                                <tr key={i} className="border-t border-gray-100">
                                  <td className="px-3 py-2 font-medium text-gray-800">{sk.skill}</td>
                                  <td className="px-3 py-2">
                                    <span className={cn("px-1.5 py-0.5 rounded text-xs font-medium", SKILL_LEVEL_MAP[sk.level]?.color || "bg-gray-100 text-gray-600")}>
                                      {SKILL_LEVEL_MAP[sk.level]?.label || sk.level}
                                    </span>
                                  </td>
                                  <td className="px-3 py-2 text-gray-500">{sk.notes || "—"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}

                    {/* Readiness */}
                    {s.readiness_to_change && (
                      <div>
                        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Gotowość do zmiany</p>
                        <div className="flex gap-1">
                          {[1,2,3,4,5].map((n) => (
                            <div key={n} className={cn("w-8 h-2 rounded-full", n <= s.readiness_to_change ? "bg-blue-500" : "bg-gray-200")} />
                          ))}
                          <span className="text-xs text-gray-500 ml-1">{s.readiness_to_change}/5</span>
                        </div>
                      </div>
                    )}

                    {/* Red flags */}
                    {s.red_flags && (
                      <div className="bg-red-50 border border-red-100 rounded-lg p-3">
                        <p className="text-xs font-semibold text-red-600 uppercase tracking-wide mb-1">Red Flags</p>
                        <p className="text-sm text-red-700">{s.red_flags}</p>
                      </div>
                    )}

                    {/* Personality notes */}
                    {s.personality_notes && (
                      <div>
                        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Notatki osobowościowe</p>
                        <p className="text-sm text-gray-700">{s.personality_notes}</p>
                      </div>
                    )}

                    {/* Closing strategy */}
                    {s.closing_strategy && (
                      <div className="bg-emerald-50 border border-emerald-100 rounded-lg p-3">
                        <p className="text-xs font-semibold text-emerald-600 uppercase tracking-wide mb-1">Strategia zamknięcia</p>
                        <p className="text-sm text-emerald-800">{s.closing_strategy}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
