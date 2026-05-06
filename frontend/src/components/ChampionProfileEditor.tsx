"use client";

/**
 * Profil Championa editor (Phase 10).
 *
 * Used by Delivery Leads / admins on /jobs/[id] to capture the "idealny
 * kandydat" briefing before recruiters start shortlisting. Mirrors the
 * internal Word template (sections: basics, project context, screening Qs,
 * sourcing strategy).
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  Plus,
  Save,
  Sparkles,
  Trash2,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Wand2,
} from "lucide-react";
import {
  championApi,
  championSuggestionsApi,
  EMPTY_CHAMPION_PROFILE,
  type ChampionProfile,
  type ChampionProfileSuggestion,
  type ScreeningQuestion,
} from "@/lib/api";
import {
  CHAMPION_PROFILE_CHANGED_EVENT,
  type ChampionProfileChangedEventDetail,
} from "@/hooks/useNotifications";
import { useAuthStore } from "@/store/auth";
import { cn } from "@/lib/utils";
import { ChampionProfileSuggestionReview } from "./ChampionProfileSuggestionReview";
import { ChampionProfileSourcesPanel } from "./ChampionProfileSourcesPanel";

const SOURCES: Array<{
  value: ChampionProfile["sourcing"]["sources"][number];
  label: string;
}> = [
  { value: "internal_base", label: "Baza wewnętrzna" },
  { value: "linkedin", label: "LinkedIn direct" },
  { value: "ad", label: "Ogłoszenie" },
  { value: "referrals", label: "Rekomendacje" },
  { value: "other", label: "Inne" },
];

interface ChampionProfileEditorProps {
  jobId: number;
  canEdit?: boolean;
  /** Phase 15: pass-through to the Sources panel so historical-matches
   *  retrieval can default to same-client scope. */
  clientId?: number | null;
}

function genId(): string {
  return `q${Date.now().toString(36).slice(-6)}`;
}

export function ChampionProfileEditor({
  jobId,
  canEdit = true,
  clientId,
}: ChampionProfileEditorProps) {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["champion-profile", jobId],
    queryFn: () => championApi.get(jobId).then((r) => r.data),
  });

  const [draft, setDraft] = useState<ChampionProfile>(EMPTY_CHAMPION_PROFILE);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saved" | "error">("idle");
  const [remoteChange, setRemoteChange] = useState<{
    by: string;
    at: number;
  } | null>(null);
  const currentUserId = useAuthStore((s) => s.user?.id);

  // AI Intake (Phase 14)
  const [showIntake, setShowIntake] = useState(false);
  const [jdText, setJdText] = useState("");
  const [activeSuggestion, setActiveSuggestion] =
    useState<ChampionProfileSuggestion | null>(null);

  const generateMutation = useMutation({
    mutationFn: async (rawDescription: string) => {
      const res = await championSuggestionsApi.generateFromJd(jobId, rawDescription);
      return res.data;
    },
    onSuccess: (suggestion) => {
      if (suggestion.status === "rejected") {
        // LLM failure already captured server-side — surface the error but
        // still open the modal so the DL can see what went wrong.
      }
      setActiveSuggestion(suggestion);
    },
  });

  useEffect(() => {
    if (data) {
      const loaded = data.champion_profile as Partial<ChampionProfile>;
      setDraft({ ...EMPTY_CHAMPION_PROFILE, ...loaded });
    }
  }, [data]);

  // Live refresh when another user edits this job's Champion Profile.
  // The WS hook dispatches CHAMPION_PROFILE_CHANGED_EVENT on the window;
  // we invalidate the query and show a subtle banner so the Delivery
  // Lead / recruiter knows their view is no longer stale.
  useEffect(() => {
    const handler = (event: Event) => {
      const custom = event as CustomEvent<ChampionProfileChangedEventDetail>;
      const detail = custom.detail;
      if (!detail || detail.job_id !== jobId) return;
      if (
        currentUserId !== undefined &&
        detail.updated_by_user_id === currentUserId
      ) {
        return;
      }
      setRemoteChange({ by: detail.updated_by_name || "Ktoś", at: Date.now() });
      qc.invalidateQueries({ queryKey: ["champion-profile", jobId] });
    };
    window.addEventListener(CHAMPION_PROFILE_CHANGED_EVENT, handler);
    return () =>
      window.removeEventListener(CHAMPION_PROFILE_CHANGED_EVENT, handler);
  }, [jobId, currentUserId, qc]);

  useEffect(() => {
    if (!remoteChange) return;
    const t = setTimeout(() => setRemoteChange(null), 6000);
    return () => clearTimeout(t);
  }, [remoteChange]);

  const mutation = useMutation({
    mutationFn: (p: ChampionProfile) => championApi.put(jobId, p),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["champion-profile", jobId] });
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 3000);
    },
    onError: () => setSaveStatus("error"),
  });

  const updateQuestion = (i: number, patch: Partial<ScreeningQuestion>) => {
    setDraft((d) => {
      const next = [...d.screening_questions];
      next[i] = { ...next[i], ...patch };
      return { ...d, screening_questions: next };
    });
  };

  const addQuestion = () =>
    setDraft((d) => ({
      ...d,
      screening_questions: [
        ...d.screening_questions,
        { id: genId(), question: "", ideal_answer: "", deal_breaker: "" },
      ],
    }));

  const removeQuestion = (i: number) =>
    setDraft((d) => ({
      ...d,
      screening_questions: d.screening_questions.filter((_, idx) => idx !== i),
    }));

  const toggleSource = (v: ChampionProfile["sourcing"]["sources"][number]) =>
    setDraft((d) => ({
      ...d,
      sourcing: {
        ...d.sourcing,
        sources: d.sourcing.sources.includes(v)
          ? d.sourcing.sources.filter((s) => s !== v)
          : [...d.sourcing.sources, v],
      },
    }));

  if (isLoading)
    return (
      <div className="flex justify-center py-10">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );

  if (error)
    return (
      <div className="rounded-xl border border-destructive/20 bg-destructive/10 p-4 text-sm text-destructive">
        Nie udało się pobrać profilu Championa.
      </div>
    );

  const disabled = !canEdit;

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-foreground dark:text-foreground flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-purple-500" />
            Profil Championa
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Delivery Lead opisuje idealnego kandydata. Rekruterzy będą odpowiadać
            na pytania screeningowe przed wysłaniem CV do klienta.
          </p>
        </div>
        {canEdit && (
          <button
            type="button"
            onClick={() => mutation.mutate(draft)}
            disabled={mutation.isPending}
            className="inline-flex items-center gap-1.5 bg-primary hover:bg-primary/90 text-white px-3 py-1.5 rounded-lg text-sm font-medium shadow-sm disabled:opacity-60"
            data-testid="save-champion-profile"
          >
            <Save className="w-4 h-4" />
            {mutation.isPending ? "Zapisuję…" : "Zapisz"}
          </button>
        )}
      </div>

      {saveStatus === "saved" && (
        <div className="text-xs px-3 py-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 inline-flex items-center gap-1.5">
          <CheckCircle2 className="w-4 h-4" /> Zapisano
        </div>
      )}

      {remoteChange && (
        <div
          className="text-xs px-3 py-2 rounded-lg bg-primary/10 border border-primary/20 text-primary inline-flex items-center gap-1.5"
          role="status"
          data-testid="champion-profile-remote-update"
        >
          <RefreshCw className="w-4 h-4" />
          {remoteChange.by} zaktualizował profil — odświeżono
        </div>
      )}

      {/* AI Intake (Phase 14): paste JD → draft Championa */}
      {canEdit && (
        <div className="rounded-xl border border-purple-200 dark:border-purple-900 bg-purple-50/50 dark:bg-purple-950/20">
          <button
            type="button"
            onClick={() => setShowIntake((v) => !v)}
            className="w-full flex items-center justify-between px-4 py-3 text-left"
            data-testid="toggle-ai-intake"
          >
            <span className="inline-flex items-center gap-2 font-medium text-sm text-purple-900 dark:text-purple-200">
              <Wand2 className="w-4 h-4" />
              Wygeneruj Profil Championa z opisu klienta (AI)
            </span>
            {showIntake ? (
              <ChevronDown className="w-4 h-4 text-purple-600" />
            ) : (
              <ChevronRight className="w-4 h-4 text-purple-600" />
            )}
          </button>
          {showIntake && (
            <div className="px-4 pb-4 space-y-2">
              <p className="text-xs text-muted-foreground dark:text-muted-foreground">
                Wklej opis stanowiska otrzymany od klienta. AI wypełni sekcje
                Profilu Championa jako draft do Twojej akceptacji.
              </p>
              <textarea
                value={jdText}
                onChange={(e) => setJdText(e.target.value)}
                placeholder="Wklej opis od klienta (min. 50 znaków)…"
                className="w-full min-h-[140px] text-sm rounded-lg border border-border dark:border-border bg-card dark:bg-card px-3 py-2 font-mono"
                data-testid="jd-intake-textarea"
              />
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className="text-[11px] text-muted-foreground">
                  {jdText.length} znaków
                </span>
                <button
                  type="button"
                  onClick={() => generateMutation.mutate(jdText)}
                  disabled={
                    generateMutation.isPending || jdText.trim().length < 50
                  }
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium bg-purple-600 hover:bg-purple-700 text-white disabled:opacity-60"
                  data-testid="generate-champion-from-jd"
                >
                  {generateMutation.isPending ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Sparkles className="w-4 h-4" />
                  )}
                  {generateMutation.isPending
                    ? "Generuję draft…"
                    : "Generuj draft"}
                </button>
              </div>
              {generateMutation.error && (
                <div className="text-xs px-2 py-1 rounded bg-destructive/10 border border-destructive/20 text-destructive inline-flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  Nie udało się wygenerować draftu.
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {activeSuggestion && (
        <ChampionProfileSuggestionReview
          jobId={jobId}
          suggestion={activeSuggestion}
          currentProfile={draft}
          onClose={() => setActiveSuggestion(null)}
        />
      )}

      {/* 1. Podstawy */}
      <Section title="1. Podstawowe informacje">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Labeled label="Dni stacjonarne / tydzień">
            <input
              type="number"
              min={0}
              max={7}
              disabled={disabled}
              value={draft.basics.onsite_days_per_week ?? ""}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  basics: {
                    ...d.basics,
                    onsite_days_per_week: e.target.value === "" ? null : Number(e.target.value),
                  },
                }))
              }
              className={inputClass}
            />
          </Labeled>
          <Labeled label="Lokalizacja kandydata">
            <input
              type="text"
              disabled={disabled}
              value={draft.basics.candidate_location_pref ?? ""}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  basics: { ...d.basics, candidate_location_pref: e.target.value },
                }))
              }
              placeholder="np. Warszawa lub PL remote"
              className={inputClass}
            />
          </Labeled>
          <Labeled label="Język">
            <input
              type="text"
              disabled={disabled}
              value={draft.basics.language ?? ""}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  basics: { ...d.basics, language: e.target.value },
                }))
              }
              placeholder="np. PL, EN B2+"
              className={inputClass}
            />
          </Labeled>
        </div>
      </Section>

      {/* 2. Kontekst */}
      <Section title="2. Kontekst projektu">
        <div className="space-y-3">
          <Labeled label="O projekcie (cel, harmonogram, zespół)">
            <textarea
              disabled={disabled}
              value={draft.project_context.about}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  project_context: { ...d.project_context, about: e.target.value },
                }))
              }
              rows={3}
              className={textareaClass}
            />
          </Labeled>
          <Labeled label="Obowiązki na stanowisku">
            <textarea
              disabled={disabled}
              value={draft.project_context.responsibilities}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  project_context: {
                    ...d.project_context,
                    responsibilities: e.target.value,
                  },
                }))
              }
              rows={3}
              className={textareaClass}
            />
          </Labeled>
          <Labeled label="Co przekona kandydata?">
            <textarea
              disabled={disabled}
              value={draft.project_context.selling_points}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  project_context: {
                    ...d.project_context,
                    selling_points: e.target.value,
                  },
                }))
              }
              rows={3}
              className={textareaClass}
            />
          </Labeled>
        </div>
      </Section>

      {/* 3. Screening Questions */}
      <Section
        title="3. Pytania screeningowe"
        action={
          canEdit && (
            <button
              type="button"
              onClick={addQuestion}
              className="text-xs inline-flex items-center gap-1 text-primary hover:text-primary/80"
            >
              <Plus className="w-3.5 h-3.5" />
              Dodaj pytanie
            </button>
          )
        }
      >
        {draft.screening_questions.length === 0 && (
          <div className="rounded border border-dashed border-border dark:border-border p-4 text-xs text-muted-foreground text-center">
            Brak pytań. Dodaj przynajmniej 1 — rekruter będzie musiał odpowiedzieć
            przed wysłaniem CV.
          </div>
        )}
        <div className="space-y-3">
          {draft.screening_questions.map((q, i) => (
            <div
              key={q.id || i}
              className="rounded-lg border border-border dark:border-border p-3 space-y-2 bg-muted dark:bg-card/30"
              data-testid={`screening-q-${i}`}
            >
              <div className="flex items-start gap-2">
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 font-mono mt-1">
                  Q{i + 1}
                </span>
                <textarea
                  disabled={disabled}
                  value={q.question}
                  onChange={(e) => updateQuestion(i, { question: e.target.value })}
                  placeholder="Pytanie od Delivery Leada…"
                  rows={2}
                  className={textareaClass}
                />
                {canEdit && (
                  <button
                    type="button"
                    onClick={() => removeQuestion(i)}
                    className="p-1 text-destructive hover:text-destructive mt-1"
                    aria-label="Usuń pytanie"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
              <Labeled label="Idealna odpowiedź">
                <textarea
                  disabled={disabled}
                  value={q.ideal_answer}
                  onChange={(e) => updateQuestion(i, { ideal_answer: e.target.value })}
                  rows={2}
                  className={textareaClass}
                />
              </Labeled>
              <Labeled label="Deal-breaker (kiedy odpada)">
                <textarea
                  disabled={disabled}
                  value={q.deal_breaker}
                  onChange={(e) => updateQuestion(i, { deal_breaker: e.target.value })}
                  rows={2}
                  className={cn(textareaClass, "border-amber-200 focus:ring-amber-500")}
                />
              </Labeled>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
          <Labeled label="Historyczne pytania klienta">
            <textarea
              disabled={disabled}
              value={draft.historical_client_questions}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  historical_client_questions: e.target.value,
                }))
              }
              rows={3}
              className={textareaClass}
            />
          </Labeled>
          <Labeled label="Insight od konsultanta wewnętrznego">
            <textarea
              disabled={disabled}
              value={draft.internal_consultant_insight}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  internal_consultant_insight: e.target.value,
                }))
              }
              rows={3}
              className={textareaClass}
            />
          </Labeled>
        </div>
      </Section>

      {/* 4. Sourcing */}
      <Section title="4. Strategia sourcingu">
        <Labeled label="Główne źródła kandydatów">
          <div className="flex flex-wrap gap-2">
            {SOURCES.map((s) => {
              const active = draft.sourcing.sources.includes(s.value);
              return (
                <button
                  key={s.value}
                  type="button"
                  disabled={disabled}
                  onClick={() => toggleSource(s.value)}
                  className={cn(
                    "text-[11px] px-2 py-1 rounded-md border transition-colors",
                    active
                      ? "bg-primary border-primary text-white"
                      : "bg-card dark:bg-muted border-border dark:border-border text-foreground dark:text-muted-foreground hover:bg-muted"
                  )}
                >
                  {s.label}
                </button>
              );
            })}
          </div>
        </Labeled>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
          <Labeled label="Słowa kluczowe do wyszukiwania">
            <textarea
              disabled={disabled}
              value={draft.sourcing.keywords}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  sourcing: { ...d.sourcing, keywords: e.target.value },
                }))
              }
              rows={3}
              placeholder="kafka, spring boot, aws…"
              className={textareaClass}
            />
          </Labeled>
          <Labeled label="Firmy docelowe">
            <textarea
              disabled={disabled}
              value={draft.sourcing.target_companies}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  sourcing: { ...d.sourcing, target_companies: e.target.value },
                }))
              }
              rows={3}
              className={textareaClass}
            />
          </Labeled>
        </div>
        <div className="mt-3">
          <Labeled label="Uwagi / plan działania">
            <textarea
              disabled={disabled}
              value={draft.sourcing.notes}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  sourcing: { ...d.sourcing, notes: e.target.value },
                }))
              }
              rows={3}
              className={textareaClass}
            />
          </Labeled>
        </div>
      </Section>

      {!canEdit && (
        <div className="text-xs text-muted-foreground inline-flex items-center gap-1.5">
          <AlertTriangle className="w-4 h-4" />
          Podgląd — edycja wymaga roli Delivery Lead lub Admin.
        </div>
      )}

      {/* Phase 14: Fireflies / CloudTalk sources + pending AI suggestions */}
      {canEdit && (
        <div className="border-t border-border dark:border-border pt-6 mt-6">
          <ChampionProfileSourcesPanel
            jobId={jobId}
            currentProfile={draft}
            clientId={clientId}
          />
        </div>
      )}
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────────

const inputClass =
  "w-full px-2 py-1 text-xs border border-border dark:border-border rounded-md bg-card dark:bg-muted dark:text-foreground focus:outline-none focus:ring-2 focus-visible:ring-ring disabled:opacity-60";
const textareaClass = inputClass + " resize-y";

function Section({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border dark:border-border p-4 bg-card dark:bg-muted">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-[11px] uppercase tracking-wide text-purple-700 dark:text-purple-300 font-bold">
          {title}
        </h3>
        {action}
      </header>
      {children}
    </section>
  );
}

function Labeled({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-[10px] uppercase tracking-wide text-muted-foreground dark:text-muted-foreground mb-1">
        {label}
      </span>
      {children}
    </label>
  );
}
