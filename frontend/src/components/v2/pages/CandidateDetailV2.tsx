"use client";

import * as React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  AlertTriangle,
  ArrowLeft,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Download,
  FileSignature,
  FileText,
  Gauge,
  Link2,
  Linkedin,
  Mail,
  MapPin,
  MessageSquare,
  PencilLine,
  Phone,
  PhoneCall,
  Plus,
  Printer,
  RefreshCcw,
  ShieldAlert,
  Sparkles,
  Star,
  Target,
  User,
  UserPlus,
  Wallet,
  X,
} from "lucide-react";
import api, { contractsApi, type ContractDraftResponse } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CandidateEngagementPanel } from "@/components/candidates/CandidateEngagementPanel";
import { CandidateLocationPanel } from "@/components/candidates/CandidateLocationPanel";
import { cn, formatDate, formatRelativeTime } from "@/lib/utils";
import { useTabsStore } from "@/store/tabs";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { EditCandidateModal } from "@/components/AppShell";
import { ScreeningSheet } from "@/components/v2/modals/ScreeningSheet";
import { SendEmailV2 } from "@/components/v2/modals/SendEmailV2";
import { CVGeneratorV2 } from "@/components/v2/modals/CVGeneratorV2";
import { QuickAssignV2 } from "@/components/v2/modals/QuickAssignV2";
import { SuggestedJobsWidget } from "@/components/SuggestedJobsWidget";
import { SuggestedPoolsWidget } from "@/components/candidates/SuggestedPoolsWidget";
import EmailThreadList from "@/components/emails/EmailThreadList";
import ScheduleInterviewModal from "@/components/calendar/ScheduleInterviewModal";
import { CandidatePipelinesWidget } from "@/components/CandidatePipelinesWidget";
import { RateHistoryWidget } from "@/components/RateHistoryWidget";
import { ConflictsWidget } from "@/components/ConflictsWidget";
import { FirefliesTranscriptsWidget } from "@/components/FirefliesTranscriptsWidget";
import { AddToMarketplaceButton } from "@/components/marketplace/AddToMarketplaceButton";
import {
  AtOurClientBanner,
  CandidateHighlights,
} from "@/components/v2/CandidateHighlights";
import { LinkedinSyncPanel } from "@/components/v2/LinkedinSyncPanel";
import { ActiveViewers } from "@/components/v2/presence/ActiveViewers";
import { usePresence, type PresenceViewer } from "@/hooks/usePresence";
import { useAuthStore } from "@/store/auth";

const STATUS_VARIANT: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  active: "success",
  passive: "warning",
  blacklisted: "danger",
};
const STATUS_LABELS: Record<string, string> = {
  active: "Aktywny",
  passive: "Pasywny",
  blacklisted: "Zablokowany",
};

const SKILL_LEVEL_VARIANT: Record<
  string,
  "burgundy" | "success" | "warning" | "neutral"
> = {
  expert: "burgundy",
  senior: "success",
  mid: "warning",
  junior: "neutral",
};

interface CandidateDetailV2Props {
  /** When true, render without page frame (for side-sheet embedding). */
  embedded?: boolean;
  /** Optional override for route param. */
  candidateId?: number;
  /** Close handler for embedded mode. */
  onClose?: () => void;
}

export function CandidateDetailV2({
  embedded,
  candidateId,
  onClose,
}: CandidateDetailV2Props = {}) {
  const routeParams = useParams();
  const router = useRouter();
  const id = candidateId ?? Number(routeParams?.id);
  const queryClient = useQueryClient();
  const openTab = useTabsStore((s) => s.openTab);

  const [activeTab, setActiveTab] = useState("profil");
  const [emailOpen, setEmailOpen] = useState(false);
  const [cvOpen, setCvOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [screeningStage, setScreeningStage] = useState<number | null>(null);
  const [noteText, setNoteText] = useState("");
  const [noteSaving, setNoteSaving] = useState(false);

  // Presence: one subscription per candidate page; viewers + setEditing are
  // passed into children so the NotatkiTab can emit edit signals without
  // mounting a second hook instance.
  const currentUser = useAuthStore((s) => s.user);
  const { viewers: presenceViewers, setEditing: setPresenceEditing } =
    usePresence("candidate", Number.isFinite(Number(id)) ? Number(id) : null);

  const { data: candidate, isLoading } = useQuery({
    queryKey: ["candidate", id],
    queryFn: () => api.get(`/api/candidates/${id}`).then((r) => r.data),
    enabled: !!id,
  });

  useEffect(() => {
    if (candidate && !embedded) {
      const fullName = `${candidate.name} ${candidate.lastname}`.trim();
      openTab("candidate", Number(id), fullName);
    }
  }, [candidate, id, openTab, embedded]);

  // Timeline API returns `{ timeline: [...] }` — normalize to array.
  const { data: timelineRaw } = useQuery<{ timeline?: any[] } | any[]>({
    queryKey: ["candidate-timeline", id],
    queryFn: () =>
      api.get(`/api/candidates/${id}/timeline?limit=50`).then((r) => r.data),
    enabled: !!id && (activeTab === "timeline" || activeTab === "notatki"),
  });
  const timeline: any[] = Array.isArray(timelineRaw)
    ? timelineRaw
    : (timelineRaw?.timeline ?? []);

  // History API returns `{ jobs: [...], contracts: [...] }` — flatten jobs.
  const { data: historyRaw } = useQuery<{ jobs?: any[]; contracts?: any[] } | any[]>({
    queryKey: ["candidate-history", id],
    queryFn: () => api.get(`/api/candidates/${id}/history`).then((r) => r.data),
    enabled: !!id && activeTab === "rekrutacje",
  });
  const history: any[] = Array.isArray(historyRaw)
    ? historyRaw
    : (historyRaw?.jobs ?? []);
  const historyContracts: any[] = Array.isArray(historyRaw)
    ? []
    : (historyRaw?.contracts ?? []);

  // Screenings & calls may come as array or { items: [...] } — normalize both.
  const { data: screeningsRaw } = useQuery<{ items?: any[] } | any[]>({
    queryKey: ["candidate-screenings", id],
    queryFn: () => api.get(`/api/candidates/${id}/screenings`).then((r) => r.data),
    enabled: !!id && activeTab === "screeningi",
  });
  const screenings: any[] = Array.isArray(screeningsRaw)
    ? screeningsRaw
    : (screeningsRaw?.items ?? []);

  const { data: callsRaw } = useQuery<{ items?: any[] } | any[]>({
    queryKey: ["candidate-calls", id],
    queryFn: () => api.get(`/api/candidates/${id}/calls`).then((r) => r.data),
    enabled: !!id && activeTab === "rozmowy",
  });
  const calls: any[] = Array.isArray(callsRaw) ? callsRaw : (callsRaw?.items ?? []);

  const { data: aiProfile } = useQuery<any>({
    queryKey: ["candidate-ai-profile", id],
    queryFn: () => api.get(`/api/candidates/${id}/ai-profile`).then((r) => r.data),
    enabled: !!id,
  });

  // Lista umów kandydata — dla zakładki "Umowa". Backend już akceptuje
  // ?candidate_id w GET /api/contracts; zwraca paginowaną kopertę.
  const { data: candidateContractsRaw } = useQuery<{ items?: any[] } | any[]>({
    queryKey: ["candidate-contracts", id],
    queryFn: () =>
      contractsApi.byCandidate(Number(id)).then((r: any) => r.data),
    enabled: !!id && activeTab === "umowa",
  });
  const candidateContracts: any[] = Array.isArray(candidateContractsRaw)
    ? candidateContractsRaw
    : (candidateContractsRaw?.items ?? []);

  const handleAddNote = async () => {
    if (!noteText.trim()) return;
    setNoteSaving(true);
    try {
      await api.post("/api/notes/", {
        candidate_id: Number(id),
        content: noteText.trim(),
        note_type: "general",
      });
      setNoteText("");
      queryClient.invalidateQueries({ queryKey: ["candidate-timeline", id] });
    } finally {
      setNoteSaving(false);
    }
  };

  if (isLoading || !candidate) {
    return (
      <div className="flex items-center justify-center py-16 text-[hsl(var(--text-muted))]">
        <div className="text-sm">Ładowanie kandydata…</div>
      </div>
    );
  }

  const fullName = `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim();
  const initials = fullName
    .split(/\s+/)
    .map((w: string) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  const rootClass = embedded
    ? "space-y-4"
    : "max-w-6xl mx-auto space-y-5";

  return (
    <div className={rootClass}>
      {/* Back / close */}
      {embedded ? null : (
        <Link
          href="/candidates"
          className="inline-flex items-center gap-1 text-sm text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent))]"
        >
          <ArrowLeft className="h-4 w-4" /> Wróć do kandydatów
        </Link>
      )}

      {candidate.employment && (
        <AtOurClientBanner employment={candidate.employment} />
      )}

      {/* ── HERO CARD ── */}
      <Card variant="default" size="md" className="!p-0 overflow-hidden">
        {/* Top accent bar */}
        <div className="h-1 bg-gradient-to-r from-[hsl(var(--accent))] to-[hsl(var(--bg-chrome))]" />
        <div className="p-6">
          <div className="flex items-start gap-4 flex-wrap">
            <Avatar size="xl">
              <AvatarFallback>{initials}</AvatarFallback>
            </Avatar>

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="font-display text-2xl md:text-3xl font-extrabold tracking-[-0.02em] text-[hsl(var(--text-title))]">
                  {fullName}
                </h1>
                {candidate.status && STATUS_LABELS[candidate.status] && (
                  <Badge variant={STATUS_VARIANT[candidate.status] ?? "neutral"} size="md">
                    {STATUS_LABELS[candidate.status]}
                  </Badge>
                )}
                <CandidateHighlights candidate={candidate} variant="full" />
                {candidate.source === "linkedin" && (
                  <Badge variant="plum" size="sm">
                    <Linkedin className="h-3 w-3" />
                    LinkedIn
                  </Badge>
                )}
                {candidate.invite_source && (
                  <Badge
                    variant="soft"
                    size="sm"
                    title={
                      candidate.invite_source.previous_created_by_name
                        ? `Przejęty: ${candidate.invite_source.previous_created_by_name} → ${candidate.invite_source.created_by_name} (${formatDate(candidate.invite_source.applied_at)})`
                        : `Dodany przez ${candidate.invite_source.created_by_name} (${formatDate(candidate.invite_source.applied_at)})`
                    }
                  >
                    <Link2 className="h-3 w-3" />
                    Przez link
                    {candidate.invite_source.label
                      ? ` · ${candidate.invite_source.label}`
                      : ""}
                  </Badge>
                )}
              </div>
              {candidate.current_role && (
                <p className="text-sm text-[hsl(var(--text-body))] mt-0.5">
                  {candidate.current_role}
                </p>
              )}

              {/* Contact row */}
              <div className="flex items-center gap-4 flex-wrap mt-3 text-sm text-[hsl(var(--text-body))]">
                {candidate.email && (
                  <a
                    href={`mailto:${candidate.email}`}
                    className="inline-flex items-center gap-1.5 hover:text-[hsl(var(--accent))]"
                  >
                    <Mail className="h-3.5 w-3.5 text-[hsl(var(--text-muted))]" />
                    {candidate.email}
                  </a>
                )}
                {candidate.phone && (
                  <a
                    href={`tel:${candidate.phone}`}
                    className="inline-flex items-center gap-1.5 hover:text-[hsl(var(--accent))]"
                  >
                    <Phone className="h-3.5 w-3.5 text-[hsl(var(--text-muted))]" />
                    {candidate.phone}
                  </a>
                )}
                {candidate.location && (
                  <span className="inline-flex items-center gap-1.5">
                    <MapPin className="h-3.5 w-3.5 text-[hsl(var(--text-muted))]" />
                    {candidate.location}
                  </span>
                )}
                {candidate.linkedin_url && (
                  <a
                    href={candidate.linkedin_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 hover:text-[hsl(var(--accent))]"
                  >
                    <Linkedin className="h-3.5 w-3.5 text-[#0A66C2]" />
                    LinkedIn
                  </a>
                )}
              </div>

              {/* Tags */}
              {candidate.tags && candidate.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-3">
                  {candidate.tags.map((t: any, i: number) => (
                    <span
                      key={i}
                      className="text-xs px-2 py-0.5 rounded-full bg-[hsl(var(--accent-soft))] text-[hsl(var(--accent))]"
                    >
                      #{typeof t === "string" ? t : t.name}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Active viewers (presence) — other users currently on this candidate */}
            <ActiveViewers
              resourceType="candidate"
              resourceId={Number.isFinite(Number(id)) ? Number(id) : null}
              viewers={presenceViewers}
            />

            {/* Close button (embedded) */}
            {embedded && onClose && (
              <button
                onClick={onClose}
                aria-label="Zamknij"
                className="p-1.5 rounded-v2-s text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text-title))] hover:bg-[hsl(var(--accent-soft))]"
              >
                <X className="h-5 w-5" />
              </button>
            )}
          </div>

          {/* Action row */}
          <div className="flex items-center gap-2 flex-wrap mt-5">
            <Button
              size="sm"
              variant="primary"
              onClick={() => setAssignOpen(true)}
              disabled={!candidate}
            >
              <UserPlus className="h-4 w-4" />
              Przypisz do oferty
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setCvOpen(true)}
            >
              <FileText className="h-4 w-4" />
              Generuj CV
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setEmailOpen(true)}
              disabled={!candidate.email}
            >
              <Mail className="h-4 w-4" />
              Email
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setScheduleOpen(true)}
              disabled={!candidate.email}
              title={candidate.email ? "Zaplanuj interview w Outlook (M365)" : "Kandydat nie ma adresu email"}
            >
              <Calendar className="h-4 w-4" />
              Zaplanuj interview
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditOpen(true)}>
              <PencilLine className="h-4 w-4" />
              Edytuj
            </Button>
            {candidate && (
              <AddToMarketplaceButton
                candidateId={candidate.id}
                candidateName={`${candidate.name} ${candidate.lastname}`}
              />
            )}
          </div>

          {/* Key stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-5">
            <StatTile
              label="Oczekiwania"
              value={
                candidate.expected_salary
                  ? `${candidate.expected_salary.toLocaleString("pl-PL")} ${candidate.currency ?? "PLN"}`
                  : "—"
              }
            />
            <StatTile
              label="Wypowiedzenie"
              value={
                candidate.notice_period_weeks
                  ? `${candidate.notice_period_weeks * 7} dni`
                  : "—"
              }
            />
            <StatTile
              label="Dostępność"
              value={
                candidate.available_from
                  ? formatDate(candidate.available_from)
                  : "—"
              }
            />
            <StatTile
              label="Kategoria"
              value={candidate.competence_category ?? "—"}
            />
          </div>
        </div>
      </Card>

      {/* AI summary */}
      {aiProfile?.summary && (
        <Card variant="default" size="md" className="!py-4">
          <div className="flex items-start gap-2">
            <Sparkles className="h-4 w-4 text-[hsl(var(--accent))] shrink-0 mt-0.5" />
            <div className="flex-1">
              <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--accent))]">
                AI Summary
              </h3>
              <p className="text-sm text-[hsl(var(--text-body))] mt-1 italic">
                {aiProfile.summary}
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Sticky screening summary — always visible across tabs */}
      {aiProfile && aiProfile.screening_count > 0 && (
        <ScreeningSummary
          aiProfile={aiProfile}
          onOpenScreenings={() => setActiveTab("screeningi")}
        />
      )}

      {/* Suggested jobs (reuse v1 widget) */}
      <SuggestedJobsWidget candidateId={Number(id)} />

      {/* AI-suggested talent pools (migracja 0041) */}
      <SuggestedPoolsWidget candidateId={Number(id)} />

      {/* Tabs */}
      <Card variant="default" size="md" className="!p-0">
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="px-4 pt-2">
            <TabsTrigger value="profil">
              <User className="h-3.5 w-3.5" />
              Profil
            </TabsTrigger>
            <TabsTrigger value="timeline">
              <MessageSquare className="h-3.5 w-3.5" />
              Timeline
            </TabsTrigger>
            <TabsTrigger value="rekrutacje">
              <Calendar className="h-3.5 w-3.5" />
              Rekrutacje
              {history.length > 0 && (
                <Badge size="sm" variant="soft">
                  {history.length}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="screeningi">
              <Star className="h-3.5 w-3.5" />
              Screeningi
              {screenings.length > 0 && (
                <Badge size="sm" variant="soft">
                  {screenings.length}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="rozmowy">
              <PhoneCall className="h-3.5 w-3.5" />
              Rozmowy
            </TabsTrigger>
            <TabsTrigger value="email">
              <Mail className="h-3.5 w-3.5" />
              Email
            </TabsTrigger>
            <TabsTrigger value="notatki">
              <MessageSquare className="h-3.5 w-3.5" />
              Notatki
            </TabsTrigger>
            <TabsTrigger value="umowa">
              <FileSignature className="h-3.5 w-3.5" />
              Umowa
              {candidateContracts.some(
                (c: any) => c.status === "draft",
              ) && (
                <Badge size="sm" variant="warning">
                  draft
                </Badge>
              )}
            </TabsTrigger>
          </TabsList>

          <div className="p-5">
            <TabsContent value="profil" className="mt-0">
              <ProfilTab candidate={candidate} />
            </TabsContent>
            <TabsContent value="timeline" className="mt-0">
              <TimelineTab items={timeline ?? []} />
            </TabsContent>
            <TabsContent value="rekrutacje" className="mt-0">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="lg:col-span-2">
                  <RekrutacjeTab history={history} />
                </div>
                <div className="space-y-4">
                  <CandidatePipelinesWidget
                    candidateId={Number(id)}
                    employment={candidate.employment}
                  />
                </div>
              </div>
            </TabsContent>
            <TabsContent value="screeningi" className="mt-0">
              <ScreeningsTab screenings={screenings} />
            </TabsContent>
            <TabsContent value="rozmowy" className="mt-0">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <RozmowyTab calls={calls} />
                <FirefliesTranscriptsWidget candidateId={Number(id)} />
              </div>
            </TabsContent>
            <TabsContent value="email" className="mt-0">
              <EmailThreadList
                candidateId={Number(id)}
                candidateName={fullName}
                candidateEmail={candidate.email ?? null}
              />
            </TabsContent>
            <TabsContent value="notatki" className="mt-0">
              <NotatkiTab
                timeline={timeline ?? []}
                noteText={noteText}
                setNoteText={setNoteText}
                onAdd={handleAddNote}
                saving={noteSaving}
                viewers={presenceViewers}
                currentUserId={currentUser?.id}
                setEditing={setPresenceEditing}
              />
            </TabsContent>
            <TabsContent value="umowa" className="mt-0">
              <UmowaTab
                candidateId={Number(id)}
                candidateName={fullName}
                contracts={candidateContracts}
                jdgComplete={Boolean(
                  candidate.legal_name && candidate.nip,
                )}
                onJumpToProfile={() => setActiveTab("profil")}
              />
            </TabsContent>
          </div>
        </Tabs>
      </Card>

      {/* Side widgets (below tabs) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <RateHistoryWidget candidateId={Number(id)} />
        <ConflictsWidget candidateId={Number(id)} />
      </div>

      {/* ── Modals ── */}
      <SendEmailV2
        open={emailOpen}
        onOpenChange={setEmailOpen}
        candidateId={Number(id)}
        candidateName={fullName}
        candidateEmail={candidate.email ?? ""}
      />
      <CVGeneratorV2
        open={cvOpen}
        onOpenChange={setCvOpen}
        candidateId={Number(id)}
        candidateName={fullName}
      />
      <QuickAssignV2
        open={assignOpen}
        onOpenChange={setAssignOpen}
        candidateId={Number(id)}
        candidateName={fullName}
        onAssigned={() => {
          queryClient.invalidateQueries({ queryKey: ["candidate-history", id] });
          queryClient.invalidateQueries({ queryKey: ["suggested-jobs", id] });
        }}
      />
      {editOpen && candidate && (
        <EditCandidateModal
          candidate={candidate}
          onClose={() => setEditOpen(false)}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ["candidate", id] });
            setEditOpen(false);
          }}
        />
      )}
      <ScreeningSheet
        open={screeningStage !== null}
        onOpenChange={(v) => !v && setScreeningStage(null)}
        stageId={screeningStage ?? 0}
        candidateName={fullName}
        onSubmitted={() => {
          queryClient.invalidateQueries({ queryKey: ["candidate-screenings", id] });
          setScreeningStage(null);
        }}
      />
      <ScheduleInterviewModal
        open={scheduleOpen}
        onOpenChange={setScheduleOpen}
        candidateId={Number(id)}
        candidateName={fullName}
        candidateEmail={candidate.email ?? null}
      />
    </div>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────

function StatTile({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-v2-m bg-[hsl(var(--bg-canvas))]/60 border border-[hsl(var(--border-subtle))] px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))]">
        {label}
      </div>
      <div className="text-sm font-bold text-[hsl(var(--text-title))] mt-0.5">
        {value}
      </div>
    </div>
  );
}

// ─── Dane do umowy (JDG) ─────────────────────────────────────────────────

interface JDGPanelInitial {
  legal_name?: string | null;
  nip?: string | null;
  regon?: string | null;
  business_address?: string | null;
  business_form?: string | null;
}

const BUSINESS_FORM_OPTIONS: { value: string; label: string }[] = [
  { value: "jdg", label: "JDG (jednoosobowa)" },
  { value: "sp_zoo", label: "Sp. z o.o." },
  { value: "sa", label: "S.A." },
  { value: "sc", label: "Spółka cywilna" },
  { value: "osoba_fizyczna", label: "Osoba fizyczna (UoP/zlecenie)" },
];

function JDGPanel({
  candidateId,
  initial,
}: {
  candidateId: number;
  initial: JDGPanelInitial;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [form, setForm] = useState({
    legal_name: initial.legal_name ?? "",
    nip: initial.nip ?? "",
    regon: initial.regon ?? "",
    business_address: initial.business_address ?? "",
    business_form: initial.business_form ?? "",
  });

  const dirty =
    form.legal_name !== (initial.legal_name ?? "") ||
    form.nip !== (initial.nip ?? "") ||
    form.regon !== (initial.regon ?? "") ||
    form.business_address !== (initial.business_address ?? "") ||
    form.business_form !== (initial.business_form ?? "");

  const save = useMutation({
    mutationFn: () =>
      api.patch(`/api/candidates/${candidateId}`, {
        legal_name: form.legal_name || null,
        nip: form.nip || null,
        regon: form.regon || null,
        business_address: form.business_address || null,
        business_form: form.business_form || null,
      }),
    onSuccess: () => {
      showSuccess("Zapisano dane do umowy");
      queryClient.invalidateQueries({ queryKey: ["candidate", candidateId] });
    },
    onError: () => showError("Nie udało się zapisać danych JDG"),
  });

  return (
    <Card variant="default" size="md">
      <CardHeader className="!pb-2">
        <CardTitle className="text-sm font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] flex items-center gap-2">
          <FileSignature className="h-3.5 w-3.5" />
          Dane do umowy (JDG / firma)
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <Label className="text-xs">Nazwa prawna</Label>
            <Input
              value={form.legal_name}
              onChange={(e) =>
                setForm((f) => ({ ...f, legal_name: e.target.value }))
              }
              placeholder="np. Jan Kowalski JDG"
            />
          </div>
          <div>
            <Label className="text-xs">Forma działalności</Label>
            <select
              className="w-full rounded-v2-m border border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-surface))] px-3 py-2 text-sm"
              value={form.business_form}
              onChange={(e) =>
                setForm((f) => ({ ...f, business_form: e.target.value }))
              }
            >
              <option value="">— wybierz —</option>
              {BUSINESS_FORM_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label className="text-xs">NIP</Label>
            <Input
              value={form.nip}
              onChange={(e) => setForm((f) => ({ ...f, nip: e.target.value }))}
              placeholder="np. PL5252000000"
            />
          </div>
          <div>
            <Label className="text-xs">REGON</Label>
            <Input
              value={form.regon}
              onChange={(e) =>
                setForm((f) => ({ ...f, regon: e.target.value }))
              }
            />
          </div>
        </div>
        <div>
          <Label className="text-xs">Adres siedziby</Label>
          <Textarea
            value={form.business_address}
            onChange={(e) =>
              setForm((f) => ({ ...f, business_address: e.target.value }))
            }
            placeholder="ul. Marszałkowska 1, 00-001 Warszawa"
            rows={2}
          />
        </div>
        <div className="flex justify-end">
          <Button
            size="sm"
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? "Zapisuję…" : "Zapisz"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Zakładka Umowa ──────────────────────────────────────────────────────

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  active: "Aktywna",
  ending: "Wygasa",
  ended: "Zakończona",
};

function formatRate(
  amount: number | null | undefined,
  currency: string | null | undefined,
  unit: string | null | undefined,
): string {
  if (amount == null) return "—";
  const unitLabel =
    unit === "hourly" ? "/h" : unit === "daily" ? "/d" : "/mies.";
  return `${amount.toLocaleString("pl-PL")} ${currency ?? "PLN"}${unitLabel}`;
}

function UmowaTab({
  candidateId,
  candidateName,
  contracts,
  jdgComplete,
  onJumpToProfile,
}: {
  candidateId: number;
  candidateName: string;
  contracts: any[];
  jdgComplete: boolean;
  onJumpToProfile: () => void;
}) {
  const sorted = useMemo(() => {
    const order: Record<string, number> = {
      active: 0,
      ending: 1,
      draft: 2,
      ended: 3,
    };
    return [...contracts].sort((a, b) => {
      const so = (order[a.status] ?? 9) - (order[b.status] ?? 9);
      if (so !== 0) return so;
      return (b.start_date ?? "").localeCompare(a.start_date ?? "");
    });
  }, [contracts]);

  const current = sorted.find(
    (c) => c.status === "active" || c.status === "ending",
  );
  const draft = sorted.find((c) => c.status === "draft");
  const history = sorted.filter((c) => c.status === "ended");
  const [historyOpen, setHistoryOpen] = useState(false);

  return (
    <div className="space-y-5">
      {!jdgComplete && (
        <Card variant="default" size="md" className="border-l-4 border-l-amber-500">
          <CardContent className="py-3 flex items-center justify-between gap-3 flex-wrap">
            <div className="text-sm flex items-center gap-2 text-[hsl(var(--text-body))]">
              <AlertTriangle className="h-4 w-4 text-amber-600" />
              Brak danych do umowy (nazwa prawna / NIP). Bez nich szablon
              wyrenderuje puste pola.
            </div>
            <Button size="sm" variant="outline" onClick={onJumpToProfile}>
              Uzupełnij w Profilu
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Aktualna umowa */}
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-2">
          Aktualna umowa
        </h3>
        {current ? (
          <CurrentContractCard contract={current} />
        ) : (
          <Card variant="default" size="md">
            <CardContent className="py-6 text-center text-sm text-[hsl(var(--text-muted))]">
              Brak aktywnej umowy.
            </CardContent>
          </Card>
        )}
      </section>

      {/* Draft */}
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-2">
          Draft do edycji
        </h3>
        {draft ? (
          <DraftEditor
            contractId={draft.id}
            candidateName={candidateName}
            contractMeta={draft}
          />
        ) : (
          <Card variant="default" size="md">
            <CardContent className="py-6 text-center text-sm text-[hsl(var(--text-muted))]">
              Brak draftu. Draft tworzy się automatycznie gdy kandydat
              przechodzi w pipeline na status <code>hired</code>, albo można
              utworzyć ręcznie umowę z poziomu listy{" "}
              <Link
                href="/contracts"
                className="text-[hsl(var(--accent))] underline"
              >
                kontraktów
              </Link>
              .
            </CardContent>
          </Card>
        )}
      </section>

      {/* Historia */}
      {history.length > 0 && (
        <section>
          <button
            type="button"
            onClick={() => setHistoryOpen((v) => !v)}
            className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent))] flex items-center gap-1"
          >
            {historyOpen ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
            Historia ({history.length})
          </button>
          {historyOpen && (
            <div className="mt-2 space-y-2">
              {history.map((c) => (
                <Card key={c.id} variant="default" size="md">
                  <CardContent className="py-3 text-sm flex items-center justify-between gap-2">
                    <div>
                      <div className="font-medium">
                        {c.client_name ?? `Klient #${c.client_id}`}
                      </div>
                      <div className="text-xs text-[hsl(var(--text-muted))]">
                        {formatDate(c.start_date)} —{" "}
                        {c.end_date ? formatDate(c.end_date) : "?"} ·{" "}
                        {c.contract_type?.toUpperCase()}
                      </div>
                    </div>
                    {c.termination_reason && (
                      <Badge variant="neutral" size="sm">
                        {c.termination_reason}
                      </Badge>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function CurrentContractCard({ contract }: { contract: any }) {
  const { data: docs } = useQuery<any[]>({
    queryKey: ["contract-docs", contract.id],
    queryFn: () => contractsApi.documents(contract.id).then((r: any) => r.data),
  });
  const documents = docs ?? [];

  return (
    <Card variant="default" size="md">
      <CardContent className="space-y-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="font-semibold text-[hsl(var(--text-title))]">
              {contract.client_name ?? `Klient #${contract.client_id}`}
              {contract.project_name ? ` · ${contract.project_name}` : ""}
            </div>
            <div className="text-xs text-[hsl(var(--text-muted))]">
              {formatDate(contract.start_date)} —{" "}
              {contract.end_date ? formatDate(contract.end_date) : "open-ended"}
            </div>
          </div>
          <div className="flex gap-2 items-center">
            <Badge
              variant={contract.status === "ending" ? "warning" : "success"}
              size="md"
            >
              {STATUS_LABEL[contract.status] ?? contract.status}
            </Badge>
            <Link
              href={`/contracts/${contract.id}`}
              className="text-xs text-[hsl(var(--accent))] underline"
            >
              Zarządzaj kontraktem →
            </Link>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <StatTile
            label="Stawka kandydata"
            value={formatRate(
              contract.rate_candidate,
              contract.currency,
              contract.rate_unit,
            )}
          />
          <StatTile
            label="Stawka klienta"
            value={formatRate(
              contract.rate_client,
              contract.currency,
              contract.rate_unit,
            )}
          />
          <StatTile
            label="Marża"
            value={formatRate(
              contract.margin,
              contract.currency,
              contract.rate_unit,
            )}
          />
          <StatTile
            label="Tryb pracy"
            value={contract.work_mode ?? "—"}
          />
        </div>
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-2">
            Dokumenty
          </div>
          {documents.length === 0 ? (
            <div className="text-xs text-[hsl(var(--text-muted))]">
              Brak załączników. Dodasz je z poziomu strony kontraktu.
            </div>
          ) : (
            <ul className="space-y-1">
              {documents.map((d: any) => (
                <li
                  key={d.id}
                  className="flex items-center justify-between text-sm"
                >
                  <span className="flex items-center gap-2">
                    <FileText className="h-3.5 w-3.5 text-[hsl(var(--text-muted))]" />
                    {d.filename}
                    <Badge variant="neutral" size="sm">
                      {d.doc_type}
                    </Badge>
                  </span>
                  <a
                    href={contractsApi.documentDownloadUrl(contract.id, d.id)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-[hsl(var(--accent))] inline-flex items-center gap-1"
                  >
                    <Download className="h-3 w-3" /> pobierz
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function DraftEditor({
  contractId,
  candidateName,
  contractMeta,
}: {
  contractId: number;
  candidateName: string;
  contractMeta: any;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [confirmFinalize, setConfirmFinalize] = useState(false);
  const [confirmTemplateId, setConfirmTemplateId] = useState<number | null>(
    null,
  );

  const { data, isLoading } = useQuery<ContractDraftResponse>({
    queryKey: ["contract-draft", contractId],
    queryFn: () => contractsApi.draft.get(contractId).then((r) => r.data),
  });

  const editor = useEditor({
    extensions: [StarterKit],
    content: "",
    editorProps: {
      attributes: {
        class:
          "prose prose-sm max-w-none min-h-[400px] focus:outline-none border border-[hsl(var(--border-subtle))] rounded-v2-m bg-white p-4",
      },
    },
  });

  // Hydrate editor when draft is loaded the first time / after re-render swap.
  const lastLoadedSig = useRef<string | null>(null);
  useEffect(() => {
    if (!editor || !data) return;
    const sig = `${data.template_id ?? ""}:${data.updated_at ?? ""}`;
    if (sig === lastLoadedSig.current) return;
    lastLoadedSig.current = sig;
    editor.commands.setContent(data.content_html ?? "<p></p>", false);
  }, [editor, data]);

  // Debounced autosave for manual edits.
  const dirtyRef = useRef(false);
  const saveMutation = useMutation({
    mutationFn: (html: string) =>
      contractsApi.draft.update(contractId, { content_html: html }),
    onSuccess: () => {
      showSuccess("Zapisano draft");
      queryClient.invalidateQueries({ queryKey: ["contract-draft", contractId] });
    },
    onError: () => showError("Nie udało się zapisać draftu"),
  });

  useEffect(() => {
    if (!editor) return;
    const handler = () => {
      dirtyRef.current = true;
    };
    editor.on("update", handler);
    return () => {
      editor.off("update", handler);
    };
  }, [editor]);

  useEffect(() => {
    if (!editor) return;
    const id = setInterval(() => {
      if (dirtyRef.current && !saveMutation.isPending) {
        dirtyRef.current = false;
        saveMutation.mutate(editor.getHTML());
      }
    }, 2000);
    return () => clearInterval(id);
  }, [editor, saveMutation]);

  const swapTemplate = useMutation({
    mutationFn: (templateId: number) =>
      contractsApi.draft.update(contractId, { template_id: templateId }),
    onSuccess: () => {
      showSuccess("Wczytano nowy szablon");
      lastLoadedSig.current = null; // force editor re-hydration
      queryClient.invalidateQueries({ queryKey: ["contract-draft", contractId] });
    },
    onError: () => showError("Nie udało się wczytać szablonu"),
  });

  const finalize = useMutation({
    mutationFn: () => contractsApi.draft.finalize(contractId),
    onSuccess: () => {
      showSuccess("Umowa sfinalizowana — status: aktywna");
      setConfirmFinalize(false);
      queryClient.invalidateQueries({
        queryKey: ["candidate-contracts"],
      });
      queryClient.invalidateQueries({
        queryKey: ["contract-draft", contractId],
      });
    },
    onError: (err: unknown) => {
      const detail =
        err && typeof err === "object" && "response" in err
          ? (err as any).response?.data?.detail
          : null;
      if (detail && typeof detail === "object" && Array.isArray(detail.missing)) {
        showError(`Uzupełnij wymagane pola: ${detail.missing.join(", ")}`);
      } else {
        showError("Nie udało się sfinalizować draftu");
      }
    },
  });

  if (isLoading || !data) {
    return (
      <Card variant="default" size="md">
        <CardContent className="py-6 text-center text-sm text-[hsl(var(--text-muted))]">
          Ładowanie draftu…
        </CardContent>
      </Card>
    );
  }

  const lastSaved = data.updated_at
    ? `zapisano ${formatRelativeTime(data.updated_at)}`
    : "jeszcze nie zapisano";

  return (
    <Card variant="default" size="md">
      <CardContent className="space-y-3">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <div className="text-sm text-[hsl(var(--text-muted))]">
              Draft umowy dla <strong>{candidateName}</strong> — kontrakt #
              {contractId}
              {contractMeta.client_name
                ? ` (${contractMeta.client_name})`
                : ""}
            </div>
            <div className="text-xs text-[hsl(var(--text-muted))]">
              {lastSaved}
              {data.updated_by_name ? ` przez ${data.updated_by_name}` : ""}
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <select
              className="rounded-v2-m border border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-surface))] px-2 py-1 text-xs"
              value={data.template_id ?? ""}
              onChange={(e) => {
                const newId = Number(e.target.value);
                if (newId && newId !== data.template_id) {
                  setConfirmTemplateId(newId);
                }
              }}
            >
              <option value="">— wybierz szablon —</option>
              {data.available_templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                  {t.is_default ? " (domyślny)" : ""}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                window.open(
                  contractsApi.draft.printableUrl(contractId),
                  "_blank",
                )
              }
              disabled={!data.content_html}
              title="Otwiera HTML w nowej karcie z auto-print → Save as PDF"
            >
              <Printer className="h-3.5 w-3.5" /> Drukuj / PDF
            </Button>
            <Button
              size="sm"
              onClick={() => setConfirmFinalize(true)}
              disabled={!data.content_html || finalize.isPending}
            >
              <CheckCircle2 className="h-3.5 w-3.5" /> Sfinalizuj umowę
            </Button>
          </div>
        </div>

        {data.available_templates.length === 0 && (
          <div className="text-xs text-amber-600 flex items-center gap-1">
            <AlertTriangle className="h-3.5 w-3.5" />
            Brak szablonu dla typu <code>{contractMeta.contract_type}</code>.
            Dodaj szablon w panelu administracyjnym.
          </div>
        )}

        <EditorContent editor={editor} />

        {saveMutation.isPending && (
          <div className="text-xs text-[hsl(var(--text-muted))] flex items-center gap-1">
            <RefreshCcw className="h-3 w-3 animate-spin" /> Zapisywanie…
          </div>
        )}
      </CardContent>

      {/* Modal: confirm template swap (overwrites manual edits) */}
      {confirmTemplateId !== null && (
        <ConfirmModal
          title="Wczytać nowy szablon?"
          message="Przełączenie szablonu nadpisze obecną treść draftu. Zapisane edycje zostaną stracone."
          confirmLabel="Wczytaj szablon"
          onConfirm={() => {
            swapTemplate.mutate(confirmTemplateId);
            setConfirmTemplateId(null);
          }}
          onCancel={() => setConfirmTemplateId(null)}
        />
      )}

      {/* Modal: confirm finalize */}
      {confirmFinalize && (
        <ConfirmModal
          title="Sfinalizować draft?"
          message="Bieżąca treść zostanie zapisana jako dokument umowy, a status kontraktu zmieni się z draft na active. Edycja w tym widoku nie będzie już możliwa."
          confirmLabel={finalize.isPending ? "Finalizuję…" : "Tak, finalizuj"}
          onConfirm={() => finalize.mutate()}
          onCancel={() => setConfirmFinalize(false)}
        />
      )}
    </Card>
  );
}

function ConfirmModal({
  title,
  message,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onCancel}
    >
      <Card
        variant="default"
        size="md"
        className="max-w-md w-full mx-4"
        onClick={(e: React.MouseEvent) => e.stopPropagation()}
      >
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-[hsl(var(--text-body))]">{message}</p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={onCancel}>
              Anuluj
            </Button>
            <Button size="sm" onClick={onConfirm}>
              {confirmLabel}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function ProfilTab({ candidate }: { candidate: any }) {
  const skills: any[] = candidate.skills ?? [];
  const experience: any[] = candidate.experience ?? [];
  const aiSummary: string | null = candidate.ai_summary ?? null;
  const aiCompanies: string[] = candidate.cv_extracted_data?.companies ?? [];
  const aiSource: string = candidate.cv_extracted_data?._source ?? "";
  const aiBadge = aiSource.startsWith("claude") || aiSource.startsWith("ollama");

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <CandidateEngagementPanel
          candidateId={candidate.id}
          initial={{
            is_ambassador: candidate.is_ambassador,
            wants_to_verify_candidates: candidate.wants_to_verify_candidates,
            open_to_side_projects: candidate.open_to_side_projects,
            open_to_sales_support: candidate.open_to_sales_support,
            open_to_expert_consult: candidate.open_to_expert_consult,
            open_to_side_projects_updated_at:
              candidate.open_to_side_projects_updated_at,
            open_to_sales_support_updated_at:
              candidate.open_to_sales_support_updated_at,
            open_to_expert_consult_updated_at:
              candidate.open_to_expert_consult_updated_at,
            engagement_notes: candidate.engagement_notes,
          }}
        />
        <CandidateLocationPanel
          candidateId={candidate.id}
          initial={{
            city: candidate.city,
            country: candidate.country,
            region: candidate.region,
            hub_city: candidate.hub_city,
          }}
        />
      </div>

      <JDGPanel
        candidateId={candidate.id}
        initial={{
          legal_name: candidate.legal_name,
          nip: candidate.nip,
          regon: candidate.regon,
          business_address: candidate.business_address,
          business_form: candidate.business_form,
        }}
      />


      {aiSummary && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-2 flex items-center gap-2">
            Podsumowanie AI
            {aiBadge && (
              <Badge size="sm" variant="info">
                AI
              </Badge>
            )}
          </h3>
          <p className="text-sm text-[hsl(var(--text-body))] whitespace-pre-line">
            {aiSummary}
          </p>
        </section>
      )}

      {candidate.about && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-2">
            O sobie
          </h3>
          <p className="text-sm text-[hsl(var(--text-body))] whitespace-pre-line">
            {candidate.about}
          </p>
        </section>
      )}

      {aiCompanies.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-2 flex items-center gap-2">
            Firmy z CV
            {aiBadge && (
              <Badge size="sm" variant="info">
                AI
              </Badge>
            )}
          </h3>
          <div className="flex flex-wrap gap-2">
            {aiCompanies.map((name: string, i: number) => (
              <div
                key={i}
                className="inline-flex items-center px-3 py-1.5 rounded-v2-m bg-[hsl(var(--bg-surface))] border border-[hsl(var(--border-subtle))]"
              >
                <span className="text-sm font-medium text-[hsl(var(--text-title))]">
                  {name}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {skills.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-2">
            Umiejętności
          </h3>
          <div className="flex flex-wrap gap-2">
            {skills.map((s: any, i: number) => (
              <div
                key={i}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-v2-m bg-[hsl(var(--bg-surface))] border border-[hsl(var(--border-subtle))]"
              >
                <span className="text-sm font-medium text-[hsl(var(--text-title))]">
                  {s.name}
                </span>
                {s.level && (
                  <Badge
                    size="sm"
                    variant={SKILL_LEVEL_VARIANT[s.level] ?? "neutral"}
                  >
                    {s.level}
                  </Badge>
                )}
                {s.years && (
                  <span className="text-[10px] text-[hsl(var(--text-muted))]">
                    {s.years}l
                  </span>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <LinkedinSyncPanel candidate={candidate} />

      {experience.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-3 flex items-center gap-2">
            Doświadczenie zawodowe
            {aiBadge && (
              <Badge size="sm" variant="info">
                AI
              </Badge>
            )}
          </h3>
          <div className="space-y-3">
            {experience.map((exp: any, i: number) => {
              // Backend schema: {company, role, start, end, desc}
              // Legacy imports may still use: {title, start_date, end_date, description}
              const role = exp.role ?? exp.title ?? "";
              const company = exp.company ?? "";
              const start = exp.start ?? exp.start_date ?? "";
              const end = exp.end ?? exp.end_date ?? "";
              const desc = exp.desc ?? exp.description ?? "";
              const location = exp.location ?? "";
              return (
                <div
                  key={i}
                  className="rounded-v2-m bg-[hsl(var(--bg-canvas))]/40 border border-[hsl(var(--border-subtle))] p-3"
                >
                  <div className="flex items-start justify-between gap-2 flex-wrap">
                    <div className="min-w-0">
                      {role && (
                        <div className="font-medium text-[hsl(var(--text-title))]">
                          {role}
                        </div>
                      )}
                      <div className="text-xs text-[hsl(var(--text-muted))]">
                        {company}
                        {location ? ` · ${location}` : ""}
                      </div>
                    </div>
                    {(start || end) && (
                      <div className="text-xs text-[hsl(var(--text-muted))] whitespace-nowrap">
                        {start ? formatDate(start) : ""} —{" "}
                        {end ? formatDate(end) : "obecnie"}
                      </div>
                    )}
                  </div>
                  {desc && (
                    <p className="text-sm text-[hsl(var(--text-body))] mt-2 whitespace-pre-line">
                      {desc}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

const TIMELINE_LABEL: Record<string, string> = {
  note: "Notatka",
  stage_change: "Zmiana etapu",
  activity: "Aktywność",
  user_activity: "Akcja użytkownika",
};

// 0045_rejection_emails — map scheduler activity actions to Polish labels.
const REJECTION_EMAIL_ACTION_LABELS: Record<string, string> = {
  rejection_email_scheduled: "Zaplanowano email odrzucenia (wyśle się za 15 min)",
  rejection_email_sent: "Wysłano email odrzucenia do kandydata",
  rejection_email_cancelled: "Anulowano wysyłkę email odrzucenia",
  rejection_email_skipped: "Email odrzucenia pominięty — brak skrzynki MS365",
  rejection_email_failed: "Email odrzucenia — błąd wysyłki",
};

function timelineItemLabel(item: any): string {
  if (item.type === "note") return `Notatka${item.note_type ? ` — ${item.note_type}` : ""}`;
  if (item.type === "stage_change")
    return `Etap: ${item.stage}${item.job_title ? ` (${item.job_title})` : ""}`;
  if (item.type === "activity") {
    if (item.action === "applied_via_invite") {
      const owner = item.user_name ?? "rekruter";
      const prev = item.previous_created_by_name;
      return prev
        ? `Przejęto opiekę: ${prev} → ${owner} (apply przez link)`
        : `Aplikacja przez link (${owner})`;
    }
    const rejectionLabel = REJECTION_EMAIL_ACTION_LABELS[item.action];
    if (rejectionLabel) return rejectionLabel;
    return item.action ?? "Aktywność";
  }
  if (item.type === "user_activity") return item.action_type ?? "Akcja";
  return TIMELINE_LABEL[item.type] ?? item.type ?? "Zdarzenie";
}

function TimelineTab({ items }: { items: any[] }) {
  if (!Array.isArray(items) || items.length === 0) {
    return (
      <div className="py-10 text-center text-sm text-[hsl(var(--text-muted))]">
        Brak zdarzeń w timeline.
      </div>
    );
  }
  return (
    <div className="space-y-0">
      {items.map((item: any, i: number) => (
        <div
          key={`${item.type}-${item.id}-${i}`}
          className="flex gap-3 py-2.5 border-b border-[hsl(var(--border-subtle))]/50 last:border-0"
        >
          <div className="w-7 h-7 rounded-full bg-[hsl(var(--accent-soft))] text-[hsl(var(--accent))] flex items-center justify-center shrink-0 mt-0.5">
            <MessageSquare className="h-3.5 w-3.5" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-sm font-medium text-[hsl(var(--text-title))]">
                {timelineItemLabel(item)}
              </span>
              <span className="ml-auto text-xs text-[hsl(var(--text-muted))]">
                {item.timestamp ? formatRelativeTime(item.timestamp) : ""}
              </span>
            </div>
            {item.content && (
              <p className="text-sm text-[hsl(var(--text-body))] mt-1 whitespace-pre-line">
                {item.content}
              </p>
            )}
            {item.notes && (
              <p className="text-sm text-[hsl(var(--text-muted))] mt-1 italic whitespace-pre-line">
                {item.notes}
              </p>
            )}
            {item.rating && (
              <div className="flex gap-0.5 mt-1">
                {[1, 2, 3, 4, 5].map((n) => (
                  <Star
                    key={n}
                    className={cn(
                      "h-3.5 w-3.5",
                      n <= item.rating
                        ? "text-amber-500 fill-amber-500"
                        : "text-[hsl(var(--border-subtle))] fill-[hsl(var(--border-subtle))]"
                    )}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function RekrutacjeTab({ history }: { history: any[] }) {
  if (!Array.isArray(history) || history.length === 0) {
    return (
      <div className="py-10 text-center text-sm text-[hsl(var(--text-muted))]">
        Kandydat nie ma aktywnych rekrutacji.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {history.map((job: any, i: number) => (
        <Link
          key={i}
          href={`/jobs/${job.job_id ?? job.id}`}
          className="block rounded-v2-m border border-[hsl(var(--border-subtle))] hover:border-[hsl(var(--accent))]/40 p-3 transition-colors"
        >
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="min-w-0 flex-1">
              <div className="font-medium text-[hsl(var(--text-title))] truncate">
                {job.job_title ?? `Oferta #${job.job_id ?? job.id}`}
              </div>
              <div className="text-xs text-[hsl(var(--text-muted))]">
                {job.latest_stage ?? "—"}
                {job.first_seen
                  ? ` · dodano ${formatDate(job.first_seen)}`
                  : ""}
              </div>
              {Array.isArray(job.stages) && job.stages.length > 0 && (
                <div className="flex items-center gap-1.5 flex-wrap mt-1.5">
                  {job.stages.slice(0, 6).map((s: any, si: number) => (
                    <Badge key={si} size="sm" variant="soft">
                      {s.stage}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </div>
        </Link>
      ))}
    </div>
  );
}

const SCREENING_TYPE_LABELS: Record<string, string> = {
  first_contact: "Pierwszy kontakt",
  technical: "Techniczny",
  soft_skills: "Soft skills",
  offer_negotiation: "Negocjacja oferty",
  general: "Ogólny",
};

function ScreeningsTab({ screenings }: { screenings: any[] }) {
  if (!Array.isArray(screenings) || screenings.length === 0) {
    return (
      <div className="py-10 text-center text-sm text-[hsl(var(--text-muted))]">
        Kandydat nie ma jeszcze żadnych screeningów.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {screenings.map((s: any) => (
        <div
          key={s.id}
          className="rounded-v2-m border border-[hsl(var(--border-subtle))] p-3 hover:border-[hsl(var(--accent))]/40 transition-colors"
        >
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium text-[hsl(var(--text-title))]">
                  {SCREENING_TYPE_LABELS[s.screening_type] ?? s.screening_type ?? "Screening"}
                </span>
                {s.overall_impression && (
                  <div className="flex gap-0.5">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <Star
                        key={n}
                        className={cn(
                          "h-3 w-3",
                          n <= s.overall_impression
                            ? "text-amber-500 fill-amber-500"
                            : "text-[hsl(var(--border-subtle))] fill-[hsl(var(--border-subtle))]"
                        )}
                      />
                    ))}
                  </div>
                )}
              </div>
              <div className="text-xs text-[hsl(var(--text-muted))] mt-1">
                {s.created_at ? formatDate(s.created_at) : "brak daty"}
                {s.salary_expectation && (
                  <>
                    {" · "}
                    {s.salary_expectation.toLocaleString("pl-PL")}{" "}
                    {s.salary_currency ?? "PLN"}
                    {s.salary_negotiable ? " (neg.)" : ""}
                  </>
                )}
              </div>
            </div>
            {s.counteroffer_risk && (
              <Badge
                size="sm"
                variant={
                  s.counteroffer_risk === "low"
                    ? "success"
                    : s.counteroffer_risk === "medium"
                      ? "warning"
                      : "danger"
                }
              >
                Counteroffer:{" "}
                {s.counteroffer_risk === "low"
                  ? "Niskie"
                  : s.counteroffer_risk === "medium"
                    ? "Średnie"
                    : "Wysokie"}
              </Badge>
            )}
          </div>
          {s.notes && (
            <p className="text-sm text-[hsl(var(--text-body))] mt-2 whitespace-pre-line">
              {s.notes}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

function RozmowyTab({ calls }: { calls: any[] }) {
  if (!Array.isArray(calls) || calls.length === 0) {
    return (
      <div className="py-6 text-center text-sm text-[hsl(var(--text-muted))]">
        Brak zarejestrowanych rozmów.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {calls.map((c: any) => {
        const dur = c.duration_seconds;
        const mins = dur != null ? Math.floor(dur / 60) : null;
        const secs = dur != null ? dur % 60 : null;
        const durationLabel =
          mins != null ? `${mins}:${String(secs).padStart(2, "0")}` : null;
        return (
          <div
            key={c.id}
            className="rounded-v2-m border border-[hsl(var(--border-subtle))] p-3"
          >
            <div className="flex items-center gap-2 flex-wrap">
              <PhoneCall className="h-3.5 w-3.5 text-[hsl(var(--accent))]" />
              <span className="text-sm font-medium text-[hsl(var(--text-title))]">
                {c.direction === "outbound" ? "↗ Wychodząca" : "↙ Przychodząca"}
              </span>
              {durationLabel && (
                <Badge size="sm" variant="soft">
                  {durationLabel}
                </Badge>
              )}
              <span className="ml-auto text-xs text-[hsl(var(--text-muted))]">
                {c.created_at ? formatRelativeTime(c.created_at) : ""}
              </span>
            </div>
            {c.summary && (
              <p className="text-sm text-[hsl(var(--text-body))] mt-2 whitespace-pre-line">
                {c.summary}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function NotatkiTab({
  timeline,
  noteText,
  setNoteText,
  onAdd,
  saving,
  viewers = [],
  currentUserId,
  setEditing,
}: {
  timeline: any[];
  noteText: string;
  setNoteText: (v: string) => void;
  onAdd: () => void;
  saving: boolean;
  viewers?: PresenceViewer[];
  currentUserId?: number;
  setEditing?: (field: string, active: boolean) => void;
}) {
  const items = Array.isArray(timeline) ? timeline : [];
  const notes = items.filter((t: any) => t.type === "note");

  const othersEditingNotes = viewers.filter(
    (v) => v.user_id !== currentUserId && v.editing.includes("notes"),
  );

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Textarea
          value={noteText}
          onChange={(e) => setNoteText(e.target.value)}
          onFocus={() => setEditing?.("notes", true)}
          onBlur={() => setEditing?.("notes", false)}
          placeholder="Nowa notatka…"
          rows={3}
        />
        {othersEditingNotes.length > 0 ? (
          <div className="text-xs text-[#F59E0B] flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#F59E0B] animate-pulse" />
            {othersEditingNotes.length === 1
              ? `${othersEditingNotes[0].name} edytuje notatki`
              : `${othersEditingNotes.map((v) => v.name).join(", ")} edytują notatki`}
          </div>
        ) : null}
        <div className="flex justify-end">
          <Button
            size="sm"
            variant="primary"
            onClick={onAdd}
            loading={saving}
            disabled={!noteText.trim()}
          >
            <Plus className="h-3.5 w-3.5" />
            Dodaj notatkę
          </Button>
        </div>
      </div>

      <Separator />

      {notes.length === 0 ? (
        <div className="py-6 text-center text-sm text-[hsl(var(--text-muted))]">
          Brak notatek.
        </div>
      ) : (
        <div className="space-y-2">
          {notes.map((n: any, i: number) => (
            <div
              key={n.id ?? i}
              className="rounded-v2-m bg-[hsl(var(--bg-canvas))]/40 border border-[hsl(var(--border-subtle))] p-3"
            >
              <div className="flex items-baseline gap-2 text-xs text-[hsl(var(--text-muted))]">
                <span className="font-medium text-[hsl(var(--text-title))]">
                  {n.note_type ? `Notatka — ${n.note_type}` : "Notatka"}
                </span>
                <span>·</span>
                <span>{n.timestamp ? formatRelativeTime(n.timestamp) : ""}</span>
              </div>
              <p className="text-sm text-[hsl(var(--text-body))] mt-1 whitespace-pre-line">
                {n.content}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Screening summary (sticky, always visible across tabs) ─────────────

const MOTIVATION_LABEL_PL: Record<string, string> = {
  money: "Pieniądze",
  growth: "Rozwój",
  project: "Projekt",
  team: "Zespół",
  work_mode: "Tryb pracy",
  stability: "Stabilność",
  technology: "Technologia",
  location: "Lokalizacja",
};

const RISK_LABEL_PL: Record<string, string> = {
  low: "Niskie",
  medium: "Średnie",
  high: "Wysokie",
};

const RISK_VARIANT: Record<string, "success" | "warning" | "danger"> = {
  low: "success",
  medium: "warning",
  high: "danger",
};

interface VerifiedSkillAgg {
  skill: string;
  level: string;
  notes?: string;
}

interface SalarySummary {
  min: number;
  max: number;
  latest: number;
  currency: string;
  negotiable: boolean;
}

interface LastScreeningMeta {
  id: number;
  created_at: string;
  screening_type?: string | null;
  overall_impression?: number | null;
}

interface AiProfile {
  screening_count: number;
  motivation_top?: string | null;
  salary_summary?: SalarySummary | null;
  readiness_avg?: number | null;
  overall_impression_avg?: number | null;
  counteroffer_risk_dominant?: string | null;
  counteroffer_risk_distribution?: Record<string, number>;
  red_flags_unique?: string[];
  verified_skills_aggregate?: VerifiedSkillAgg[];
  motivation_trend?: Array<{
    date: string;
    primary?: string | null;
    secondary?: string | null;
    type?: string | null;
  }>;
  last_screening?: LastScreeningMeta | null;
}

function pluralScreenings(n: number): string {
  if (n === 1) return "rozmowa";
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return "rozmowy";
  return "rozmów";
}

function ScreeningSummary({
  aiProfile,
  onOpenScreenings,
}: {
  aiProfile: AiProfile;
  onOpenScreenings: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const {
    screening_count,
    motivation_top,
    salary_summary,
    readiness_avg,
    overall_impression_avg,
    counteroffer_risk_dominant,
    red_flags_unique = [],
    verified_skills_aggregate = [],
    motivation_trend = [],
    last_screening,
  } = aiProfile;

  const lastRelative = last_screening?.created_at
    ? formatRelativeTime(last_screening.created_at)
    : null;
  const topSkills = verified_skills_aggregate.slice(0, 5);

  return (
    <div className="sticky top-0 z-20">
      <Card
        variant="default"
        size="md"
        className={cn(
          "!py-3 shadow-v2-md",
          "bg-[hsl(var(--bg-surface))]/95 backdrop-blur-sm"
        )}
      >
        {/* Header */}
        <div className="flex items-center gap-2 flex-wrap">
          <Sparkles className="h-4 w-4 text-[hsl(var(--accent))] shrink-0" />
          <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--accent))]">
            Podsumowanie screeningów
          </h3>
          <span className="text-xs text-[hsl(var(--text-muted))]">
            · {screening_count} {pluralScreenings(screening_count)}
          </span>
          {lastRelative && (
            <span className="text-xs text-[hsl(var(--text-muted))]">
              · ostatnia {lastRelative}
            </span>
          )}
          <button
            type="button"
            onClick={() => setExpanded((e) => !e)}
            className="ml-auto inline-flex items-center gap-1 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent))] transition-colors"
            aria-expanded={expanded}
          >
            {expanded ? "Zwiń" : "Rozwiń"}
            {expanded ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
          </button>
        </div>

        {/* Badges row */}
        <div className="flex items-center gap-2 flex-wrap mt-2.5">
          {motivation_top && (
            <Badge variant="soft" size="md">
              <Target className="h-3 w-3" />
              Motywacja: {MOTIVATION_LABEL_PL[motivation_top] ?? motivation_top}
            </Badge>
          )}
          {salary_summary && (
            <Badge variant="plum" size="md">
              <Wallet className="h-3 w-3" />
              {salary_summary.min === salary_summary.max
                ? salary_summary.latest.toLocaleString("pl-PL")
                : `${salary_summary.min.toLocaleString("pl-PL")}–${salary_summary.max.toLocaleString("pl-PL")}`}{" "}
              {salary_summary.currency}
              {salary_summary.negotiable ? " (neg.)" : ""}
            </Badge>
          )}
          {readiness_avg != null && (
            <Badge variant="soft" size="md">
              <Gauge className="h-3 w-3" />
              Gotowość: {readiness_avg}/5
            </Badge>
          )}
          {counteroffer_risk_dominant && (
            <Badge
              variant={RISK_VARIANT[counteroffer_risk_dominant] ?? "neutral"}
              size="md"
            >
              <ShieldAlert className="h-3 w-3" />
              Counteroffer:{" "}
              {RISK_LABEL_PL[counteroffer_risk_dominant] ??
                counteroffer_risk_dominant}
            </Badge>
          )}
          {overall_impression_avg != null && (
            <Badge variant="burgundy" size="md">
              <Star className="h-3 w-3" />
              Wrażenie: {overall_impression_avg}/5
            </Badge>
          )}
          {red_flags_unique.length > 0 && (
            <Badge variant="danger" size="md">
              <AlertTriangle className="h-3 w-3" />
              {red_flags_unique.length}{" "}
              {red_flags_unique.length === 1 ? "red flag" : "red flags"}
            </Badge>
          )}
        </div>

        {/* Expanded content */}
        {expanded && (
          <div className="mt-3.5 pt-3.5 border-t border-[hsl(var(--border-subtle))] space-y-3">
            {red_flags_unique.length > 0 && (
              <div>
                <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-[#6b1120] mb-1.5">
                  <AlertTriangle className="h-3 w-3" />
                  Red flags
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {red_flags_unique.map((rf, i) => (
                    <Badge key={i} variant="danger" size="sm">
                      {rf}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {topSkills.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-1.5">
                  Potwierdzone umiejętności
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {topSkills.map((sk, i) => (
                    <Badge
                      key={i}
                      variant={sk.level === "confirmed" ? "success" : "soft"}
                      size="sm"
                    >
                      {sk.skill}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {motivation_trend.length > 1 && (
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-1.5">
                  Trend motywacji
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {motivation_trend.map((m, i) => (
                    <Badge key={i} variant="outline" size="sm">
                      {MOTIVATION_LABEL_PL[m.primary ?? ""] ??
                        m.primary ??
                        "—"}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            <div className="flex justify-end pt-1">
              <Button size="sm" variant="ghost" onClick={onOpenScreenings}>
                Zobacz wszystkie screeningi →
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
