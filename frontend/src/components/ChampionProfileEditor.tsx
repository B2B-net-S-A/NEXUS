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
  Loader2,
  Plus,
  Save,
  Sparkles,
  Trash2,
  AlertTriangle,
  CheckCircle2,
} from "lucide-react";
import {
  championApi,
  EMPTY_CHAMPION_PROFILE,
  type ChampionProfile,
  type ScreeningQuestion,
} from "@/lib/api";
import { cn } from "@/lib/utils";

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
}

function genId(): string {
  return `q${Date.now().toString(36).slice(-6)}`;
}

export function ChampionProfileEditor({
  jobId,
  canEdit = true,
}: ChampionProfileEditorProps) {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["champion-profile", jobId],
    queryFn: () => championApi.get(jobId).then((r) => r.data),
  });

  const [draft, setDraft] = useState<ChampionProfile>(EMPTY_CHAMPION_PROFILE);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saved" | "error">("idle");

  useEffect(() => {
    if (data) {
      const loaded = data.champion_profile as Partial<ChampionProfile>;
      setDraft({ ...EMPTY_CHAMPION_PROFILE, ...loaded });
    }
  }, [data]);

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
        <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
      </div>
    );

  if (error)
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Nie udało się pobrać profilu Championa.
      </div>
    );

  const disabled = !canEdit;

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100 flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-purple-500" />
            Profil Championa
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Delivery Lead opisuje idealnego kandydata. Rekruterzy będą odpowiadać
            na pytania screeningowe przed wysłaniem CV do klienta.
          </p>
        </div>
        {canEdit && (
          <button
            type="button"
            onClick={() => mutation.mutate(draft)}
            disabled={mutation.isPending}
            className="inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-lg text-sm font-medium shadow-sm disabled:opacity-60"
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
              className="text-xs inline-flex items-center gap-1 text-blue-600 hover:text-blue-800"
            >
              <Plus className="w-3.5 h-3.5" />
              Dodaj pytanie
            </button>
          )
        }
      >
        {draft.screening_questions.length === 0 && (
          <div className="rounded border border-dashed border-gray-200 dark:border-gray-700 p-4 text-xs text-gray-400 text-center">
            Brak pytań. Dodaj przynajmniej 1 — rekruter będzie musiał odpowiedzieć
            przed wysłaniem CV.
          </div>
        )}
        <div className="space-y-3">
          {draft.screening_questions.map((q, i) => (
            <div
              key={q.id || i}
              className="rounded-lg border border-gray-200 dark:border-gray-700 p-3 space-y-2 bg-gray-50 dark:bg-gray-900/30"
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
                    className="p-1 text-red-500 hover:text-red-700 mt-1"
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
                      ? "bg-blue-600 border-blue-600 text-white"
                      : "bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50"
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
        <div className="text-xs text-gray-500 inline-flex items-center gap-1.5">
          <AlertTriangle className="w-4 h-4" />
          Podgląd — edycja wymaga roli Delivery Lead lub Admin.
        </div>
      )}
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────────

const inputClass =
  "w-full px-2 py-1 text-xs border border-gray-200 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60";
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
    <section className="rounded-xl border border-gray-200 dark:border-gray-700 p-4 bg-white dark:bg-gray-800">
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
      <span className="block text-[10px] uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
        {label}
      </span>
      {children}
    </label>
  );
}
