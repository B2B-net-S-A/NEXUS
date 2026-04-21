"use client";

import * as React from "react";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Calendar,
  FileText,
  Linkedin,
  Mail,
  MapPin,
  MessageSquare,
  PencilLine,
  Phone,
  PhoneCall,
  Plus,
  Sparkles,
  Star,
  User,
  UserPlus,
  X,
} from "lucide-react";
import api from "@/lib/api";
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
import { CandidatePipelinesWidget } from "@/components/CandidatePipelinesWidget";
import { RateHistoryWidget } from "@/components/RateHistoryWidget";
import { ConflictsWidget } from "@/components/ConflictsWidget";
import { FirefliesTranscriptsWidget } from "@/components/FirefliesTranscriptsWidget";

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
  const [editOpen, setEditOpen] = useState(false);
  const [screeningStage, setScreeningStage] = useState<number | null>(null);
  const [noteText, setNoteText] = useState("");
  const [noteSaving, setNoteSaving] = useState(false);

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

  const { data: timeline } = useQuery<any[]>({
    queryKey: ["candidate-timeline", id],
    queryFn: () =>
      api.get(`/api/candidates/${id}/timeline?limit=50`).then((r) => r.data),
    enabled: !!id && (activeTab === "timeline" || activeTab === "notatki"),
  });

  const { data: history = [] } = useQuery<any[]>({
    queryKey: ["candidate-history", id],
    queryFn: () => api.get(`/api/candidates/${id}/history`).then((r) => r.data),
    enabled: !!id && activeTab === "rekrutacje",
  });

  const { data: screenings = [] } = useQuery<any[]>({
    queryKey: ["candidate-screenings", id],
    queryFn: () => api.get(`/api/candidates/${id}/screenings`).then((r) => r.data),
    enabled: !!id && activeTab === "screeningi",
  });

  const { data: calls = [] } = useQuery<any[]>({
    queryKey: ["candidate-calls", id],
    queryFn: () => api.get(`/api/candidates/${id}/calls`).then((r) => r.data),
    enabled: !!id && activeTab === "rozmowy",
  });

  const { data: aiProfile } = useQuery<any>({
    queryKey: ["candidate-ai-profile", id],
    queryFn: () => api.get(`/api/candidates/${id}/ai-profile`).then((r) => r.data),
    enabled: !!id,
  });

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
                {candidate.source === "linkedin" && (
                  <Badge variant="plum" size="sm">
                    <Linkedin className="h-3 w-3" />
                    LinkedIn
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
            <Button size="sm" variant="ghost" onClick={() => setEditOpen(true)}>
              <PencilLine className="h-4 w-4" />
              Edytuj
            </Button>
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

      {/* Suggested jobs (reuse v1 widget) */}
      <SuggestedJobsWidget candidateId={Number(id)} />

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
            <TabsTrigger value="notatki">
              <MessageSquare className="h-3.5 w-3.5" />
              Notatki
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
                  <CandidatePipelinesWidget candidateId={Number(id)} />
                </div>
              </div>
            </TabsContent>
            <TabsContent value="screeningi" className="mt-0">
              <ScreeningsTab
                screenings={screenings}
                onOpenScreening={(stageId) => setScreeningStage(stageId)}
              />
            </TabsContent>
            <TabsContent value="rozmowy" className="mt-0">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <RozmowyTab calls={calls} />
                <FirefliesTranscriptsWidget candidateId={Number(id)} />
              </div>
            </TabsContent>
            <TabsContent value="notatki" className="mt-0">
              <NotatkiTab
                timeline={timeline ?? []}
                noteText={noteText}
                setNoteText={setNoteText}
                onAdd={handleAddNote}
                saving={noteSaving}
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

function ProfilTab({ candidate }: { candidate: any }) {
  const skills: any[] = candidate.skills ?? [];
  const experience: any[] = candidate.experience ?? [];

  return (
    <div className="space-y-6">
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

      {experience.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-3">
            Doświadczenie zawodowe
          </h3>
          <div className="space-y-3">
            {experience.map((exp: any, i: number) => (
              <div
                key={i}
                className="rounded-v2-m bg-[hsl(var(--bg-canvas))]/40 border border-[hsl(var(--border-subtle))] p-3"
              >
                <div className="flex items-start justify-between gap-2 flex-wrap">
                  <div className="min-w-0">
                    <div className="font-medium text-[hsl(var(--text-title))]">
                      {exp.title}
                    </div>
                    <div className="text-xs text-[hsl(var(--text-muted))]">
                      {exp.company}
                      {exp.location ? ` · ${exp.location}` : ""}
                    </div>
                  </div>
                  <div className="text-xs text-[hsl(var(--text-muted))] whitespace-nowrap">
                    {exp.start_date ? formatDate(exp.start_date) : ""} —{" "}
                    {exp.end_date ? formatDate(exp.end_date) : "obecnie"}
                  </div>
                </div>
                {exp.description && (
                  <p className="text-sm text-[hsl(var(--text-body))] mt-2 whitespace-pre-line">
                    {exp.description}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function TimelineTab({ items }: { items: any[] }) {
  if (items.length === 0) {
    return (
      <div className="py-10 text-center text-sm text-[hsl(var(--text-muted))]">
        Brak zdarzeń w timeline.
      </div>
    );
  }
  return (
    <div className="space-y-0">
      {items.map((e: any, i: number) => (
        <div key={i} className="flex gap-3 py-2.5 border-b border-[hsl(var(--border-subtle))]/50 last:border-0">
          <div className="w-7 h-7 rounded-full bg-[hsl(var(--accent-soft))] text-[hsl(var(--accent))] flex items-center justify-center shrink-0 mt-0.5">
            <MessageSquare className="h-3.5 w-3.5" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-sm font-medium text-[hsl(var(--text-title))]">
                {e.action_label ?? e.action ?? "Zdarzenie"}
              </span>
              {e.author_name && (
                <span className="text-xs text-[hsl(var(--text-muted))]">
                  {e.author_name}
                </span>
              )}
              <span className="ml-auto text-xs text-[hsl(var(--text-muted))]">
                {e.created_at ? formatRelativeTime(e.created_at) : ""}
              </span>
            </div>
            {e.content && (
              <p className="text-sm text-[hsl(var(--text-body))] mt-1 whitespace-pre-line">
                {e.content}
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function RekrutacjeTab({ history }: { history: any[] }) {
  if (history.length === 0) {
    return (
      <div className="py-10 text-center text-sm text-[hsl(var(--text-muted))]">
        Kandydat nie ma aktywnych rekrutacji.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {history.map((h: any, i: number) => (
        <Link
          key={i}
          href={`/jobs/${h.job_id}`}
          className="block rounded-v2-m border border-[hsl(var(--border-subtle))] hover:border-[hsl(var(--accent))]/40 p-3 transition-colors"
        >
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="min-w-0 flex-1">
              <div className="font-medium text-[hsl(var(--text-title))] truncate">
                {h.job_title ?? `Oferta #${h.job_id}`}
              </div>
              <div className="text-xs text-[hsl(var(--text-muted))]">
                {h.client_name ?? "—"} · {h.stage_name ?? h.stage}
              </div>
            </div>
            <Badge size="sm" variant={h.is_terminal ? "neutral" : "success"}>
              {h.is_terminal ? "Zamknięta" : "Aktywna"}
            </Badge>
          </div>
        </Link>
      ))}
    </div>
  );
}

function ScreeningsTab({
  screenings,
  onOpenScreening,
}: {
  screenings: any[];
  onOpenScreening: (stageId: number) => void;
}) {
  if (screenings.length === 0) {
    return (
      <div className="py-10 text-center text-sm text-[hsl(var(--text-muted))]">
        Kandydat nie ma jeszcze żadnych screeningów.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {screenings.map((s: any) => (
        <button
          key={s.stage_id}
          onClick={() => onOpenScreening(s.stage_id)}
          className="w-full text-left rounded-v2-m border border-[hsl(var(--border-subtle))] hover:border-[hsl(var(--accent))]/40 p-3 transition-colors"
        >
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="min-w-0">
              <div className="font-medium text-[hsl(var(--text-title))]">
                {s.job_title ?? `Oferta #${s.job_id}`}
              </div>
              <div className="text-xs text-[hsl(var(--text-muted))]">
                {s.stage_name ?? "Screening"} ·{" "}
                {s.answered_at ? formatDate(s.answered_at) : "brak daty"}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {typeof s.match_percent === "number" && (
                <Badge
                  size="sm"
                  variant={
                    s.match_percent >= 75
                      ? "success"
                      : s.match_percent >= 50
                        ? "soft"
                        : "neutral"
                  }
                >
                  {Math.round(s.match_percent)}%
                </Badge>
              )}
              <Badge
                size="sm"
                variant={
                  s.overall_fit === "fit"
                    ? "success"
                    : s.overall_fit === "miss"
                      ? "danger"
                      : "warning"
                }
              >
                {s.overall_fit === "fit"
                  ? "Pasuje"
                  : s.overall_fit === "miss"
                    ? "Nie pasuje"
                    : "Niepewnie"}
              </Badge>
            </div>
          </div>
        </button>
      ))}
    </div>
  );
}

function RozmowyTab({ calls }: { calls: any[] }) {
  if (calls.length === 0) {
    return (
      <div className="py-6 text-center text-sm text-[hsl(var(--text-muted))]">
        Brak zarejestrowanych rozmów.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {calls.map((c: any) => (
        <div
          key={c.id}
          className="rounded-v2-m border border-[hsl(var(--border-subtle))] p-3"
        >
          <div className="flex items-center gap-2">
            <PhoneCall className="h-3.5 w-3.5 text-[hsl(var(--accent))]" />
            <span className="text-sm font-medium text-[hsl(var(--text-title))]">
              {c.direction === "outbound" ? "Wychodząca" : "Przychodząca"}
            </span>
            <span className="ml-auto text-xs text-[hsl(var(--text-muted))]">
              {c.created_at ? formatRelativeTime(c.created_at) : ""}
            </span>
          </div>
          {c.duration_seconds != null && (
            <div className="text-xs text-[hsl(var(--text-muted))] mt-1">
              Czas: {Math.round(c.duration_seconds / 60)} min
            </div>
          )}
          {c.notes && (
            <p className="text-sm text-[hsl(var(--text-body))] mt-2 whitespace-pre-line">
              {c.notes}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

function NotatkiTab({
  timeline,
  noteText,
  setNoteText,
  onAdd,
  saving,
}: {
  timeline: any[];
  noteText: string;
  setNoteText: (v: string) => void;
  onAdd: () => void;
  saving: boolean;
}) {
  const notes = timeline.filter((t: any) => t.action === "note_added");

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Textarea
          value={noteText}
          onChange={(e) => setNoteText(e.target.value)}
          placeholder="Nowa notatka…"
          rows={3}
        />
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
              key={i}
              className="rounded-v2-m bg-[hsl(var(--bg-canvas))]/40 border border-[hsl(var(--border-subtle))] p-3"
            >
              <div className="flex items-baseline gap-2 text-xs text-[hsl(var(--text-muted))]">
                <span className="font-medium text-[hsl(var(--text-title))]">
                  {n.author_name ?? "System"}
                </span>
                <span>·</span>
                <span>{n.created_at ? formatRelativeTime(n.created_at) : ""}</span>
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
