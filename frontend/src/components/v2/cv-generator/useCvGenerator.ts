"use client";

/**
 * Zapytania, mutacje i stan generatora CV v3. Reguły (braki, domyślny tryb
 * i język, treść żądania) liczy `cv-generator-form.ts` — tu tylko je wołamy.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useCentralPolicy } from "@/components/cv-rules/CentralPolicyView";
import { useClientCvRule } from "@/components/v2/cv-generator/ClientCvRuleBanner";
import type { ChampionPreview, ChampionValidation } from "@/components/ChampionIntake";
import { useToast } from "@/components/Toast";
import api, {
  cvGeneratorApi,
  type ChampionProfile,
  type CvGenerateEnqueued,
  type CvIdentifyMatch,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { invalidateChampionDependents } from "@/lib/champion-cache";
import { withCvGenerationRequest } from "@/lib/cv-generation-request";
import {
  CANDIDATE_SEARCH_MAX_LENGTH,
  CHAMPION_ACCEPT,
  CV_ACCEPT,
  candidateSearchMessage,
  extractErrorDetail,
  fileValidationError,
  ruleNeedsProjectRef,
  type RecruitmentOption,
} from "@/lib/cv-generator";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";
import { useDebouncedValue } from "@/lib/use-debounced-value";

import {
  OTHER_CLIENT_CHOICE,
  advancedNeedsAttention,
  autoProcessChoice,
  buildGeneratePayload,
  buildUploadFormData,
  championImportPayload,
  defaultLanguageChoice,
  defaultProcessingMode,
  missingInputs,
  type CvClientRef,
  type CvLanguageChoice,
  type CvProcessingMode,
  type LanguagePolicy,
} from "./cv-generator-form";

export interface CvCandidateOption {
  id: number;
  name: string;
  lastname: string;
  full_name: string;
  position?: string | null;
  email?: string | null;
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
  prefillCandidateId?: number;
  prefillCandidateName?: string;
  prefillJobId?: number | null;
  onEnqueued?: (generatedId: number) => void;
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
}: UseCvGeneratorOptions) {
  const toast = useToast();
  const queryClient = useQueryClient();

  // ── Ścieżka: osoba z bazy albo plik z dysku ──────────────────────────────
  const [flow, setFlow] = useState<"person" | "upload">("person");
  const [candidate, setCandidate] = useState<CvCandidateOption | null>(() =>
    prefillCandidateId != null
      ? candidateFromName(prefillCandidateId, prefillCandidateName)
      : null,
  );
  const [candidateQuery, setCandidateQuery] = useState("");
  const [processChoice, setProcessChoice] = useState("");
  const [otherClient, setOtherClient] = useState<CvClientRef | null>(null);
  const [sourceChoice, setSourceChoice] = useState<number | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [championOverride, setChampionOverride] = useState<ChampionOverride | null>(null);
  const [championPreview, setChampionPreview] = useState<{ file: File; data: ChampionPreview } | null>(null);
  const [championBusy, setChampionBusy] = useState(false);
  const [championMessage, setChampionMessage] = useState<string | null>(null);

  // ── Osoba spoza bazy ─────────────────────────────────────────────────────
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [identifyMatches, setIdentifyMatches] = useState<CvIdentifyMatch[] | null>(null);
  const [identifyError, setIdentifyError] = useState<string | null>(null);
  const [uploadDecision, setUploadDecision] = useState<"pending" | "without-adding">("pending");
  const [uploadClient, setUploadClient] = useState<CvClientRef | null>(null);
  const [uploadChampionFile, setUploadChampionFile] = useState<File | null>(null);
  const [uploadChampionProfile, setUploadChampionProfile] = useState<ChampionProfile | null>(null);
  const [uploadChampionValidation, setUploadChampionValidation] = useState<ChampionValidation>();
  const [uploadChampionError, setUploadChampionError] = useState<string | null>(null);
  const [uploadChampionNotice, setUploadChampionNotice] = useState<string | null>(null);
  const [uploadNotes, setUploadNotes] = useState("");

  // ── Treść CV ─────────────────────────────────────────────────────────────
  const [contentMode, setContentModeState] = useState<CvProcessingMode>("polished");
  const [languageChoice, setLanguageChoiceState] = useState<CvLanguageChoice>("pl");
  const [blind, setBlind] = useState(false);
  const [position, setPosition] = useState("");
  const [projectRef, setProjectRef] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [consentToken, setConsentToken] = useState<string | null>(null);
  const [result, setResult] = useState<CvGenerationResult | null>(null);

  // ── Wyszukiwanie osoby ───────────────────────────────────────────────────
  const debouncedQuery = useDebouncedValue(candidateQuery, 300);
  const candidatesQuery = useQuery({
    queryKey: ["cv-gen-candidates", debouncedQuery],
    queryFn: async () =>
      (await api.get<CvCandidateOption[]>("/api/cv-generator/candidates", {
        params: { q: debouncedQuery, limit: 20 },
      })).data,
    enabled:
      flow === "person" &&
      !candidate &&
      debouncedQuery.trim().length > 0 &&
      debouncedQuery.trim().length <= CANDIDATE_SEARCH_MAX_LENGTH,
    staleTime: 30_000,
  });
  const candidateSearchError = candidateSearchMessage(candidateQuery, candidatesQuery.error);

  // ── Procesy i pliki osoby ────────────────────────────────────────────────
  const candidateId = flow === "person" ? (candidate?.id ?? null) : null;
  const recruitmentsQuery = useQuery({
    queryKey: ["cv-gen-recruitments", candidateId, contentMode],
    queryFn: async () =>
      (await api.get<RecruitmentOption[]>(
        `/api/cv-generator/candidates/${candidateId}/recruitments`,
        { params: { content_mode: contentMode } },
      )).data,
    enabled: candidateId != null,
    // Zmiana trybu obróbki nie może na chwilę „odznaczać” procesu.
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1] === candidateId ? previous : undefined,
  });
  const recruitments = useMemo(() => recruitmentsQuery.data ?? [], [recruitmentsQuery.data]);
  const recruitment =
    processChoice && processChoice !== OTHER_CLIENT_CHOICE
      ? (recruitments.find((r) => String(r.stage_id) === processChoice) ?? null)
      : null;

  const sourcesQuery = useQuery({
    queryKey: ["cv-gen-sources", candidateId],
    queryFn: async () =>
      (await api.get<CvSourceFile[]>(`/api/cv-generator/candidates/${candidateId}/cv-sources`)).data,
    enabled: candidateId != null,
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
    if (candidateId == null || !recruitmentsQuery.isSuccess || recruitmentsQuery.isPlaceholderData) return;
    const key = `${candidateId}:${prefillJobId ?? ""}`;
    if (appliedProcessFor.current === key) return;
    appliedProcessFor.current = key;
    setProcessChoice(autoProcessChoice(recruitments, prefillJobId));
  }, [candidateId, prefillJobId, recruitments, recruitmentsQuery.isSuccess, recruitmentsQuery.isPlaceholderData]);

  // ── Klient, reguły, polityka centralna ───────────────────────────────────
  const clientId =
    flow === "upload"
      ? (uploadClient?.id ?? null)
      : recruitment
        ? (recruitment.client_id ?? null)
        : processChoice === OTHER_CLIENT_CHOICE
          ? (otherClient?.id ?? null)
          : null;
  const clientName =
    flow === "upload"
      ? (uploadClient?.name ?? null)
      : recruitment
        ? (recruitment.client_name ?? null)
        : (otherClient?.name ?? null);
  const uploadedChampion = flow === "upload" ? !!uploadChampionFile : !!championOverride;
  const policyQuery = useCentralPolicy(clientId, recruitment?.stage_id ?? null, uploadedChampion);
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
  const hasChampion =
    flow === "upload" ? !!uploadChampionFile : !!recruitment?.has_champion || !!championOverride;

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
  const modeKey = `${flow}:${recruitment?.stage_id ?? ""}:${clientId ?? ""}:${hasChampion ? 1 : 0}`;
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
    flow,
    policyPending: clientId != null && policyQuery.isPending,
    policyError: policyQuery.isError,
    candidateId,
    processChoice,
    recruitment,
    recruitmentsLoading: candidateId != null && recruitmentsQuery.isPending,
    otherClient,
    cvDocumentId,
    sourcesLoading: candidateId != null && sourcesQuery.isPending,
    sourcesCount: sources.length,
    noteDraft,
    championOverride: !!championOverride,
    uploadFile,
    uploadDecisionPending: uploadDecision === "pending",
    uploadClient,
    uploadChampion: !!uploadChampionFile,
    uploadNotes,
    rule: activeRule,
    position,
    projectRef,
    consentBlocksGeneration,
    consentToken,
  });

  // ── Wybór osoby (także z pliku) ──────────────────────────────────────────
  function chooseCandidate(next: CvCandidateOption | null) {
    setCandidate(next);
    setCandidateQuery("");
    setProcessChoice("");
    setOtherClient(null);
    setSourceChoice(null);
    setNoteDraft("");
    setChampionOverride(null);
    setChampionMessage(null);
    setConsentToken(null);
    appliedProcessFor.current = null;
  }

  function chooseProcess(value: string) {
    setProcessChoice(value);
    setChampionOverride(null);
    setChampionMessage(null);
    setConsentToken(null);
  }

  function startUpload() {
    setFlow("upload");
    setUploadDecision("pending");
  }

  function backToSearch() {
    setFlow("person");
    setUploadFile(null);
    setIdentifyMatches(null);
    setIdentifyError(null);
    setUploadDecision("pending");
  }

  // ── Plik osoby spoza bazy ────────────────────────────────────────────────
  const identifyMut = useMutation({
    mutationFn: async (file: File) => (await cvGeneratorApi.identifyUpload(file)).data,
    onSuccess: (data) => setIdentifyMatches(data.matches ?? []),
    onError: (error) =>
      setIdentifyError(apiErrorMessage(error, "Nie udało się sprawdzić, czy ta osoba jest w bazie.")),
  });

  function pickUploadFile(file: File | null) {
    setUploadError(null);
    setIdentifyMatches(null);
    setIdentifyError(null);
    setUploadDecision("pending");
    setConsentToken(null);
    if (!file) {
      setUploadFile(null);
      return;
    }
    const problem = fileValidationError(file, CV_ACCEPT);
    if (problem) {
      setUploadError(problem);
      return;
    }
    setUploadFile(file);
    identifyMut.mutate(file);
  }

  function pickMatchedCandidate(match: CvIdentifyMatch) {
    setFlow("person");
    setUploadFile(null);
    setIdentifyMatches(null);
    setUploadDecision("pending");
    chooseCandidate(candidateFromName(match.candidate_id, match.full_name));
    toast.showSuccess(
      `Wybrano ${match.full_name} z bazy — CV powstanie z plików na profilu. Nowszy plik dodaj na profilu kandydata.`,
    );
  }

  const addToBaseMut = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return (await api.post<{ candidate: { id: number; name: string; lastname: string } }>(
        "/api/candidates/from-cv",
        fd,
        { headers: { "Content-Type": "multipart/form-data" }, timeout: SLOW_ENDPOINT_TIMEOUT_MS },
      )).data;
    },
    onSuccess: (data) => {
      const full = `${data.candidate.name} ${data.candidate.lastname}`.trim();
      void queryClient.invalidateQueries({ queryKey: ["candidates"] });
      setFlow("person");
      setUploadFile(null);
      setIdentifyMatches(null);
      chooseCandidate(candidateFromName(data.candidate.id, full));
      toast.showSuccess(`Dodano ${full} do bazy kandydatów. Wybierz proces albo klienta.`);
    },
    onError: (error: unknown) => {
      const detail = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
      const matches = (detail?.data?.detail as { matches?: Array<{ candidate_id: number; name?: string | null; lastname?: string | null; match_reasons?: string[] }> } | undefined)?.matches;
      if (detail?.status === 409 && Array.isArray(matches)) {
        setIdentifyMatches(matches.map((m) => ({
          candidate_id: m.candidate_id,
          full_name: [m.name, m.lastname].filter(Boolean).join(" ") || `#${m.candidate_id}`,
          match_reasons: m.match_reasons ?? [],
        })));
        return;
      }
      setIdentifyError(apiErrorMessage(error, "Nie udało się dodać osoby do bazy."));
    },
  });

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
    if (!jobId) {
      setChampionOverride({ profile, notice: "Bez procesu Championa nie ma gdzie zapisać — użyjemy go tylko do tego CV." });
      return;
    }
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

  // ── Champion w uploadzie: plik przypięty PRZED podglądem AI ──────────────
  // Podgląd (`/api/champion/preview`) to pomoc w przejrzeniu pól, nigdy
  // bramka: generacja czyta DOCX sama, deterministycznie.
  async function pickUploadChampion(file: File | null) {
    if (!file) {
      setUploadChampionFile(null);
      setUploadChampionProfile(null);
      setUploadChampionValidation(undefined);
      setUploadChampionNotice(null);
      setUploadChampionError(null);
      return;
    }
    const problem = fileValidationError(file, CHAMPION_ACCEPT);
    if (problem) {
      setUploadChampionError(problem);
      return;
    }
    setUploadChampionError(null);
    setUploadChampionNotice(null);
    setUploadChampionFile(file);
    setUploadChampionProfile(null);
    setUploadChampionValidation(undefined);
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await api.post<ChampionPreview>("/api/champion/preview", form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120_000,
      });
      setChampionPreview({ file, data });
    } catch (error) {
      setUploadChampionNotice(
        `Podgląd AI profilu nie powiódł się (${errorText(error, "błąd odczytu")}). Plik został przypięty — generator odczyta sekcje MUST-HAVE / NICE-TO-HAVE bezpośrednio z dokumentu.`,
      );
    }
  }

  function applyUploadChampion(profile: ChampionProfile, validation?: ChampionValidation) {
    const file = championPreview?.file ?? null;
    setChampionPreview(null);
    setUploadChampionProfile(profile);
    if (file) setUploadChampionFile(file);
    setUploadChampionValidation(validation);
  }

  // ── Generacja ────────────────────────────────────────────────────────────
  const generateMut = useMutation({
    mutationFn: async (): Promise<CvGenerateEnqueued> => {
      if (flow === "upload") {
        if (!uploadFile || !uploadClient) throw new Error("Brak pliku albo klienta");
        const fd = buildUploadFormData({
          file: uploadFile,
          client: uploadClient,
          projectRef,
          language: languageChoice,
          blind,
          contentMode: capBasic ? "basic" : contentMode,
          position,
          notes: uploadNotes,
          championFile: uploadChampionFile,
          championProfile: uploadChampionProfile,
          consentToken,
        });
        return (await withCvGenerationRequest("/api/cv-generator/generate-upload", fd, (key) =>
          api.post<CvGenerateEnqueued>("/api/cv-generator/generate-upload", fd, {
            headers: { "Content-Type": "multipart/form-data", "Idempotency-Key": key },
            timeout: 60_000,
          }))).data;
      }
      if (!candidate || cvDocumentId == null) throw new Error("Brak kandydata albo pliku CV");
      if (recruitment && noteDraft.trim()) {
        // Z procesem notatka zapisuje się w rekrutacji PRZED generacją — serwer
        // czyta notatki z bazy. Bez procesu idzie w żądaniu tylko do tego CV.
        await api.post("/api/notes", {
          content: noteDraft.trim(),
          note_type: "call",
          candidate_id: candidate.id,
          job_id: recruitment?.job_id ?? null,
        });
        setNoteDraft("");
        void queryClient.invalidateQueries({ queryKey: ["cv-gen-recruitments", candidate.id] });
      }
      const payload = buildGeneratePayload({
        candidateId: candidate.id,
        recruitment,
        otherClient,
        cvDocumentId,
        projectRef,
        language: languageChoice,
        blind,
        contentMode: capBasic ? "basic" : contentMode,
        position,
        championProfile: championOverride?.profile ?? null,
        consentToken,
        notes: recruitment ? undefined : noteDraft,
      });
      return (await withCvGenerationRequest("/api/cv-generator/generate", payload, (key) =>
        api.post<CvGenerateEnqueued>("/api/cv-generator/generate", payload, {
          timeout: 30_000,
          headers: { "Idempotency-Key": key },
        }))).data;
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["cv-generated"] });
      void queryClient.invalidateQueries({ queryKey: ["cv-my-list"] });
      setResult({
        id: data.id,
        candidateName: data.candidate_name || candidate?.full_name || "",
        jobId: recruitment?.job_id ?? null,
        jobTitle: flow === "person" ? (recruitment?.job_title ?? (position.trim() || null)) : (position.trim() || null),
        clientName,
        stageLabel: recruitment?.stage ?? null,
        attachedToStage: flow === "person" && !!recruitment,
      });
      onEnqueued?.(data.id);
    },
    onError: async (error: unknown) => {
      const detail = await extractErrorDetail(error);
      toast.showError(detail || "Nie udało się uruchomić generacji.");
    },
  });

  function submit() {
    if (missing.length > 0 || generateMut.isPending) return;
    generateMut.mutate();
  }

  /** „Wygeneruj ponownie” — wraca do formularza z tymi samymi ustawieniami. */
  function backToForm() {
    setResult(null);
  }

  return {
    flow,
    // osoba
    candidate,
    candidateQuery,
    setCandidateQuery,
    candidatesQuery,
    candidateSearchError,
    chooseCandidate,
    startUpload,
    backToSearch,
    // proces
    recruitments,
    recruitmentsQuery,
    processChoice,
    chooseProcess,
    recruitment,
    otherClient,
    setOtherClient,
    // źródła
    sources,
    sourcesQuery,
    cvDocumentId,
    setSourceChoice,
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
    // upload
    uploadFile,
    uploadError,
    setUploadError,
    pickUploadFile,
    identifyPending: identifyMut.isPending,
    identifyMatches,
    identifyError,
    pickMatchedCandidate,
    addToBase: () => uploadFile && addToBaseMut.mutate(uploadFile),
    addToBasePending: addToBaseMut.isPending,
    uploadDecision,
    generateWithoutAdding: () => setUploadDecision("without-adding"),
    uploadClient,
    setUploadClient,
    uploadChampionFile,
    uploadChampionValidation,
    uploadChampionError,
    setUploadChampionError,
    uploadChampionNotice,
    pickUploadChampion,
    applyUploadChampion,
    uploadNotes,
    setUploadNotes,
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
