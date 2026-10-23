"use client";

/**
 * Zapytania, mutacje i stan generatora CV v3. Reguły (braki, domyślny tryb
 * i język, treść żądania) liczy `cv-generator-form.ts` — tu tylko je wołamy.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useCentralPolicy } from "@/components/cv-rules/CentralPolicyView";
import { useClientCvRule } from "@/components/v2/cv-generator/ClientCvRuleBanner";
import type { ChampionPreview } from "@/components/ChampionIntake";
import { useToast } from "@/components/Toast";
import api, { type ChampionProfile, type CvGenerateEnqueued } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { invalidateChampionDependents } from "@/lib/champion-cache";
import {
  cvAiSourcesQueryKey,
  fetchCvAiSources,
  initialAiSources,
  type CvAiSourceKey,
  type CvAiSourceToggles,
} from "@/lib/cv-ai-sources";
import { withCvGenerationRequest } from "@/lib/cv-generation-request";
import {
  extractErrorDetail,
  fileValidationError,
  ruleNeedsProjectRef,
  type RecruitmentOption,
} from "@/lib/cv-generator";

import {
  advancedNeedsAttention,
  autoProcessChoice,
  buildGeneratePayload,
  championImportPayload,
  defaultLanguageChoice,
  defaultProcessingMode,
  missingInputs,
  type CvLanguageChoice,
  type CvProcessingMode,
  type LanguagePolicy,
} from "./cv-generator-form";

export interface CvCandidateOption {
  id: number;
  name: string;
  lastname: string;
  full_name: string;
}

export interface CvSourceFile {
  id: number;
  filename: string;
  is_primary: boolean;
  uploaded_at: string | null;
}

/** Champion z pliku, który NIE zapisał się w rekrutacji — idzie tylko do tego CV. */
export interface ChampionOverride {
  profile: ChampionProfile;
  notice: string;
}

export interface UseCvGeneratorOptions {
  /** Osoba zawsze z góry — generator żyje tylko w oknie z rekrutacji / profilu. */
  prefillCandidateId: number;
  prefillCandidateName?: string;
  prefillJobId?: number | null;
  onEnqueued?: (generatedId: number) => void;
  /**
   * „Napisz od nowa” (Edytor CV 3, PR 5): uwaga rekrutera. Przed generacją
   * zapisuje się w notatkach rekrutacji (fakty z tego zdania stają się
   * źródłem), a model dostaje ją jako życzenie co do formy.
   */
  instruction?: string;
}

export interface CvGenerationResult {
  id: number;
  candidateName: string;
  jobId: number | null;
  jobTitle: string | null;
  clientName: string | null;
  stageLabel: string | null;
  attachedToStage: boolean;
}

export function useCvGenerator({
  prefillCandidateId,
  prefillCandidateName,
  prefillJobId,
  onEnqueued,
  instruction = "",
}: UseCvGeneratorOptions) {
  const toast = useToast();
  const queryClient = useQueryClient();

  // ── Osoba i proces ───────────────────────────────────────────────────────
  const candidate = useMemo(
    () => candidateFromName(prefillCandidateId, prefillCandidateName),
    [prefillCandidateId, prefillCandidateName],
  );
  const [processChoice, setProcessChoice] = useState("");
  const [sourceChoice, setSourceChoice] = useState<number | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const notedInstruction = useRef<string | null>(null);
  // Notatka zapisana przy nieudanej generacji — ponowienie jej nie dopisuje.
  const notedDraft = useRef<string | null>(null);
  const [championOverride, setChampionOverride] = useState<ChampionOverride | null>(null);
  const [championPreview, setChampionPreview] = useState<{ file: File; data: ChampionPreview } | null>(null);
  const [championBusy, setChampionBusy] = useState(false);
  const [championMessage, setChampionMessage] = useState<string | null>(null);

  // ── Treść CV ─────────────────────────────────────────────────────────────
  const [contentMode, setContentModeState] = useState<CvProcessingMode>("polished");
  const [languageChoice, setLanguageChoiceState] = useState<CvLanguageChoice>("pl");
  const [blind, setBlind] = useState(false);
  const [position, setPosition] = useState("");
  const [projectRef, setProjectRef] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [consentToken, setConsentToken] = useState<string | null>(null);
  const [result, setResult] = useState<CvGenerationResult | null>(null);
  // Ostatnia odmowa serwera (np. 422 reguły klienta) — okno pokazuje ją w toaście,
  // karta „CV do klienta” także pod przyciskiem.
  const [lastError, setLastError] = useState<string | null>(null);

  // ── Procesy i pliki osoby ────────────────────────────────────────────────
  const candidateId = candidate.id;
  const recruitmentsQuery = useQuery({
    queryKey: ["cv-gen-recruitments", candidateId, contentMode],
    queryFn: async () =>
      (await api.get<RecruitmentOption[]>(
        `/api/cv-generator/candidates/${candidateId}/recruitments`,
        { params: { content_mode: contentMode } },
      )).data,
    // Zmiana trybu obróbki nie może na chwilę „odznaczać” procesu.
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1] === candidateId ? previous : undefined,
  });
  const recruitments = useMemo(() => recruitmentsQuery.data ?? [], [recruitmentsQuery.data]);
  const recruitment = processChoice
    ? (recruitments.find((r) => String(r.stage_id) === processChoice) ?? null)
    : null;

  const sourcesQuery = useQuery({
    queryKey: ["cv-gen-sources", candidateId],
    queryFn: async () =>
      (await api.get<CvSourceFile[]>(`/api/cv-generator/candidates/${candidateId}/cv-sources`)).data,
  });
  const sources = useMemo(() => sourcesQuery.data ?? [], [sourcesQuery.data]);
  // Domyślnie plik główny (albo jedyny); rekruter może wybrać inny.
  const cvDocumentId =
    sourceChoice != null && sources.some((s) => s.id === sourceChoice)
      ? sourceChoice
      : (sources.find((s) => s.is_primary)?.id ?? sources[0]?.id ?? null);

  // Proces wybierany sam — raz na osobę (i na rekrutację, z której otwarto).
  const appliedProcessFor = useRef<string | null>(null);
  useEffect(() => {
    if (!recruitmentsQuery.isSuccess || recruitmentsQuery.isPlaceholderData) return;
    const key = `${candidateId}:${prefillJobId ?? ""}`;
    if (appliedProcessFor.current === key) return;
    appliedProcessFor.current = key;
    setProcessChoice(autoProcessChoice(recruitments, prefillJobId));
  }, [candidateId, prefillJobId, recruitments, recruitmentsQuery.isSuccess, recruitmentsQuery.isPlaceholderData]);

  // ── „Z czego powstało” (D4): przełączniki źródeł dla AI ──────────────────
  // Stan startowy = wybór bieżącej wersji CV etapu (`last_used`) albo domyślne.
  // Wybór rekrutera trzymamy per etap — zmiana procesu zaczyna od nowa.
  const aiStageId = recruitment?.stage_id ?? null;
  const aiSourcesQuery = useQuery({
    queryKey: cvAiSourcesQueryKey(aiStageId ?? 0),
    queryFn: () => fetchCvAiSources(aiStageId ?? 0),
    enabled: aiStageId != null,
    // Wczytywanie blokuje „Generuj”, awaria — nie. Ponawia tylko axios (jeden
    // właściciel ponowień, `QueryProvider.test`), więc awaria widać od razu.
    retry: false,
  });
  const [aiChoice, setAiChoice] = useState<{ stageId: number; value: CvAiSourceToggles } | null>(null);
  const aiSources: CvAiSourceToggles | null =
    aiStageId == null
      ? null
      : aiChoice?.stageId === aiStageId
        ? aiChoice.value
        : aiSourcesQuery.data
          ? initialAiSources(aiSourcesQuery.data)
          : null;
  function setAiSource(key: CvAiSourceKey, on: boolean) {
    if (aiStageId == null || !aiSources) return;
    setAiChoice({ stageId: aiStageId, value: { ...aiSources, [key]: on } });
  }

  // ── Klient, reguły, polityka centralna ───────────────────────────────────
  const clientId = recruitment?.client_id ?? null;
  const clientName = recruitment?.client_name ?? null;
  const policyQuery = useCentralPolicy(clientId, recruitment?.stage_id ?? null, !!championOverride);
  const policy = policyQuery.data;
  const managed = !!policy?.managed;
  const ruleQuery = useClientCvRule(clientId);
  const activeRule = ruleQuery.data?.is_active ? ruleQuery.data : undefined;

  const languagePolicy: LanguagePolicy = {
    forced: policy?.effective_policy?.cv_language ?? activeRule?.cv_language ?? null,
    requiresBoth: managed
      ? !!policy?.effective_policy?.requires_en_copy
      : !!activeRule?.requires_en_copy,
  };
  const capBasic = managed && policy?.default_mode === "basic";
  const hasChampion = !!recruitment?.has_champion || !!championOverride;

  // Domyślny język — raz na klienta; wymuszony język zawsze wygrywa.
  const languageDefaultFor = useRef<string | null>(null);
  const languageKey = `${clientId ?? ""}:${languagePolicy.forced ?? ""}:${languagePolicy.requiresBoth ? 1 : 0}`;
  useEffect(() => {
    if (policyQuery.isPending && clientId != null) return;
    if (languageDefaultFor.current === languageKey) return;
    languageDefaultFor.current = languageKey;
    setLanguageChoiceState(defaultLanguageChoice(languagePolicy));
    // `languagePolicy` jest liczone z tych samych wartości co klucz.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [languageKey, policyQuery.isPending, clientId]);

  // Domyślna obróbka — przy każdej zmianie kontekstu (proces / klient /
  // obecność Championa). Champion dodany w miejscu przełącza na „Pod rekrutację”.
  const modeKey = `${recruitment?.stage_id ?? ""}:${clientId ?? ""}:${hasChampion ? 1 : 0}`;
  const modeDefaultFor = useRef<string | null>(null);
  useEffect(() => {
    if (modeDefaultFor.current === modeKey) return;
    modeDefaultFor.current = modeKey;
    setContentModeState(defaultProcessingMode(hasChampion));
  }, [modeKey, hasChampion]);

  // Stanowisko domyślnie z tytułu rekrutacji; numer projektu PKO z rekrutacji.
  useEffect(() => {
    setPosition(recruitment?.job_title ?? "");
  }, [recruitment?.stage_id, recruitment?.job_title]);
  const projectRefFromJob = policy?.project_ref ?? null;
  useEffect(() => {
    if (projectRefFromJob) setProjectRef(projectRefFromJob);
  }, [projectRefFromJob]);

  const projectRefRequired =
    !!policy?.effective_policy?.require_project_ref || !!activeRule?.require_project_ref;
  const projectRefVisible = projectRefRequired || ruleNeedsProjectRef(activeRule) || !!projectRefFromJob;
  const positionRequired = !!activeRule?.require_position && !recruitment;
  const consentRequired =
    !!policy?.effective_policy?.requires_rodo_consent_block || !!activeRule?.requires_rodo_consent_block;
  const consentBlocksGeneration = !managed && !!activeRule?.requires_rodo_consent_block;

  useEffect(() => {
    if (advancedNeedsAttention({ positionRequired, position, projectRefRequired, projectRef })) {
      setAdvancedOpen(true);
    }
  }, [positionRequired, position, projectRefRequired, projectRef]);

  const missing = missingInputs({
    policyPending: clientId != null && policyQuery.isPending,
    rulePending: clientId != null && ruleQuery.isPending,
    policyError: policyQuery.isError,
    recruitment,
    recruitmentsLoading: recruitmentsQuery.isPending,
    recruitmentsError: recruitmentsQuery.isError,
    recruitmentsCount: recruitments.length,
    cvDocumentId,
    sourcesLoading: sourcesQuery.isPending,
    sourcesError: sourcesQuery.isError,
    sourcesCount: sources.length,
    noteDraft,
    championOverride: !!championOverride,
    rule: activeRule,
    position,
    projectRef,
    consentBlocksGeneration,
    consentToken,
    aiSourcesLoading: aiStageId != null && aiSourcesQuery.isPending,
  });

  // ── Wybór procesu ────────────────────────────────────────────────────────
  function chooseProcess(value: string) {
    setProcessChoice(value);
    setChampionOverride(null);
    setChampionMessage(null);
    setConsentToken(null);
  }

  // ── Champion w miejscu (proces bez Championa) ────────────────────────────
  async function readChampionFile(file: File) {
    const problem = fileValidationError(file, ".docx,.pdf");
    if (problem) {
      setChampionMessage(problem);
      return;
    }
    setChampionBusy(true);
    setChampionMessage(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await api.post<ChampionPreview>("/api/champion/preview", form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120_000,
      });
      setChampionPreview({ file, data });
    } catch (error) {
      setChampionMessage(
        `Nie udało się odczytać pliku Championa (${errorText(error, "błąd odczytu")}). Uzupełnij Championa w rekrutacji albo generuj w trybie Redakcja.`,
      );
    } finally {
      setChampionBusy(false);
    }
  }

  /** Profil po przeglądzie: zapis w rekrutacji, a gdy się nie uda — tylko to CV. */
  async function applyChampion(profile: ChampionProfile) {
    setChampionPreview(null);
    const jobId = recruitment?.job_id;
    if (!jobId) return;
    setChampionBusy(true);
    try {
      const { data } = await api.get<{ fingerprint: string }>(`/api/jobs/${jobId}/champion-profile`);
      // Tylko pola niesione przez dokument, bez notatek zespołu — generator
      // nie widzi zapisanego profilu, więc nie może go nadpisywać pustymi.
      await api.post(`/api/jobs/${jobId}/champion-profile/apply-import`, {
        profile: championImportPayload(profile),
        expected_fingerprint: data.fingerprint,
        sync_fields: [],
      });
      invalidateChampionDependents(queryClient, jobId);
      await queryClient.invalidateQueries({ queryKey: ["cv-gen-recruitments", candidateId] });
      setChampionOverride(null);
      toast.showSuccess("Zapisano Profil Championa w rekrutacji — kolejne CV do niej już go dostaną.");
    } catch (error) {
      setChampionOverride({
        profile,
        notice: `Profil Championa nie zapisał się w rekrutacji (${apiErrorMessage(error, "brak uprawnień albo awaria")}) — użyjemy go tylko do tego CV.`,
      });
    } finally {
      setChampionBusy(false);
    }
  }

  // ── Generacja ────────────────────────────────────────────────────────────
  const generateMut = useMutation({
    mutationFn: async (): Promise<CvGenerateEnqueued> => {
      if (!recruitment || cvDocumentId == null) throw new Error("Brak rekrutacji albo pliku CV");
      const note = noteDraft.trim();
      if (note && notedDraft.current !== note) {
        // Notatka zapisuje się w rekrutacji PRZED generacją — serwer czyta
        // notatki z bazy. Pole czyści się dopiero po udanej generacji: po
        // odmowie zostaje z potwierdzeniem, a ponowienie nie zapisuje jej
        // drugi raz (audyt 22.10).
        await api.post("/api/notes", {
          content: note,
          note_type: "call",
          candidate_id: candidate.id,
          job_id: recruitment.job_id,
        });
        notedDraft.current = note;
        void queryClient.invalidateQueries({ queryKey: ["cv-gen-recruitments", candidate.id] });
        void queryClient.invalidateQueries({ queryKey: cvAiSourcesQueryKey(recruitment.stage_id) });
      }
      // Uwaga raz na treść — ponowienie po błędzie generacji nie dopisuje
      // kolejnej notatki (każda byłaby źródłem dla modelu).
      const noted = instruction.trim();
      if (noted && notedInstruction.current !== noted) {
        notedInstruction.current = noted;
        await api.post("/api/notes", {
          // Lista poprawek (linia = punkt) zaczyna się od nowej linii.
          content: `Uwaga do CV:${noted.includes("\n") ? "\n" : " "}${noted}`,
          note_type: "general",
          candidate_id: candidate.id,
          job_id: recruitment.job_id,
        });
      }
      const payload = buildGeneratePayload({
        candidateId: candidate.id,
        recruitment,
        cvDocumentId,
        projectRef,
        language: languageChoice,
        blind,
        contentMode: capBasic ? "basic" : contentMode,
        position,
        championProfile: championOverride?.profile ?? null,
        consentToken,
        sources: aiSources,
        instruction,
      });
      return (await withCvGenerationRequest("/api/cv-generator/generate", payload, (key) =>
        api.post<CvGenerateEnqueued>("/api/cv-generator/generate", payload, {
          timeout: 30_000,
          headers: { "Idempotency-Key": key },
        }))).data;
    },
    onSuccess: (data) => {
      setNoteDraft("");
      notedDraft.current = null;
      void queryClient.invalidateQueries({ queryKey: ["cv-generated"] });
      setResult({
        id: data.id,
        candidateName: data.candidate_name || candidate.full_name,
        jobId: recruitment?.job_id ?? null,
        jobTitle: recruitment?.job_title ?? (position.trim() || null),
        clientName,
        stageLabel: recruitment?.stage ?? null,
        attachedToStage: !!recruitment,
      });
      onEnqueued?.(data.id);
    },
    onError: async (error: unknown) => {
      const detail = (await extractErrorDetail(error)) || apiErrorMessage(error, "Nie udało się uruchomić generacji.");
      setLastError(detail);
      toast.showError(detail);
    },
  });

  function submit() {
    if (missing.length > 0 || generateMut.isPending) return;
    setLastError(null);
    generateMut.mutate();
  }

  /** „Wygeneruj ponownie” — wraca do formularza z tymi samymi ustawieniami. */
  function backToForm() {
    setResult(null);
  }

  return {
    candidate,
    // proces
    recruitments,
    recruitmentsQuery,
    processChoice,
    chooseProcess,
    recruitment,
    // źródła
    sources,
    sourcesQuery,
    cvDocumentId,
    setSourceChoice,
    aiSourcesQuery,
    aiSources,
    setAiSource,
    noteDraft,
    setNoteDraft,
    championOverride,
    championPreview,
    closeChampionPreview: () => setChampionPreview(null),
    championBusy,
    championMessage,
    setChampionMessage,
    readChampionFile,
    applyChampion,
    // treść
    contentMode,
    setContentMode: setContentModeState,
    capBasic,
    hasChampion,
    languageChoice,
    setLanguageChoice: setLanguageChoiceState,
    languagePolicy,
    blind,
    setBlind,
    position,
    setPosition,
    positionRequired,
    projectRef,
    setProjectRef,
    projectRefFromJob,
    projectRefRequired,
    projectRefVisible,
    advancedOpen,
    setAdvancedOpen,
    // klient
    clientId,
    clientName,
    policy,
    policyQuery,
    activeRule,
    managed,
    consentRequired,
    consentBlocksGeneration,
    consentToken,
    setConsentToken,
    // generacja
    missing,
    submit,
    generating: generateMut.isPending,
    lastError,
    result,
    backToForm,
  };
}

export type CvGeneratorState = ReturnType<typeof useCvGenerator>;

/** Komunikat błędu: z odpowiedzi API, a bez niej — z samego wyjątku. */
function errorText(error: unknown, fallback: string): string {
  return apiErrorMessage(error, error instanceof Error && error.message ? error.message : fallback);
}

function candidateFromName(id: number, fullName?: string | null): CvCandidateOption {
  const name = fullName?.trim() || `#${id}`;
  const [first, ...rest] = name.split(" ");
  return { id, name: first ?? name, lastname: rest.join(" "), full_name: name };
}
