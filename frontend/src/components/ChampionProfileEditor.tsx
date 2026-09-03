"use client";

/**
 * Profil Championa editor.
 *
 * Used by Delivery Leads / admins on /jobs/[id] to capture the "idealny
 * kandydat" briefing before recruiters start shortlisting. Mirrors the internal
 * Word template, restructured 09.2026 into six sections: podstawowe
 * informacje, co wpisać (search), stack technologiczny, o projekcie, pytania
 * screeningowe, o kliencie. Fakty o kliencie i dokumenty żyją w karcie
 * klienta (`ClientPlaybookCard`, 09.2026) — sekcja 6 pokazuje ją do odczytu,
 * a edytuje tylko to, co jest per rekrutacja.
 *
 * Formularz jest krótszy niż poprzedni celowo — Delivery Leadowie opisywali 80%
 * starego profilu jako szum. Skrócenie prozy jest jednak bezpieczne dla jakości
 * dopasowań WYŁĄCZNIE dlatego, że sekcja 3 podaje wymagania wprost: wcześniej
 * scoring wyciągał je regexem z narracji, więc im mniej tekstu, tym mniej
 * znalezionych technologii. Nie skracaj sekcji 4 bez wypełnionej sekcji 3.
 *
 * Weryfikacja dwustronna, briefing DL i rekomendowane wyszukiwania NIE są
 * sekcjami — serwer stempluje je własnymi endpointami i renderują się osobno
 * nad formularzem.
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
  type StackItem,
  type ScreeningQuestion,
} from "@/lib/api";
import {
  CHAMPION_PROFILE_CHANGED_EVENT,
  type ChampionProfileChangedEventDetail,
} from "@/hooks/useNotifications";
import { useAuthStore } from "@/store/auth";
import { useClientCvRule } from "@/components/v2/cv-generator/ClientCvRuleBanner";
import { ClientPlaybookCard } from "@/components/client-playbook/ClientPlaybookCard";
import { cn } from "@/lib/utils";
import { ChampionProfileSuggestionReview } from "./ChampionProfileSuggestionReview";
import { ChampionProfileSourcesPanel } from "./ChampionProfileSourcesPanel";
import { ChampionVerificationChecklist } from "./ChampionVerificationChecklist";
import { ChampionRecommendedSearches } from "./ChampionRecommendedSearches";

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
  // Język dokumentu CV pochodzi z REGUŁY KLIENTA, nie z profilu: to jego słucha
  // generator (Nordea tylko EN, PFRON tylko PL). `is_active`, bo propozycja
  // z seeda nie obowiązuje i serwer też jej nie stosuje.
  const cvRuleQuery = useClientCvRule(clientId ?? null);
  const cvLanguage = cvRuleQuery.data?.is_active
    ? (cvRuleQuery.data.cv_language ?? null)
    : null;

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

  // Patche sekcyjne. Każdy podmienia JEDNĄ sekcję, resztę zostawia — zapis i tak
  // scala payload na zapisanym profilu po stronie serwera, więc sekcja, której
  // edytor nie tknął, nie ma jak zniknąć.
  const patchBasics = (patch: Partial<ChampionProfile["basics"]>) =>
    setDraft((d) => ({ ...d, basics: { ...d.basics, ...patch } }));
  const patchSearch = (patch: Partial<ChampionProfile["search"]>) =>
    setDraft((d) => ({ ...d, search: { ...d.search, ...patch } }));
  const patchStack = (patch: Partial<ChampionProfile["stack"]>) =>
    setDraft((d) => ({ ...d, stack: { ...d.stack, ...patch } }));
  const patchProject = (patch: Partial<ChampionProfile["project"]>) =>
    setDraft((d) => ({ ...d, project: { ...d.project, ...patch } }));
  const patchClient = (patch: Partial<ChampionProfile["client"]>) =>
    setDraft((d) => ({ ...d, client: { ...d.client, ...patch } }));

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
            className="inline-flex items-center gap-1.5 bg-primary hover:bg-primary/90 text-white px-3 py-1.5 rounded-lg text-sm font-medium shadow-xs disabled:opacity-60"
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

      {/* Two-sided verification + DL briefing. Reads server state (not the
          local draft) — updates go through dedicated endpoints with
          server-side stamps. */}
      <ChampionVerificationChecklist
        jobId={jobId}
        verification={
          (data?.champion_profile as Partial<ChampionProfile> | undefined)
            ?.verification
        }
        briefing={
          (data?.champion_profile as Partial<ChampionProfile> | undefined)
            ?.briefing
        }
        canEdit={canEdit}
      />

      {/* AI-proposed sourcing strategies — DL approves, recruiters activate
          them one-click from the "Wyszukaj manualnie" tab. */}
      <ChampionRecommendedSearches
        jobId={jobId}
        searches={
          (data?.champion_profile as Partial<ChampionProfile> | undefined)
            ?.recommended_searches
        }
        canEdit={canEdit}
      />

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

      {/* 1. Podstawowe informacje */}
      <Section title="1. Podstawowe informacje">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Labeled label="Nazwa roli">
            <input
              type="text"
              disabled={disabled}
              value={draft.basics.role_name ?? ""}
              onChange={(e) => patchBasics({ role_name: e.target.value })}
              placeholder="np. Senior Java Developer"
              className={inputClass}
            />
          </Labeled>
          <Labeled label="Min. lat doświadczenia">
            <input
              type="number"
              min={0}
              max={60}
              disabled={disabled}
              value={draft.basics.seniority_min_years ?? ""}
              onChange={(e) =>
                patchBasics({
                  seniority_min_years:
                    e.target.value === "" ? null : Number(e.target.value),
                })
              }
              className={inputClass}
            />
          </Labeled>
          {/* Ta stawka nie jest opisem — filtr odrzuca po niej kandydatów
              powyżej progu, bez marginesu. Podpis mówi o tym wprost, bo pole
              wyglądające jak notatka, a działające jak filtr, jest pułapką. */}
          <Labeled label="Stawka kandydata (PLN/h) — twardy sufit">
            <input
              type="number"
              min={0}
              step="0.5"
              disabled={disabled}
              value={draft.basics.rate_value ?? ""}
              onChange={(e) =>
                patchBasics({
                  rate_value: e.target.value === "" ? null : Number(e.target.value),
                })
              }
              placeholder="np. 122.50"
              className={inputClass}
            />
          </Labeled>
          <Labeled label="Tryb pracy">
            <input
              type="text"
              disabled={disabled}
              value={draft.basics.work_mode ?? ""}
              onChange={(e) => patchBasics({ work_mode: e.target.value })}
              placeholder="stacjonarnie / hybrydowo / zdalnie"
              className={inputClass}
            />
          </Labeled>
          <Labeled label="Dni stacjonarne / tydzień">
            <input
              type="number"
              min={0}
              max={7}
              disabled={disabled}
              value={draft.basics.onsite_days_per_week ?? ""}
              onChange={(e) =>
                patchBasics({
                  onsite_days_per_week:
                    e.target.value === "" ? null : Number(e.target.value),
                })
              }
              className={inputClass}
            />
          </Labeled>
          <Labeled label="Lokalizacja biura">
            <input
              type="text"
              disabled={disabled}
              value={draft.basics.candidate_location_pref ?? ""}
              onChange={(e) =>
                patchBasics({ candidate_location_pref: e.target.value })
              }
              placeholder="np. Warszawa, Al. Jerozolimskie / PL remote"
              className={inputClass}
            />
          </Labeled>
          <Labeled label="Język pracy (od kandydata)">
            <input
              type="text"
              disabled={disabled}
              value={draft.basics.language ?? ""}
              onChange={(e) => patchBasics({ language: e.target.value })}
              placeholder="np. PL, EN B2+"
              className={inputClass}
            />
          </Labeled>
          <Labeled label="Start">
            <input
              type="text"
              disabled={disabled}
              value={draft.basics.start_date ?? ""}
              onChange={(e) => patchBasics({ start_date: e.target.value })}
              placeholder="np. ASAP / 01.10.2026"
              className={inputClass}
            />
          </Labeled>
          <Labeled label="Deadline na kandydatów">
            <input
              type="text"
              disabled={disabled}
              value={draft.basics.deadline ?? ""}
              onChange={(e) => patchBasics({ deadline: e.target.value })}
              placeholder="np. 12.09.2026"
              className={inputClass}
            />
          </Labeled>
          {/* Język CV — TYLKO DO ODCZYTU, z reguł CV klienta.
              To jedyna wartość, której słucha generator; edytowalne pole obok
              niej byłoby drugim źródłem prawdy, które przy pierwszej zmianie
              zaczęłoby kłamać. Pusto = klient nie stawia wymogu. */}
          <Labeled label="Język CV (z reguł klienta)">
            <div
              className={cn(inputClass, "flex items-center bg-muted/60")}
              data-testid="champion-cv-language"
            >
              {cvLanguage ? (
                <span className="uppercase">{cvLanguage}</span>
              ) : (
                <span className="text-muted-foreground">
                  {clientId ? "klient nie wymusza" : "wybierz klienta"}
                </span>
              )}
            </div>
          </Labeled>
          <Labeled label="Długość kontraktu">
            <input
              type="text"
              disabled={disabled}
              value={draft.basics.contract_length ?? ""}
              onChange={(e) => patchBasics({ contract_length: e.target.value })}
              placeholder="np. 3-5 mies. z przedłużeniem"
              className={inputClass}
            />
          </Labeled>
        </div>
      </Section>

      {/* 2. Co wpisać (search) */}
      <Section title="2. Co wpisać (search)">
        <div className="space-y-3">
          <Labeled label="Frazy do wyszukiwarki — dokładnie tak, jak je wpisujesz">
            <textarea
              disabled={disabled}
              value={draft.search.keywords}
              onChange={(e) => patchSearch({ keywords: e.target.value })}
              placeholder="java, spring boot, kafka, mikroserwisy"
              rows={2}
              className={textareaClass}
              data-testid="champion-search-keywords"
            />
          </Labeled>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Labeled label="Firmy docelowe">
              <textarea
                disabled={disabled}
                value={draft.search.target_companies}
                onChange={(e) => patchSearch({ target_companies: e.target.value })}
                rows={3}
                className={textareaClass}
              />
            </Labeled>
            <Labeled label="Kogo odrzucamy od razu (jeden na linię)">
              <textarea
                disabled={disabled}
                value={(draft.search.disqualifiers || []).join("\n")}
                onChange={(e) =>
                  patchSearch({ disqualifiers: splitLines(e.target.value) })
                }
                placeholder="brak polskiego&#10;bez doświadczenia w bankowości"
                rows={3}
                className={textareaClass}
              />
            </Labeled>
          </div>
          <Labeled label="Uwagi / plan działania">
            <textarea
              disabled={disabled}
              value={draft.search.notes}
              onChange={(e) => patchSearch({ notes: e.target.value })}
              placeholder="np. nie zawężamy do bankowości"
              rows={2}
              className={textareaClass}
            />
          </Labeled>
        </div>
      </Section>

      {/* 3. Stack technologiczny */}
      <Section title="3. Stack technologiczny">
        <p className="text-[11px] text-muted-foreground mb-3">
          Zapis przenosi te technologie do wymagań rekrutacji — to z nich liczy
          się dopasowanie kandydatów. Oddzielaj przecinkiem lub nową linią.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <StackField
            label="MUST-HAVE"
            testId="champion-stack-must"
            value={draft.stack.must}
            disabled={disabled}
            onChange={(items) => patchStack({ must: items })}
          />
          <StackField
            label="NICE-TO-HAVE"
            testId="champion-stack-nice"
            value={draft.stack.nice}
            disabled={disabled}
            onChange={(items) => patchStack({ nice: items })}
          />
        </div>
        <div className="mt-3">
          <Labeled label="Niuanse wersji / zakresu">
            <input
              type="text"
              disabled={disabled}
              value={draft.stack.notes}
              onChange={(e) => patchStack({ notes: e.target.value })}
              placeholder="np. Java 17+, Java 8 nie interesuje"
              className={inputClass}
            />
          </Labeled>
        </div>
      </Section>

      {/* 4. O projekcie */}
      <Section title="4. O projekcie">
        <div className="space-y-3">
          <Labeled label="Czym jest projekt — maksymalnie 2 zdania">
            <textarea
              disabled={disabled}
              value={draft.project.about}
              onChange={(e) => patchProject({ about: e.target.value })}
              placeholder="Cel i charakter projektu. Dwa zdania wystarczą."
              rows={2}
              className={textareaClass}
              data-testid="champion-project-about"
            />
          </Labeled>
          <p className="text-[11px] text-muted-foreground -mt-1">
            {countSentences(draft.project.about)} zdania/zdań
            {countSentences(draft.project.about) > 2 && (
              <span className="text-amber-600 dark:text-amber-400">
                {" "}
                — dłużej niż zakłada szablon, skróć do tego, co naprawdę zmienia
                decyzję kandydata
              </span>
            )}
          </p>
          <Labeled label="Obowiązki na stanowisku">
            <textarea
              disabled={disabled}
              value={draft.project.responsibilities}
              onChange={(e) => patchProject({ responsibilities: e.target.value })}
              rows={3}
              className={textareaClass}
            />
          </Labeled>
        </div>
      </Section>

      {/* 5. Pytania screeningowe */}
      <Section
        title="5. Pytania screeningowe"
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
      </Section>


      {/* 6. O kliencie — fakty o kliencie (SLA, limity, off-limit, dokumenty,
          „co powiedzieć kandydatowi", reguły priorytetu) żyją w KARCIE KLIENTA
          (DL: profil klienta → Zasady współpracy albo /settings/cv-rules →
          Karta klienta) i są tu tylko do odczytu. Pola
          `client.about/priority_rules/contract_type/offlimit` i `documents`
          zostają w `draft` i jadą w PUT nietknięte (serwer scala płytko) —
          usunięcie kontrolek NIE kasuje zapisanych danych. */}
      <Section title="6. O kliencie">
        <div className="space-y-3">
          {clientId ? (
            <ClientPlaybookCard
              clientId={clientId}
              variant="compact"
              editHref={`/clients/${clientId}?tab=zasady`}
            />
          ) : (
            <p
              className="text-xs text-muted-foreground"
              data-testid="champion-client-playbook-missing"
            >
              Wybierz klienta rekrutacji, żeby zobaczyć jego kartę.
            </p>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Labeled label="Co przekona kandydata do TEJ oferty">
              <textarea
                disabled={disabled}
                value={draft.client.selling_points}
                onChange={(e) => patchClient({ selling_points: e.target.value })}
                rows={3}
                className={textareaClass}
              />
            </Labeled>
            <Labeled label="Insight od naszego konsultanta u klienta">
              <textarea
                disabled={disabled}
                value={draft.client.consultant_insight}
                onChange={(e) => patchClient({ consultant_insight: e.target.value })}
                rows={3}
                className={textareaClass}
              />
            </Labeled>
            <Labeled label="Historyczne pytania klienta">
              <textarea
                disabled={disabled}
                value={draft.client.historical_questions}
                onChange={(e) => patchClient({ historical_questions: e.target.value })}
                rows={3}
                className={textareaClass}
              />
            </Labeled>
            {/* Język CV celowo NIE jest tu edytowalny — pokazuje go sekcja 1,
                z reguł klienta, bo to ich słucha generator. Wartość sparsowana
                ze starego dokumentu zostaje w danych, ale nie jest przepisywana
                ręcznie, żeby nie powstały dwie prawdy o jednym fakcie. */}
            <Labeled label="Branże">
              <input
                type="text"
                disabled={disabled}
                value={(draft.client.sectors || []).join(", ")}
                onChange={(e) =>
                  patchClient({ sectors: splitList(e.target.value) })
                }
                placeholder="banking, fintech"
                className={inputClass}
              />
            </Labeled>
          </div>
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
  "w-full px-2 py-1 text-xs border border-border dark:border-border rounded-md bg-card dark:bg-muted dark:text-foreground focus:outline-hidden focus:ring-2 focus-visible:ring-ring disabled:opacity-60";
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

/** Rozbicie na listę po nowej linii — dla pól, gdzie jedna pozycja = jedna linia. */
function splitLines(raw: string): string[] {
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

/** Rozbicie po przecinku LUB nowej linii — ludzie wpisują listy na oba sposoby. */
function splitList(raw: string): string[] {
  return raw
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

/**
 * Przybliżona liczba zdań — na potrzeby podpowiedzi „maksymalnie 2 zdania".
 *
 * Świadomie NIE blokuje zapisu: to podpowiedź redakcyjna, a nie reguła
 * poprawności. Twardy limit odrzucałby też profil zaimportowany ze starego
 * dokumentu, którego nikt w tej chwili nie redaguje.
 */
function countSentences(text: string): number {
  const trimmed = text.trim();
  if (!trimmed) return 0;
  return trimmed.split(/[.!?]+(?:\s|$)/).filter((part) => part.trim()).length;
}

/**
 * Pole listy technologii: piszesz tekstem, widzisz chipy.
 *
 * Podgląd nie jest ozdobą — to jedyny moment, w którym widać, że „Java, Spring
 * Boot" zostanie zapisane jako DWIE pozycje, a nie jedna fraza. Bez niego pole
 * strukturalne wyglądałoby dokładnie jak pole tekstowe i wracalibyśmy do prozy,
 * od której ta przebudowa odchodzi.
 */
function StackField({
  label,
  value,
  disabled,
  onChange,
  testId,
}: {
  label: string;
  value: StackItem[];
  disabled: boolean;
  onChange: (items: StackItem[]) => void;
  testId: string;
}) {
  const asText = (value || []).map((item) => item.name).join(", ");
  return (
    <div>
      <Labeled label={label}>
        <textarea
          disabled={disabled}
          value={asText}
          onChange={(e) =>
            onChange(splitList(e.target.value).map((name) => ({ name })))
          }
          placeholder="Java, Spring Boot, Kubernetes"
          rows={3}
          className={textareaClass}
          data-testid={testId}
        />
      </Labeled>
      <div className="flex flex-wrap gap-1 mt-1.5" data-testid={`${testId}-chips`}>
        {(value || []).length === 0 ? (
          <span className="text-[10px] text-muted-foreground">
            Brak pozycji — dopóki jest pusto, wymagania zgadywane są z opisu.
          </span>
        ) : (
          (value || []).map((item, i) => (
            <span
              key={`${item.name}-${i}`}
              className="text-[10px] px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-200 font-mono"
            >
              {item.name}
            </span>
          ))
        )}
      </div>
    </div>
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
