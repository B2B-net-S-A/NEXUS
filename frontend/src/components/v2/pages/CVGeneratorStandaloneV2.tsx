"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronsUpDown,
  Download,
  Eye,
  FileCode2,
  FileText,
  Link2,
  Loader2,
  Search,
  Sparkles,
  Trash2,
  Upload,
  UserSearch,
  X,
} from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { LanguageTiles } from "@/components/v2/LanguageTiles";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import { ContentModeTiles } from "@/components/v2/cv-generator/ContentModeTiles";
import { ConsentScreenshotField } from "@/components/v2/cv/ConsentScreenshotField";
import { CvGeneratedShareModal } from "@/components/v2/modals/CvGeneratedShareModal";
import { RecruitmentCombobox } from "@/components/v2/cv-generator/RecruitmentCombobox";
import api from "@/lib/api";
import {
  ClientSinglePicker,
  type ClientRef,
} from "@/components/clients/ClientSinglePicker";
import {
  ClientCvRuleBanner,
  useClientCvRule,
} from "@/components/v2/cv-generator/ClientCvRuleBanner";
import {
  type CvContentMode,
  type RecruitmentOption,
  CHAMPION_ACCEPT,
  CV_ACCEPT,
  DEFAULT_CV_CONTENT_MODE,
  MAX_UPLOAD_MB,
  downloadBlob,
  extractErrorDetail,
  fileValidationError,
  isCertainWarning,
} from "@/lib/cv-generator";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { useLocalStorageFlag } from "@/lib/use-local-storage-flag";
import { cn } from "@/lib/utils";
import { canMutateSection } from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";

type CandidateOption = {
  id: number;
  name: string;
  lastname: string;
  full_name: string;
  position?: string | null;
  email?: string | null;
};

type Mode = "new" | "old";

type GeneratedCvItem = {
  id: number;
  candidate_id?: number | null;
  job_id?: number | null;
  client_id?: number | null;
  client_name?: string | null;
  candidate_name: string;
  position?: string | null;
  language: string;
  blind: boolean;
  mode: string;
  filename: string;
  status: "processing" | "ready" | "failed";
  error_message?: string | null;
  warnings?: string[];
  created_at?: string | null;
  created_by_name?: string | null;
  can_download: boolean;
  can_delete: boolean;
};

type EnqueuedResponse = {
  id: number;
  status: string;
  candidate_name: string;
};

function formatGeneratedDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function CVGeneratorStandaloneV2() {
  const toast = useToast();
  const currentUser = useAuthStore((state) => state.user);
  const isImpersonating = useAuthStore((state) => state.realUser !== null);
  const canWriteSourcing = canMutateSection(
    currentUser,
    "sourcing",
    isImpersonating,
  );

  // ── Mode (New vs Old) ───────────────────────────────────────────────────
  const [mode, setMode] = useState<Mode>("new");

  // ── New mode state ──────────────────────────────────────────────────────
  const [candidate, setCandidate] = useState<CandidateOption | null>(null);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [candidateQuery, setCandidateQuery] = useState("");
  const [stageId, setStageId] = useState<string>("");

  // ── Old mode state ──────────────────────────────────────────────────────
  const [cvFile, setCvFile] = useState<File | null>(null);
  const [championFile, setChampionFile] = useState<File | null>(null);
  // Durable rejection reason. A toast alone was not enough: it self-destructs
  // and the dropzone re-renders its untouched empty state, so a recruiter whose
  // champion file was rejected saw no trace of it and generated a CV with no
  // champion at all — reported as "the generator does not work with a champion".
  const [championError, setChampionError] = useState<string | null>(null);
  const [screeningNotes, setScreeningNotes] = useState("");
  // Ręczne wymagania na kafelki interaktywnego CV (upload nie ma joba).
  // Puste + brak pliku championa = link pokaże sam widok klasyczny.
  const [mustRequirements, setMustRequirements] = useState("");
  const [niceRequirements, setNiceRequirements] = useState("");

  // ── Klient + pola, których upload nie ma skąd wziąć ─────────────────────
  // W trybie „new" klienta wyprowadza SERWER z rekrutacji, a ten stan służy
  // tylko do pokazania go i pobrania reguł. W trybie upload rekruter wybiera
  // go sam — wybór jest OPCJONALNY, bo CV powstają też poza konkretnym
  // zleceniem, a wymuszony wybór zamieniłby brak wiedzy w zgadywanie.
  const [uploadClient, setUploadClient] = useState<ClientRef | null>(null);
  const [position, setPosition] = useState("");
  const [projectRef, setProjectRef] = useState("");
  // Kandydat z bazy w trybie upload (0267) — WYŁĄCZNIE po to, żeby podpowiedzieć
  // klienta z jego aktywnego procesu. Plik CV nadal wgrywa rekruter; nic
  // z bazy kandydata nie idzie do modelu tą ścieżką.
  const [uploadCandidate, setUploadCandidate] = useState<CandidateOption | null>(null);
  const [uploadCandidateOpen, setUploadCandidateOpen] = useState(false);
  const [uploadCandidateQuery, setUploadCandidateQuery] = useState("");
  // Generacja bez klienta wymaga jawnego potwierdzenia — bez klienta ŻADNA
  // reguła nie działa, a to była największa dziura: rekruter „zapominał"
  // wybrać klienta i dostawał plik z ogólną nazwą i bez blokad.
  const [outsideAssignment, setOutsideAssignment] = useState(false);

  // ── Shared options ──────────────────────────────────────────────────────
  const [language, setLanguage] = useState<"pl" | "en">("pl");

  const [blindCv, setBlindCv] = useState(false);
  const [contentMode, setContentMode] = useState<CvContentMode>(
    DEFAULT_CV_CONTENT_MODE,
  );
  // Ids enqueued in THIS session with auto-download on — downloaded once they
  // flip to „ready" (see the effect below). A ref, not state: mutating it must
  // not re-render, and it needn't survive a reload.
  const autoDownloadIds = useRef<Set<number>>(new Set());

  // Auto-download to the browser's „Pobrane" folder is now opt-in (remembered
  // per browser). Default off: the generated CV lands on the panel list below
  // instead of piling up as unlabeled files while the recruiter browses on.
  const [autoDownload, setAutoDownload] = useLocalStorageFlag("cvgen_auto_download");

  // „Wygenerowane CV" — server-side list, survives navigation/refresh.
  const [previewItem, setPreviewItem] = useState<GeneratedCvItem | null>(null);
  const [shareItem, setShareItem] = useState<GeneratedCvItem | null>(null);
  const generatedQuery = useQuery({
    queryKey: ["cv-generated"],
    queryFn: async () => {
      const res = await api.get<GeneratedCvItem[]>("/api/cv-generator/generated");
      return res.data;
    },
    staleTime: 15_000,
    // Generacja leci w tle — dopóki któreś CV jest „processing", odpytuj listę,
    // by wiersz sam przeskoczył na „ready"/„failed" bez odświeżania strony.
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.status === "processing") ? 4000 : false,
  });

  // ── New mode queries ────────────────────────────────────────────────────
  // Debounce — bez tego każdy keystroke strzela requestem do API.
  const debouncedCandidateQuery = useDebouncedValue(candidateQuery, 300);
  const candidatesQuery = useQuery({
    queryKey: ["cv-gen-candidates", debouncedCandidateQuery],
    queryFn: async () => {
      const res = await api.get<CandidateOption[]>("/api/cv-generator/candidates", {
        params: { q: debouncedCandidateQuery, limit: 20 },
      });
      return res.data;
    },
    enabled: candidateOpen && mode === "new",
    staleTime: 30_000,
  });

  const recruitmentsQuery = useQuery({
    queryKey: ["cv-gen-recruitments", candidate?.id],
    queryFn: async () => {
      if (!candidate) return [] as RecruitmentOption[];
      const res = await api.get<RecruitmentOption[]>(
        `/api/cv-generator/candidates/${candidate.id}/recruitments`,
      );
      return res.data;
    },
    enabled: !!candidate && mode === "new",
  });

  const selectedRecruitment = useMemo(() => {
    if (!stageId) return null;
    return (
      recruitmentsQuery.data?.find((r) => String(r.stage_id) === stageId) ?? null
    );
  }, [recruitmentsQuery.data, stageId]);

  // ── Upload: klient podpowiadany z aktywnego procesu kandydata ───────────
  const debouncedUploadCandidateQuery = useDebouncedValue(uploadCandidateQuery, 300);
  const uploadCandidatesQuery = useQuery({
    queryKey: ["cv-gen-candidates", debouncedUploadCandidateQuery],
    queryFn: async () => {
      const res = await api.get<CandidateOption[]>("/api/cv-generator/candidates", {
        params: { q: debouncedUploadCandidateQuery, limit: 20 },
      });
      return res.data;
    },
    enabled: uploadCandidateOpen && mode === "old",
    staleTime: 30_000,
  });
  const uploadRecruitmentsQuery = useQuery({
    queryKey: ["cv-gen-recruitments", uploadCandidate?.id],
    queryFn: async () => {
      if (!uploadCandidate) return [] as RecruitmentOption[];
      const res = await api.get<RecruitmentOption[]>(
        `/api/cv-generator/candidates/${uploadCandidate.id}/recruitments`,
      );
      return res.data;
    },
    enabled: !!uploadCandidate && mode === "old",
  });
  const uploadClientOptions = useMemo<ClientRef[]>(() => {
    const seen = new Map<number, ClientRef>();
    for (const r of uploadRecruitmentsQuery.data ?? []) {
      if (r.client_id && !seen.has(r.client_id)) {
        seen.set(r.client_id, { id: r.client_id, name: r.client_name ?? `#${r.client_id}` });
      }
    }
    return [...seen.values()];
  }, [uploadRecruitmentsQuery.data]);
  useEffect(() => {
    // Dokładnie jeden klient w procesach kandydata = wybieramy go sami. Przy
    // kilku decyduje rekruter (przyciski niżej); przy zerze nie zgadujemy.
    if (mode === "old" && uploadCandidate && uploadClientOptions.length === 1) {
      setUploadClient(uploadClientOptions[0]);
    }
  }, [mode, uploadCandidate, uploadClientOptions]);
  useEffect(() => {
    if (uploadClient) setOutsideAssignment(false);
  }, [uploadClient]);

  // Klient obowiązujący dla TEJ generacji. W trybie „new" pochodzi z wybranej
  // rekrutacji (serwer i tak liczy go sam), w uploadzie — z pickera.
  const effectiveClientId =
    mode === "new" ? (selectedRecruitment?.client_id ?? null) : (uploadClient?.id ?? null);
  const cvRuleQuery = useClientCvRule(effectiveClientId);
  const activeRule = cvRuleQuery.data?.is_active ? cvRuleQuery.data : undefined;
  const forcedLanguage = activeRule?.cv_language ?? null;
  // Zrzut zgody kandydata — wymagany u klientów z `requires_rodo_consent_block`
  // (dziś PKO BP). `activeRule`, nie surowe `cvRuleQuery.data`: propozycja
  // z seeda nie obowiązuje i serwer też jej nie stosuje.
  const [consentKey, setConsentKey] = useState<string | null>(null);
  const consentRequired = !!activeRule?.requires_rodo_consent_block;

  // Reguła klienta WYMUSZA język: front go ustawia i blokuje kafelki, backend
  // odrzuca rozjazd (422). Bez tego Nordea — jedyny klient wymagający wyłącznie
  // angielskiego — dostawałaby domyślnie polskie CV przy każdej generacji.
  useEffect(() => {
    if (forcedLanguage && forcedLanguage !== language) {
      setLanguage(forcedLanguage);
    }
  }, [forcedLanguage, language]);

  // ── Blokada trybu obróbki treści (0267) ─────────────────────────────────
  // Zablokowany tryb: kafelki wyłączone, wartość wymuszona (serwer i tak
  // nadpisuje). Domyślny tryb: zaznaczany RAZ przy zmianie klienta — potem
  // rekruter może go zmienić.
  const lockedMode = activeRule?.content_mode_locked
    ? activeRule.content_mode
    : null;
  const defaultMode = activeRule?.content_mode ?? null;
  const ruleClientId = activeRule?.client_id ?? null;
  const lastDefaultedClient = useRef<number | null>(null);
  useEffect(() => {
    if (lockedMode && lockedMode !== contentMode) setContentMode(lockedMode);
  }, [lockedMode, contentMode]);
  useEffect(() => {
    if (ruleClientId === null || lastDefaultedClient.current === ruleClientId) return;
    lastDefaultedClient.current = ruleClientId;
    if (defaultMode && !lockedMode) setContentMode(defaultMode);
  }, [ruleClientId, defaultMode, lockedMode]);

  // ── Wymagane wejścia (0267) — te same komunikaty, które zwróci 422 ───────
  const hasChampionInput =
    mode === "new"
      ? !!selectedRecruitment?.has_champion
      : !!championFile || !!mustRequirements.trim() || !!niceRequirements.trim();
  const notesChars =
    mode === "new" ? (selectedRecruitment?.notes_chars ?? 0) : screeningNotes.trim().length;
  const requirementProblems = useMemo(() => {
    if (!activeRule) return [] as string[];
    const problems: string[] = [];
    const min = activeRule.require_screening_notes_min_chars ?? 0;
    if (min > 0 && notesChars < min) {
      problems.push(
        `Ten klient wymaga notatek ze screeningu o długości co najmniej ${min} znaków — jest ${notesChars}.`,
      );
    }
    if (activeRule.require_project_ref && !projectRef.trim()) {
      problems.push("Ten klient wymaga numeru projektu — uzupełnij pole „Numer / nazwa projektu”.");
    }
    if (activeRule.require_position && mode === "old" && !position.trim()) {
      problems.push("Ten klient wymaga stanowiska — uzupełnij pole „Stanowisko”.");
    }
    if (activeRule.require_champion && !hasChampionInput) {
      problems.push(
        mode === "new"
          ? "Ten klient wymaga Profilu Championa — uzupełnij go na karcie rekrutacji przed generacją."
          : "Ten klient wymaga wymagań z Profilu Championa — wgraj plik championa albo wpisz wymagania must-have / nice-to-have.",
      );
    }
    return problems;
  }, [activeRule, notesChars, projectRef, position, mode, hasChampionInput]);
  const showRequirementProblems =
    requirementProblems.length > 0 &&
    (mode === "new" ? !!selectedRecruitment : !!uploadClient);

  const canSubmitNew =
    !!candidate && !!selectedRecruitment && selectedRecruitment.ready;
  const canSubmitOld = !!cvFile && (!!uploadClient || outsideAssignment);
  const canSubmit =
    (mode === "new" ? canSubmitNew : canSubmitOld) &&
    (!consentRequired || !!consentKey) &&
    requirementProblems.length === 0;

  // ── New mode mutation ───────────────────────────────────────────────────
  // Enqueues background generation (202) and returns immediately — the recruiter
  // can leave the tab; the CV lands on the „Wygenerowane CV" list when ready.
  const generateMut = useMutation({
    mutationFn: async () => {
      if (!candidate || !selectedRecruitment) {
        throw new Error("Missing inputs");
      }
      const res = await api.post<EnqueuedResponse>(
        "/api/cv-generator/generate",
        {
          candidate_id: candidate.id,
          stage_id: selectedRecruitment.stage_id,
          // Asercja, nie wybór: serwer i tak bierze klienta z rekrutacji,
          // a rozjazd odrzuca 422 — dzięki temu rekruter nigdy nie dostanie
          // reguł innego klienta niż ten pokazany na ekranie.
          client_id: selectedRecruitment.client_id ?? null,
          project_ref: projectRef.trim(),
          language,
          blind_cv: blindCv,
          content_mode: contentMode,
          consent_screenshot_key: consentKey ?? "",
        },
        { timeout: 30_000 },
      );
      return res.data;
    },
    onSuccess: (data) => {
      if (autoDownload) autoDownloadIds.current.add(data.id);
      generatedQuery.refetch();
      toast.showSuccess(
        "Generacja ruszyła w tle — CV pojawi się na liście poniżej, gdy będzie gotowe. Możesz zamknąć kartę.",
      );
    },
    onError: async (err: unknown) => {
      const detail = await extractErrorDetail(err);
      toast.showError(detail || "Nie udało się uruchomić generacji.");
    },
  });

  // ── Old mode mutation ───────────────────────────────────────────────────
  const uploadMut = useMutation({
    mutationFn: async () => {
      if (!cvFile) throw new Error("CV file required");
      const fd = new FormData();
      fd.append("cv_file", cvFile);
      if (uploadClient) fd.append("client_id", String(uploadClient.id));
      if (position.trim()) fd.append("position", position.trim());
      if (projectRef.trim()) fd.append("project_ref", projectRef.trim());
      fd.append("language", language);
      fd.append("blind_cv", String(blindCv));
      fd.append("content_mode", contentMode);
      if (screeningNotes.trim()) fd.append("screening_notes", screeningNotes);
      if (mustRequirements.trim())
        fd.append("must_requirements", mustRequirements);
      if (niceRequirements.trim())
        fd.append("nice_requirements", niceRequirements);
      if (championFile) fd.append("champion_file", championFile);
      if (consentKey) fd.append("consent_screenshot_key", consentKey);
      const res = await api.post<EnqueuedResponse>(
        "/api/cv-generator/generate-upload",
        fd,
        {
          // The shared axios instance defaults to application/json; FormData needs
          // an explicit multipart Content-Type so axios fills in the boundary,
          // otherwise FastAPI can't parse the upload (422). Matches every other
          // upload in the app.
          headers: { "Content-Type": "multipart/form-data" },
          timeout: 60_000,
        },
      );
      return res.data;
    },
    onSuccess: (data) => {
      if (autoDownload) autoDownloadIds.current.add(data.id);
      generatedQuery.refetch();
      // Clear the per-candidate inputs so the next CV can be dropped straight in
      // without manually removing the previous file, champion and notes.
      setCvFile(null);
      setChampionFile(null);
      setChampionError(null);
      setScreeningNotes("");
      // Klient, stanowisko i numer projektu ZOSTAJĄ — rekruter zwykle robi
      // kilka CV pod ten sam wakat, a kasowanie ich zmuszałoby do wybierania
      // klienta od nowa przy każdym kandydacie (i zapraszało do pominięcia
      // wyboru, czyli do pliku z ogólną nazwą).
      toast.showSuccess(
        "Generacja ruszyła w tle — CV pojawi się na liście poniżej. Formularz wyczyszczony — możesz wgrać kolejne CV.",
      );
    },
    onError: async (err: unknown) => {
      const detail = await extractErrorDetail(err);
      toast.showError(detail || "Nie udało się uruchomić generacji.");
    },
  });

  const activeMut = mode === "new" ? generateMut : uploadMut;

  // Auto-download CVs enqueued in THIS session as they turn „ready" — keeps the
  // old „pobierz od razu" convenience for recruiters who stay on the page.
  // Leavers just find the CV on the list; the whole point is that closing the
  // tab no longer loses the result, so there is no more beforeunload guard.
  useEffect(() => {
    const items = generatedQuery.data;
    if (!items || autoDownloadIds.current.size === 0) return;
    for (const item of items) {
      if (
        autoDownloadIds.current.has(item.id) &&
        item.status === "ready" &&
        item.can_download
      ) {
        autoDownloadIds.current.delete(item.id);
        void handleDownloadGenerated(item);
      }
    }
    // handleDownloadGenerated is a stable in-scope helper; re-running only when
    // the list data changes is intentional.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generatedQuery.data]);

  function handleSubmit() {
    if (!canWriteSourcing) return;
    activeMut.mutate();
  }

  async function handleDownloadGenerated(item: GeneratedCvItem) {
    try {
      const res = await api.get(`/api/cv-generator/generated/${item.id}/docx`, {
        responseType: "blob",
      });
      downloadBlob(res.data as Blob, item.filename);
    } catch (err) {
      toast.showError((await extractErrorDetail(err)) || "Nie udało się pobrać CV.");
    }
  }

  async function handleDownloadHtml(item: GeneratedCvItem) {
    // Interaktywne CV jako JEDEN plik HTML — do wysyłki mailem jak DOCX.
    try {
      const res = await api.get(`/api/cv-generator/generated/${item.id}/html`, {
        responseType: "blob",
      });
      downloadBlob(
        res.data as Blob,
        item.filename.replace(/\.docx$/i, "") + ".html",
      );
    } catch (err) {
      toast.showError(
        (await extractErrorDetail(err)) || "Nie udało się pobrać pliku HTML.",
      );
    }
  }

  async function handleDeleteGenerated(item: GeneratedCvItem) {
    if (!canWriteSourcing) return;
    try {
      await api.delete(`/api/cv-generator/generated/${item.id}`);
      generatedQuery.refetch();
      toast.showSuccess("Usunięto z listy.");
    } catch (err) {
      toast.showError(
        (await extractErrorDetail(err)) || "Nie udało się usunąć wpisu.",
      );
    }
  }

  function handleModeChange(next: string) {
    const nextMode = next === "old" ? "old" : "new";
    setMode(nextMode);
  }

  function handleCvFile(f: File | null) {
    if (f) {
      const err = fileValidationError(f, CV_ACCEPT);
      if (err) {
        toast.showError(`CV: ${err}`);
        return;
      }
    }
    setCvFile(f);
  }

  function handleChampionFile(f: File | null) {
    if (f) {
      const err = fileValidationError(f, CHAMPION_ACCEPT);
      if (err) {
        setChampionError(err);
        toast.showError(`Profil Championa: ${err}`);
        return;
      }
    }
    setChampionError(null);
    setChampionFile(f);
  }

  function handleChampionEmptyDrop() {
    setChampionError(
      "Nie udało się odczytać upuszczonego pliku — wybierz go z dysku, klikając pole powyżej.",
    );
  }

  return (
    <div className="container mx-auto max-w-3xl py-8">
      <div className="mb-6 flex items-start gap-3">
        <div className="rounded-xl bg-primary/10 p-3 text-primary">
          <Sparkles className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-foreground">Generator CV</h1>
          <p className="text-sm text-muted-foreground">
            Wygeneruj branżowo dopasowane CV w szablonie B2B Network. Dwa tryby:
            zaciąganie danych z NEXUSa lub manualny upload plików (1:1 jak
            zewnętrzny CV-Generator).
          </p>
        </div>
      </div>

      {canWriteSourcing ? (
        <>
      <Card className="mb-4">
        <CardHeader>
          <CardTitle className="text-base">Tryb</CardTitle>
        </CardHeader>
        <CardContent>
          <RadioGroup
            value={mode}
            onValueChange={handleModeChange}
            className="grid grid-cols-1 gap-3 sm:grid-cols-2"
          >
            <label
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors",
                mode === "new"
                  ? "border-primary bg-primary/5"
                  : "border-border hover:bg-muted/30",
              )}
            >
              <RadioGroupItem value="new" className="mt-1" />
              <div>
                <div className="text-sm font-medium">New (z procesu)</div>
                <div className="text-xs text-muted-foreground">
                  Wybierz konsultanta i rekrutację — system zaciąga CV, profil
                  championa i notatki z NEXUSa.
                </div>
              </div>
            </label>
            <label
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors",
                mode === "old"
                  ? "border-primary bg-primary/5"
                  : "border-border hover:bg-muted/30",
              )}
            >
              <RadioGroupItem value="old" className="mt-1" />
              <div>
                <div className="text-sm font-medium">Old (upload plików)</div>
                <div className="text-xs text-muted-foreground">
                  Wgraj CV (PDF / DOCX), opcjonalnie Profil Championa i
                  notatki — 1:1 jak external CV-Generator.
                </div>
              </div>
            </label>
          </RadioGroup>
        </CardContent>
      </Card>

      {mode === "new" ? (
        <NewModeForm
          candidate={candidate}
          candidateOpen={candidateOpen}
          candidateQuery={candidateQuery}
          candidatesQuery={candidatesQuery}
          recruitmentsQuery={recruitmentsQuery}
          selectedRecruitment={selectedRecruitment}
          stageId={stageId}
          setCandidate={setCandidate}
          setCandidateOpen={setCandidateOpen}
          setCandidateQuery={setCandidateQuery}
          setStageId={setStageId}
        />
      ) : (
        <OldModeForm
          cvFile={cvFile}
          championFile={championFile}
          championError={championError}
          screeningNotes={screeningNotes}
          mustRequirements={mustRequirements}
          niceRequirements={niceRequirements}
          setCvFile={handleCvFile}
          setChampionFile={handleChampionFile}
          onChampionEmptyDrop={handleChampionEmptyDrop}
          setScreeningNotes={setScreeningNotes}
          setMustRequirements={setMustRequirements}
          setNiceRequirements={setNiceRequirements}
        />
      )}

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Opcje</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label className="block">Klient</Label>
            {mode === "new" ? (
              // W tym trybie klient WYNIKA z rekrutacji — pokazujemy go, ale
              // nie pozwalamy wybrać. Możliwość rozjazdu z ofertą oznaczałaby
              // zastosowanie reguł innego klienta, niż widać na ekranie.
              <p className="text-sm">
                {selectedRecruitment?.client_name ? (
                  <span className="font-medium">
                    {selectedRecruitment.client_name}
                  </span>
                ) : (
                  <span className="text-muted-foreground">
                    {selectedRecruitment
                      ? "Ta rekrutacja nie ma przypisanego klienta."
                      : "Wybierz rekrutację, żeby zobaczyć klienta."}
                  </span>
                )}
              </p>
            ) : (
              <>
                <UploadCandidatePicker
                  candidate={uploadCandidate}
                  open={uploadCandidateOpen}
                  query={uploadCandidateQuery}
                  candidatesQuery={uploadCandidatesQuery}
                  setCandidate={setUploadCandidate}
                  setOpen={setUploadCandidateOpen}
                  setQuery={setUploadCandidateQuery}
                />
                {uploadCandidate && uploadClientOptions.length > 1 ? (
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="text-muted-foreground">
                      Kandydat jest w procesach kilku klientów — wybierz:
                    </span>
                    {uploadClientOptions.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        onClick={() => setUploadClient(c)}
                        className={
                          uploadClient?.id === c.id
                            ? "rounded-full bg-primary px-2 py-0.5 text-primary-foreground"
                            : "rounded-full border px-2 py-0.5 hover:bg-muted"
                        }
                      >
                        {c.name}
                      </button>
                    ))}
                  </div>
                ) : null}
                {uploadCandidate &&
                uploadRecruitmentsQuery.isSuccess &&
                uploadClientOptions.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    Ten kandydat nie ma procesu z przypisanym klientem — wybierz
                    klienta ręcznie.
                  </p>
                ) : null}
                <ClientSinglePicker
                  value={uploadClient}
                  onChange={setUploadClient}
                  queryKey="clients-lookup-cv-generator"
                  placeholder="Wybierz klienta…"
                  allowClear
                />
                <p className="text-xs text-muted-foreground">
                  Klient włącza jego reguły: nazwę pliku, język, blokady i
                  instrukcje Delivery Leada. Wskaż kandydata z bazy, a klient
                  podpowie się z jego procesu.
                </p>
                {!uploadClient ? (
                  <label className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-2 text-xs text-amber-800 dark:text-amber-300">
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={outsideAssignment}
                      onChange={(e) => setOutsideAssignment(e.target.checked)}
                    />
                    <span>
                      Generuję CV poza zleceniem — bez klienta nie zadziała żadna
                      reguła (nazwa pliku i język będą ogólne, bez blokad i
                      instrukcji Delivery Leada).
                    </span>
                  </label>
                ) : null}
              </>
            )}
            <ClientCvRuleBanner
              clientId={effectiveClientId}
              rule={cvRuleQuery.data}
              isLoading={cvRuleQuery.isLoading}
              isError={cvRuleQuery.isError}
            />
          </div>

          {mode === "old" && (
            <div>
              <Label className="mb-2 block" htmlFor="cvgen-position">
                Stanowisko
              </Label>
              <Input
                id="cvgen-position"
                value={position}
                onChange={(e) => setPosition(e.target.value)}
                placeholder="np. Analityk Biznesowy"
                maxLength={300}
                className="sm:max-w-md"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Wchodzi w nazwę pliku u klientów, których wzór jej wymaga.
                W tym trybie nie ma rekrutacji, z której dałoby się ją odczytać.
              </p>
            </div>
          )}

          {(activeRule?.filename_pattern?.includes("{PROJEKT}") ||
            activeRule?.require_project_ref) && (
            <div>
              <Label className="mb-2 block" htmlFor="cvgen-project">
                Numer / nazwa projektu
              </Label>
              <Input
                id="cvgen-project"
                value={projectRef}
                onChange={(e) => setProjectRef(e.target.value)}
                placeholder="np. 4521"
                maxLength={120}
                className="sm:max-w-md"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Wzór nazwy pliku tego klienta zawiera numer projektu. Bez niego
                plik dostanie nazwę bez tego członu.
              </p>
            </div>
          )}

          <div>
            <Label className="mb-2 block">Obróbka treści</Label>
            <div className={lockedMode ? "pointer-events-none opacity-60" : undefined}>
              <ContentModeTiles value={contentMode} onChange={setContentMode} />
            </div>
            {lockedMode ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Tryb ustalony przez Delivery Leada dla tego klienta — wybór jest
                zablokowany. Zmienisz to w regułach CV klienta.
              </p>
            ) : null}
          </div>

          <div>
            <Label className="mb-2 block">Język CV</Label>
            <div className={forcedLanguage ? "pointer-events-none opacity-60" : undefined}>
              <LanguageTiles
                value={language}
                onChange={setLanguage}
                className="sm:max-w-md"
              />
            </div>
            {forcedLanguage ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Ten klient wymaga CV w języku{" "}
                {forcedLanguage === "en" ? "angielskim" : "polskim"} — wybór
                jest zablokowany. Zmienisz to w regułach CV klienta.
              </p>
            ) : null}
          </div>

          <ConsentScreenshotField
            value={consentKey}
            onChange={(key: string | null) => setConsentKey(key)}
            required={consentRequired}
            disabled={generateMut.isPending || uploadMut.isPending}
          />

          <div className="flex items-center justify-between gap-4">
            <div>
              <Label className="block">Blind CV</Label>
              <p className="text-xs text-muted-foreground">
                Anonimizuje imię, nazwisko i nazwy firm w doświadczeniu — używaj
                przy share-ach klientom przed zaakceptowaniem profilu.
              </p>
            </div>
            <Switch checked={blindCv} onCheckedChange={setBlindCv} />
          </div>

          <div className="flex items-center justify-between gap-4">
            <div>
              <Label className="block">Pobierz automatycznie po wygenerowaniu</Label>
              <p className="text-xs text-muted-foreground">
                Włączone — CV od razu trafia do folderu „Pobrane" (jak
                dotychczas). Wyłączone — CV pojawia się tylko na liście
                „Wygenerowane CV" poniżej (Podgląd / Pobierz), bez zaśmiecania
                Pobranych przy generowaniu wielu CV pod rząd.
              </p>
            </div>
            <Switch checked={autoDownload} onCheckedChange={setAutoDownload} />
          </div>
        </CardContent>
      </Card>

      {mode === "old" && championError && !championFile && (
        <Alert
          variant="warning"
          className="mt-6"
          title="Wygenerujesz CV bez Profilu Championa"
          description="Technologie klienta nie zostaną wytłuszczone, a lista brakujących wymagań nie powstanie. Popraw plik w kroku 2 albo generuj świadomie."
        />
      )}

      {showRequirementProblems && (
        <Alert
          variant="warning"
          className="mt-6"
          title="Klient wymaga uzupełnienia danych przed generacją"
          description={
            <ul className="list-disc space-y-1 pl-4">
              {requirementProblems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          }
        />
      )}

      {/* Przyklejony pasek akcji. Formularz bywa bardzo długi (Krok 1–4 +
          „Opcje" ≈ 2600 px), a wcześniej przycisk „Generuj" leżał na samym dole
          w normalnym przepływie — po wgraniu CV/championa wyglądało to, jakby
          ekran „uciął się" na Kroku 2 i nie było czym wygenerować. `sticky
          bottom-0` w kontenerze przewijania (main z overflow-y-auto) trzyma
          przycisk przy dolnej krawędzi widoku przez cały formularz i zwalnia go
          dopiero przy liście „Wygenerowane CV" poniżej. */}
      <div className="sticky bottom-0 z-20 mt-6 flex flex-wrap items-center justify-end gap-x-4 gap-y-2 border-t border-border bg-background/95 py-3 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <p className="mr-auto hidden text-xs text-muted-foreground sm:block">
          {activeMut.isPending
            ? "Uruchamiam generację…"
            : "Generacja leci w tle (60–90 s) — CV pojawi się na liście poniżej. Możesz zamknąć kartę."}
        </p>
        <Button
          size="lg"
          disabled={!canSubmit || activeMut.isPending}
          onClick={handleSubmit}
        >
          {activeMut.isPending ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Generuję…
            </>
          ) : (
            <>
              <Download className="mr-2 h-4 w-4" />
              Generuj CV (DOCX)
            </>
          )}
        </Button>
      </div>
        </>
      ) : (
        <Alert
          variant="info"
          className="mb-4"
          title="Tryb tylko do odczytu"
          description="Możesz przeglądać i pobierać wcześniej wygenerowane CV, ale generowanie, udostępnianie i usuwanie wymagają prawa zapisu w Sourcing."
        />
      )}

      {/* ── Wygenerowane CV — lista trwała (przetrwa nawigację/odświeżenie) ── */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            Wygenerowane CV
          </CardTitle>
          <CardDescription>
            Ostatnio wygenerowane CV — Podgląd w aplikacji lub Pobierz, gdy
            będziesz gotów. Lista zostaje po przejściu do innych kandydatów.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {generatedQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">Ładowanie…</p>
          ) : !generatedQuery.data?.length ? (
            <p className="text-sm text-muted-foreground">
              Brak wygenerowanych CV — wygeneruj pierwsze powyżej.
            </p>
          ) : (
            // Lista „ostatnio wygenerowanych" rośnie bez ograniczeń (na prodzie
            // 60+ pozycji ≈ 4000 px) i była CAŁĄ resztą strony — cały ekran to
            // wewnętrzny scroll `main` (overflow-y-auto), a na macOS pasek się
            // chowa, więc lista uciekała pod dolną krawędź bez sygnału, że coś
            // jest niżej: użytkownik zgłaszał „dolna część strony znika / ucięta"
            // (po wgraniu Championa i wygenerowaniu — wtedy patrzy na wynik).
            // Własny scroll domyka listę w samodzielną kartę z widocznym paskiem;
            // najnowsze CV jest na górze, a strona przestaje być monolitem ~7000 px.
            <ul className="max-h-[30rem] divide-y divide-border overflow-y-auto pr-2">
              {generatedQuery.data.map((item) => (
                <GeneratedCvRow
                  key={item.id}
                  item={item}
                  onPreview={setPreviewItem}
                  onDownload={handleDownloadGenerated}
                  onDownloadHtml={handleDownloadHtml}
                  onShare={setShareItem}
                  onDelete={handleDeleteGenerated}
                  canWrite={canWriteSourcing}
                />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <GeneratedCvPreviewModal
        item={previewItem}
        onClose={() => setPreviewItem(null)}
        onDownload={handleDownloadGenerated}
      />

      {canWriteSourcing ? (
        <CvGeneratedShareModal
          generatedId={shareItem?.id ?? null}
          candidateName={shareItem?.candidate_name}
          onClose={() => setShareItem(null)}
        />
      ) : null}
    </div>
  );
}

// ── New mode form ──────────────────────────────────────────────────────────

type NewModeFormProps = {
  candidate: CandidateOption | null;
  candidateOpen: boolean;
  candidateQuery: string;
  candidatesQuery: {
    data?: CandidateOption[];
    isLoading: boolean;
  };
  recruitmentsQuery: {
    data?: RecruitmentOption[];
    isLoading: boolean;
  };
  selectedRecruitment: RecruitmentOption | null;
  stageId: string;
  setCandidate: (c: CandidateOption | null) => void;
  setCandidateOpen: (v: boolean) => void;
  setCandidateQuery: (v: string) => void;
  setStageId: (v: string) => void;
};

function NewModeForm({
  candidate,
  candidateOpen,
  candidateQuery,
  candidatesQuery,
  recruitmentsQuery,
  selectedRecruitment,
  stageId,
  setCandidate,
  setCandidateOpen,
  setCandidateQuery,
  setStageId,
}: NewModeFormProps) {
  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Krok 1 — Konsultant</CardTitle>
          <CardDescription>
            Zacznij wpisywać imię, nazwisko lub e-mail.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Popover open={candidateOpen} onOpenChange={setCandidateOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                role="combobox"
                aria-expanded={candidateOpen}
                className="w-full justify-between"
              >
                <span className="flex items-center gap-2 truncate">
                  <UserSearch className="h-4 w-4 text-muted-foreground" />
                  {candidate ? (
                    <span className="truncate">
                      {candidate.full_name}
                      {candidate.position ? (
                        <span className="ml-2 text-xs text-muted-foreground">
                          {candidate.position}
                        </span>
                      ) : null}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">
                      Wybierz konsultanta…
                    </span>
                  )}
                </span>
                <ChevronsUpDown className="h-4 w-4 text-muted-foreground" />
              </Button>
            </PopoverTrigger>
            <PopoverContent
              align="start"
              className="w-(--radix-popover-trigger-width) p-0"
            >
              <Command shouldFilter={false}>
                <div className="flex items-center border-b border-border px-3">
                  <Search className="mr-2 h-4 w-4 text-muted-foreground" />
                  <CommandInput
                    placeholder="Szukaj kandydata…"
                    value={candidateQuery}
                    onValueChange={setCandidateQuery}
                    className="h-10 border-0"
                  />
                </div>
                <CommandList>
                  {candidatesQuery.isLoading && (
                    <div className="p-4 text-center text-xs text-muted-foreground">
                      Ładowanie…
                    </div>
                  )}
                  <CommandEmpty>Brak wyników.</CommandEmpty>
                  <CommandGroup>
                    {(candidatesQuery.data ?? []).map((c) => (
                      <CommandItem
                        key={c.id}
                        value={String(c.id)}
                        onSelect={() => {
                          setCandidate(c);
                          setStageId("");
                          setCandidateOpen(false);
                        }}
                      >
                        <div className="flex flex-col">
                          <span className="font-medium">{c.full_name}</span>
                          <span className="text-xs text-muted-foreground">
                            {[c.position, c.email].filter(Boolean).join(" · ")}
                          </span>
                        </div>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
        </CardContent>
      </Card>

      {candidate && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>Krok 2 — Proces rekrutacyjny</CardTitle>
            <CardDescription>
              Wymagany Profil Championa oraz co najmniej jedna notatka z rozmowy
              dla wybranego procesu.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <RecruitmentCombobox
              recruitments={recruitmentsQuery.data ?? []}
              value={stageId}
              onChange={setStageId}
              loading={recruitmentsQuery.isLoading}
            />

            {selectedRecruitment && (
              <div className="flex flex-wrap gap-2 text-xs">
                <ReadyBadge
                  label="CV w systemie"
                  ok={selectedRecruitment.has_cv}
                />
                <ReadyBadge
                  label="Profil Championa"
                  ok={selectedRecruitment.has_champion}
                />
                <ReadyBadge
                  label="Notatki z rozmów"
                  ok={selectedRecruitment.has_notes}
                />
              </div>
            )}

            {selectedRecruitment && !selectedRecruitment.ready && (
              <Alert
                variant="warning"
                title="Nie można wygenerować CV"
                description={
                  <div className="space-y-1">
                    {!selectedRecruitment.has_cv && (
                      <div>
                        Kandydat nie ma wgranego CV (PDF/DOCX) w systemie —
                        dodaj plik w zakładce Dokumenty na profilu kandydata.
                      </div>
                    )}
                    {!selectedRecruitment.has_champion && (
                      <div>
                        Brakuje Profilu Championa (must-have, nice-to-have,
                        kontekst projektu). Uzupełnij go na karcie rekrutacji zanim
                        wygenerujesz CV.
                      </div>
                    )}
                    {!selectedRecruitment.has_notes && (
                      <div>
                        Brak notatek z rozmów — wymagana co najmniej jedna:
                        screening, transkrypt rozmowy CloudTalk albo notatka
                        procesu.
                      </div>
                    )}
                  </div>
                }
              />
            )}
          </CardContent>
        </Card>
      )}
    </>
  );
}

// ── Upload: kandydat z bazy (podpowiedź klienta) ───────────────────────────

type UploadCandidatePickerProps = {
  candidate: CandidateOption | null;
  open: boolean;
  query: string;
  candidatesQuery: { data?: CandidateOption[]; isLoading: boolean };
  setCandidate: (c: CandidateOption | null) => void;
  setOpen: (v: boolean) => void;
  setQuery: (v: string) => void;
};

function UploadCandidatePicker({
  candidate,
  open,
  query,
  candidatesQuery,
  setCandidate,
  setOpen,
  setQuery,
}: UploadCandidatePickerProps) {
  return (
    <div className="flex items-center gap-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            aria-label="Kandydat z bazy"
            className="w-full justify-between font-normal"
          >
            <span className="flex items-center gap-2 truncate">
              <UserSearch className="h-4 w-4 text-muted-foreground" />
              {candidate ? (
                <span className="truncate">{candidate.full_name}</span>
              ) : (
                <span className="text-muted-foreground">
                  Kandydat z bazy (opcjonalnie) — podpowie klienta z procesu
                </span>
              )}
            </span>
            <ChevronsUpDown className="h-4 w-4 text-muted-foreground" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-(--radix-popover-trigger-width) p-0">
          <Command shouldFilter={false}>
            <div className="flex items-center border-b border-border px-3">
              <Search className="mr-2 h-4 w-4 text-muted-foreground" />
              <CommandInput
                placeholder="Szukaj kandydata…"
                value={query}
                onValueChange={setQuery}
                className="h-10 border-0"
              />
            </div>
            <CommandList>
              {candidatesQuery.isLoading && (
                <div className="p-4 text-center text-xs text-muted-foreground">
                  Ładowanie…
                </div>
              )}
              <CommandEmpty>Brak wyników.</CommandEmpty>
              <CommandGroup>
                {(candidatesQuery.data ?? []).map((c) => (
                  <CommandItem
                    key={c.id}
                    value={String(c.id)}
                    onSelect={() => {
                      setCandidate(c);
                      setOpen(false);
                    }}
                  >
                    <div className="flex flex-col">
                      <span className="font-medium">{c.full_name}</span>
                      <span className="text-xs text-muted-foreground">
                        {[c.position, c.email].filter(Boolean).join(" · ")}
                      </span>
                    </div>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {candidate ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Wyczyść kandydata"
          onClick={() => setCandidate(null)}
        >
          <X className="h-4 w-4" />
        </Button>
      ) : null}
    </div>
  );
}

// ── Old mode form ──────────────────────────────────────────────────────────

type OldModeFormProps = {
  cvFile: File | null;
  championFile: File | null;
  championError: string | null;
  screeningNotes: string;
  mustRequirements: string;
  niceRequirements: string;
  setCvFile: (f: File | null) => void;
  setChampionFile: (f: File | null) => void;
  onChampionEmptyDrop: () => void;
  setScreeningNotes: (v: string) => void;
  setMustRequirements: (v: string) => void;
  setNiceRequirements: (v: string) => void;
};

function OldModeForm({
  cvFile,
  championFile,
  championError,
  screeningNotes,
  mustRequirements,
  niceRequirements,
  setCvFile,
  setChampionFile,
  onChampionEmptyDrop,
  setScreeningNotes,
  setMustRequirements,
  setNiceRequirements,
}: OldModeFormProps) {
  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Krok 1 — Plik CV</CardTitle>
          <CardDescription>
            Wgraj surowe CV kandydata (PDF lub DOCX, max {MAX_UPLOAD_MB} MB) —
            Claude przeanalizuje treść i wyciągnie strukturę.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FileDropZone
            file={cvFile}
            onFile={setCvFile}
            accept={CV_ACCEPT}
            label="Upuść CV tutaj lub kliknij, by wybrać plik"
            description="PDF / DOCX"
          />
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Krok 2 — Profil Championa (opcjonalnie)</CardTitle>
          <CardDescription>
            Wgraj DOCX z sekcjami MUST-HAVE / NICE-TO-HAVE / Kontekst /
            Pytania — system wytłuści kluczowe technologie w wygenerowanym CV
            i zwróci listę brakujących wymagań.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FileDropZone
            file={championFile}
            onFile={setChampionFile}
            accept={CHAMPION_ACCEPT}
            label="Upuść DOCX championa tutaj lub kliknij, by wybrać"
            description="DOCX"
            invalid={!!championError}
            onEmptyDrop={onChampionEmptyDrop}
          />
          {championError && (
            <Alert
              variant="error"
              className="mt-3"
              title="Profil Championa nie został wczytany"
              description={championError}
            />
          )}
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Krok 3 — Notatki ze screeningu (opcjonalnie)</CardTitle>
          <CardDescription>
            Wklej notatki z rozmowy rekrutera — Claude wzbogaci CV o
            technologie i kompetencje wspomniane na screeningu.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Textarea
            rows={6}
            value={screeningNotes}
            onChange={(e) => setScreeningNotes(e.target.value)}
            placeholder="Np. „Kandydat ma 3 lata doświadczenia z Kubernetes, prowadził migrację Jenkinsa do GitHub Actions w poprzedniej firmie…”"
          />
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>
            Krok 4 — Wymagania na kafelki interaktywnego CV (opcjonalnie)
          </CardTitle>
          <CardDescription>
            Z tych wymagań powstaną kafelki „Dopasowanie do wymagań" z
            dowodami-cytatami na publicznym linku dla klienta. Bez nich (i bez
            pliku championa, z którego wymagania biorą się automatycznie) link
            pokaże sam widok klasyczny.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <Label htmlFor="cvgen-must-req" className="mb-1 block">
              Must-have
            </Label>
            <Textarea
              id="cvgen-must-req"
              rows={2}
              value={mustRequirements}
              onChange={(e) => setMustRequirements(e.target.value)}
              placeholder="Np. Kubernetes, AWS, Terraform (przecinki lub nowe linie, max 12)"
            />
          </div>
          <div>
            <Label htmlFor="cvgen-nice-req" className="mb-1 block">
              Nice-to-have
            </Label>
            <Textarea
              id="cvgen-nice-req"
              rows={2}
              value={niceRequirements}
              onChange={(e) => setNiceRequirements(e.target.value)}
              placeholder="Np. Grafana, GitOps (max 8)"
            />
          </div>
        </CardContent>
      </Card>
    </>
  );
}

// ── File drop zone ─────────────────────────────────────────────────────────

type FileDropZoneProps = {
  file: File | null;
  onFile: (f: File | null) => void;
  accept: string;
  label: string;
  description: string;
  /** Tint the zone as rejected — pairs with a caller-rendered error Alert. */
  invalid?: boolean;
  /** Fired when a drop carried no readable file (e.g. dragged from a mail client). */
  onEmptyDrop?: () => void;
};

function FileDropZone({
  file,
  onFile,
  accept,
  label,
  description,
  invalid,
  onEmptyDrop,
}: FileDropZoneProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragOver, setDragOver] = useState(false);

  function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const next = e.target.files?.[0] ?? null;
    onFile(next);
    // Reset so re-picking the SAME file fires `change` again. Without this, a
    // rejected file could not be retried after fixing it on disk — the second
    // pick was a silent no-op, which reads as "the button does nothing".
    e.target.value = "";
  }

  function handleDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    const next = e.dataTransfer.files?.[0] ?? null;
    if (next) {
      onFile(next);
    } else {
      onEmptyDrop?.();
    }
  }

  function handleDragOver(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
    if (!dragOver) setDragOver(true);
  }

  function handleDragLeave(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  }

  if (file) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-lg border border-border p-3">
        <div className="flex min-w-0 items-center gap-3">
          <FileText className="h-5 w-5 shrink-0 text-primary" />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{file.name}</div>
            <div className="text-xs text-muted-foreground">
              {(file.size / 1024).toFixed(0)} KB
            </div>
          </div>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onFile(null)}
          aria-label="Usuń plik"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    );
  }

  return (
    <label
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-6 text-center transition-colors",
        dragOver
          ? "border-primary bg-primary/5"
          : invalid
            ? "border-destructive/60 bg-destructive/5"
            : "border-border hover:bg-muted/30",
      )}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        onChange={handleChange}
        className="sr-only"
      />
      <Upload className="h-6 w-6 text-muted-foreground" />
      <div className="text-sm font-medium">{label}</div>
      <div className="text-xs text-muted-foreground">{description}</div>
    </label>
  );
}

// ── Inline UI helpers ──────────────────────────────────────────────────────

function ReadyBadge({ label, ok }: { label: string; ok: boolean }) {
  return (
    <Badge
      variant={ok ? "success" : "warning"}
      className={cn("flex items-center gap-1")}
    >
      {ok ? (
        <CheckCircle2 className="h-3 w-3" />
      ) : (
        <AlertTriangle className="h-3 w-3" />
      )}
      {label}
    </Badge>
  );
}

// ── „Wygenerowane CV" list row ───────────────────────────────────────────────

type GeneratedCvRowProps = {
  item: GeneratedCvItem;
  onPreview: (item: GeneratedCvItem) => void;
  onDownload: (item: GeneratedCvItem) => void;
  onDownloadHtml: (item: GeneratedCvItem) => void;
  onShare: (item: GeneratedCvItem) => void;
  onDelete: (item: GeneratedCvItem) => void;
  canWrite: boolean;
};

function GeneratedCvRow({
  item,
  onPreview,
  onDownload,
  onDownloadHtml,
  onShare,
  onDelete,
  canWrite,
}: GeneratedCvRowProps) {
  const warnings = item.warnings ?? [];
  // Ostrzeżenia klasy „BRAK POKRYCIA" (treść bez pokrycia w źródłowym CV)
  // rozwijają się SAME, gdy dokument powstał pod konkretnego klienta.
  // Dziesięć z czternastu szablonów Championa prosi wprost: „sprawdzajcie, czy
  // AI nie namieszało — porównujcie z oryginalnym CV". Zwinięty licznik
  // spełniał tę prośbę tylko dla kogoś, kto i tak kliknie; dla wysyłki do
  // klienta to za mało. Bez blokowania pobrania — blokada nauczyłaby ludzi
  // obchodzić narzędzie, a deadline'y i wyjątki są realne.
  const hasCertainWarnings = warnings.some(isCertainWarning);
  const [showWarnings, setShowWarnings] = useState(
    () => hasCertainWarnings && item.client_id != null,
  );

  return (
    <li className="py-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-medium">{item.candidate_name}</span>
            {item.position && (
              <span className="truncate text-xs text-muted-foreground">
                · {item.position}
              </span>
            )}
            <Badge variant="neutral" className="uppercase">
              {item.language}
            </Badge>
            {item.blind && <Badge variant="outline">Blind</Badge>}
            {item.mode === "upload" && <Badge variant="outline">Upload</Badge>}
            {item.status === "processing" && (
              <Badge variant="warning" className="flex items-center gap-1">
                <Loader2 className="h-3 w-3 animate-spin" />
                Generuję…
              </Badge>
            )}
            {item.status === "failed" && (
              <Badge variant="danger" className="flex items-center gap-1">
                <AlertTriangle className="h-3 w-3" />
                Błąd
              </Badge>
            )}
            {item.status === "ready" && warnings.length > 0 && (
              <button
                type="button"
                onClick={() => setShowWarnings((v) => !v)}
                className="inline-flex items-center gap-1 text-xs text-amber-600 hover:underline dark:text-amber-400"
              >
                <AlertTriangle className="h-3 w-3" />
                {warnings.length} {warnings.length === 1 ? "uwaga" : "uwagi"}
              </button>
            )}
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {item.created_by_name ? `${item.created_by_name} · ` : ""}
            {formatGeneratedDate(item.created_at)}
          </p>
          {item.status === "failed" && item.error_message && (
            <p className="mt-1 text-xs text-destructive">{item.error_message}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {item.status === "processing" ? (
            <span
              className="flex items-center gap-1 text-xs text-muted-foreground"
              title="Generacja w toku — możesz zamknąć kartę"
            >
              <Loader2 className="h-4 w-4 animate-spin" />
            </span>
          ) : (
            <>
              {item.status === "ready" && (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={!item.can_download}
                    onClick={() => onPreview(item)}
                    title="Podgląd w aplikacji"
                  >
                    <Eye className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={!item.can_download}
                    onClick={() => onDownload(item)}
                    title="Pobierz DOCX"
                  >
                    <Download className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={!item.can_download}
                    onClick={() => onDownloadHtml(item)}
                    title="Pobierz interaktywny HTML (jeden plik: kafelki + widok klasyczny)"
                  >
                    <FileCode2 className="h-4 w-4" />
                  </Button>
                  {canWrite ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={!item.can_download}
                      onClick={() => onShare(item)}
                      title="Udostępnij klientowi (link)"
                    >
                      <Link2 className="h-4 w-4" />
                    </Button>
                  ) : null}
                </>
              )}
              {canWrite && item.can_delete && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onDelete(item)}
                  title="Usuń z listy"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </>
          )}
        </div>
      </div>
      {item.status === "ready" && showWarnings && warnings.length > 0 && (
        <ul className="ml-4 mt-2 list-disc space-y-0.5 text-xs text-amber-700 dark:text-amber-300">
          {warnings.map((w, idx) => (
            <li key={idx}>{w}</li>
          ))}
        </ul>
      )}
    </li>
  );
}


// ── Inline DOCX preview for a saved generated CV ─────────────────────────────

type GeneratedCvPreviewModalProps = {
  item: GeneratedCvItem | null;
  onClose: () => void;
  onDownload: (item: GeneratedCvItem) => void;
};

function GeneratedCvPreviewModal({
  item,
  onClose,
  onDownload,
}: GeneratedCvPreviewModalProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  // Fetch the re-rendered DOCX and render it inline via docx-preview (lazy
  // import so the parser stays out of the main bundle until a preview opens).
  useEffect(() => {
    if (!item) return;
    let cancelled = false;
    setStatus("loading");
    (async () => {
      try {
        const res = await api.get(
          `/api/cv-generator/generated/${item.id}/docx`,
          { responseType: "blob" },
        );
        if (cancelled) return;
        const { renderAsync } = await import("docx-preview");
        const host = hostRef.current;
        if (!host || cancelled) return;
        host.innerHTML = "";
        await renderAsync(res.data as Blob, host, undefined, {
          className: "docx",
          inWrapper: true,
          breakPages: true,
          useBase64URL: true,
        });
        if (!cancelled) setStatus("ready");
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [item]);

  return (
    <Dialog open={!!item} onOpenChange={(o) => !o && onClose()}>
      <DialogContent size="full" className="h-[92vh] gap-0 p-0">
        <DialogHeader className="flex-row items-center justify-between gap-3 border-b px-4 py-3">
          <DialogTitle className="min-w-0 truncate text-base font-semibold">
            {item?.candidate_name}
            {item?.position ? ` — ${item.position}` : ""}
          </DialogTitle>
          {item && (
            <Button size="sm" variant="outline" onClick={() => onDownload(item)}>
              <Download className="mr-2 h-4 w-4" />
              Pobierz
            </Button>
          )}
        </DialogHeader>
        <div className="relative flex-1 overflow-auto bg-muted/30 p-4">
          {status !== "ready" && (
            <div className="absolute inset-0 flex items-center justify-center text-sm">
              {status === "loading" ? (
                <span className="flex items-center text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Renderowanie podglądu…
                </span>
              ) : (
                <span className="text-destructive">
                  Nie udało się wyświetlić podglądu — pobierz plik DOCX.
                </span>
              )}
            </div>
          )}
          <div ref={hostRef} className="docx-preview-host mx-auto" />
        </div>
      </DialogContent>
    </Dialog>
  );
}
