"use client";

/**
 * Strona `/jobs/new` — nowa rekrutacja z requestu klienta (22.09.2026).
 *
 * Zastępuje okno „Dodaj rekrutację” (9 pól) + ręczne wypełnianie Championa +
 * dok gotowości. Decyzje Artura: tworzenie przenosimy do NEXUSA, start od
 * maila klienta, AI wypełnia minimum, DL sprawdza i jednym kliknięciem
 * „Utwórz i przekaż do searchu”. Pola spoza minimum (TAC, szablon procesu,
 * Program/Train, typ, widełki mies.) nie istnieją ani tu, ani w ustawieniach
 * rekrutacji — ustawia je backend.
 *
 * Od 02.10.2026 (makiety https://claude.ai/artifact/UPDv1tSQBeo5t9kLW6WJoH):
 * krok 1 to klient i trzy kafle źródła (`NewJobSourceStep`), krok 2 to sześć
 * sekcji — wymagania są jedną listą słów kluczowych, pytania mają odpowiedź,
 * która odpada, a Delivery Lead potwierdza kategorię i wybiera, czy rekrutera
 * prowadzącego przydzieli automat, czy wskaże go sam (`NewJobTeamStep`).
 *
 * Od 04.10.2026 rekrutacja nigdy nie jest szkicem (decyzja Artura): jedno
 * `POST /api/jobs` tworzy ją razem z profilem Championa, hiring managerem,
 * przekazaniem i publikacją, w jednej transakcji. Brak = 422 z listą braków
 * i nic nie powstaje. Praca w toku żyje na koncie autora jako formularz
 * (`/api/job-intake/forms`): zapis co kilka sekund i przy „Dokończę później”.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check } from "lucide-react";

import api, { championApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ds/PageHeader";
import type { ClientRef } from "@/components/clients/ClientSinglePicker";
import { SimilarRequestsBanner } from "@/components/v2/jobs/SimilarRequestsBanner";
import {
  EMPTY_INTAKE_FORM,
  MISSING_LABEL,
  CLIENT_TITLE_REQUIRED_TEXT,
  MISSING_SECTION,
  applyTemplate,
  loadTemplateSource,
  buildCreateJobPayload,
  formFromIntake,
  highlightSegments,
  intakeFormLabel,
  missingFor,
  missingHeadline,
  mustOf,
  restoreIntakeForm,
  jobTitleFor,
  sectionAnchor,
  serverBlockerSection,
  serverBlockersFromError,
  serverBlockersHeadline,
  templateLegacyFields,
  type CreateHandoff,
  type IntakeForm,
  type ServerBlocker,
  type RequestIntakeResponse,
  type TemplateRows,
  type TemplateSourceJob,
} from "@/lib/job-request-intake";
import type { RowCriticalState } from "@/lib/requirement-rows";
import { fetchRowsFromLegacy, useRowCriticalInfo } from "@/lib/requirement-rows-api";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
import { NewJobSourceStep, type NewJobSource } from "./NewJobSourceStep";
import { NewJobReviewForm, NewJobSectionNav } from "./NewJobReviewForm";
import { SimilarJobsPicker } from "./SimilarJobsPicker";
import { ClientAskedBeforeHint } from "./ClientAskedBeforeHint";
import { UnfinishedIntakeForms } from "./UnfinishedIntakeForms";
import {
  deleteIntakeForm,
  fetchIntakeForm,
  fetchIntakeForms,
  isFormsLimitError,
  jobIntakeFormKeys,
  saveIntakeForm,
  type IntakeFormListItem,
  type IntakeFormRead,
  type IntakeFormState,
  type IntakeFormWrite,
} from "@/lib/api/jobIntakeForms";
import {
  automaticAssignmentAvailable,
  automaticHandoffOutcome,
  resolveRecruiterAssignment,
  type AllocationMode,
  type RecruiterAssignment,
} from "@/lib/recruiter-assignment";
import {
  NEW_JOB_PRIORITY_LEVEL,
  rawPriorityForLevel,
  type PriorityLevel,
} from "@/lib/request-priority";
import { invalidateJobTeam } from "@/lib/job-team-cache";
import {
  NewJobTeamStep,
  type CategoryOption,
  type RecruiterOption,
} from "./NewJobTeamStep";
import {
  fetchPortalConfig,
  fetchPublicDraft,
  jobPortalKeys,
  readyPortals,
  EMPTY_LISTING_OPTIONS,
  type PublicDraftRead,
} from "@/lib/api/jobPortals";
import {
  listingDefaultsFromForm,
  portalPlanBlocker,
  publicDraftRequest,
  publishNewJobToPortals,
  type NewJobPortalPlan,
} from "@/lib/new-job-portal-publish";
import { NewJobPortalsStep } from "./NewJobPortalsStep";

export type Step = "request" | "review";

/** Autozapis formularza: po tylu ms ciszy od ostatniej zmiany. */
export const AUTOSAVE_DELAY_MS = 3_000;

export const FORMS_LIMIT_TEXT =
  "Masz już komplet niedokończonych formularzy. Dokończ albo usuń któryś w kroku 1 — wtedy ten się zapisze.";

/** Stan zapisu formularza na koncie — stopka mówi go jednym zdaniem. */
export type AutosaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved"; at: string }
  | { status: "error"; message: string };

function hourMinute(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function autosaveLabel(state: AutosaveState): string | null {
  switch (state.status) {
    case "saving":
      return "Zapisuję formularz…";
    case "saved":
      return `Formularz zapisany ${hourMinute(state.at)}`.trim();
    case "error":
      return state.message;
    default:
      return null;
  }
}

const SOURCES: readonly NewJobSource[] = ["text", "file", "manual"];

/** `GET /api/job-intake/handoff-options` — rekrutacji jeszcze nie ma. */
interface HandoffOptions {
  automatic_enabled: boolean;
  mode: AllocationMode;
}

/** `POST /api/job-intake/category-suggestion`. */
interface CategorySuggestion {
  suggested_id: number | null;
  categories: CategoryOption[];
}

/**
 * Stare pola wymagań rekrutacji-szablonu zamienione na wiersze słów
 * kluczowych. Awaria zamiany nie blokuje szablonu — formularz bierze wtedy
 * każde must-have jako wiersz z jednym słowem.
 */
async function templateRows(src: TemplateSourceJob): Promise<TemplateRows | null> {
  const legacy = templateLegacyFields(src);
  if (legacy == null) return null;
  if (legacy.must.length + legacy.nice.length + legacy.requirements.length === 0) return null;
  try {
    return await fetchRowsFromLegacy(legacy);
  } catch {
    return null;
  }
}

/** Odczyt modelem trwa kilkanaście–kilkadziesiąt sekund (OCR PDF-a dłużej). */
const READ_TIMEOUT_MS = 120_000;

function readErrorMessage(error: unknown, fallback: string): string {
  const detail = (
    error as { response?: { data?: { detail?: unknown } } } | null | undefined
  )?.response?.data?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const { message, blockers } = detail as {
      message?: unknown;
      blockers?: unknown;
    };
    if (
      typeof message === "string" &&
      Array.isArray(blockers) &&
      blockers.length
    ) {
      return `${message} ${blockers.filter((b) => typeof b === "string").join(" ")}`;
    }
  }
  return apiErrorMessage(error, fallback);
}

/**
 * Stan startowy dla harnessu `/preview/new-job` (dane fikcyjne, zero zapytań).
 * Produkcja nie przekazuje go nigdy.
 */
export interface NewJobPagePreview {
  step: Step;
  client: ClientRef | null;
  /** Kafel źródła w kroku 1; brak = „Wklej treść requestu”. */
  source?: NewJobSource;
  requestText: string;
  form: IntakeForm;
  evidence: string[];
  /** Kategorie do sekcji 6 (strona pyta o nie serwer). */
  categories?: CategoryOption[];
  /** Co serwer wie o wierszach wymagań (strona pyta o to serwer). */
  criticalInfo?: RowCriticalState;
  recruiterId?: number | null;
  /** Jawny wybór w polu „Rekruter prowadzący”; brak = automat, o ile jest dostępny. */
  assignment?: RecruiterAssignment;
  priorityLevel?: PriorityLevel;
  /** Krok „Ogłoszenie na portalach” (widoczny tylko przy gotowym portalu). */
  portalPlan?: NewJobPortalPlan;
  portalFindings?: PublicDraftRead["findings"];
  /** Niedokończone formularze w kroku 1 (strona pyta o nie serwer). */
  unfinishedForms?: IntakeFormListItem[];
  /** Stan autozapisu w stopce. */
  autosave?: AutosaveState;
  /** 422 `job_not_ready` z ostatniej próby utworzenia. */
  serverBlockers?: ServerBlocker[];
}

const EMPTY_PORTAL_PLAN: NewJobPortalPlan = {
  portals: [],
  draft: null,
  options: EMPTY_LISTING_OPTIONS,
};

export function NewJobPage({ preview }: { preview?: NewJobPagePreview } = {}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const [step, setStep] = useState<Step>(preview?.step ?? "request");
  const [client, setClient] = useState<ClientRef | null>(
    preview?.client ?? null,
  );
  const [source, setSource] = useState<NewJobSource>(preview?.source ?? "text");
  const [requestText, setRequestText] = useState(preview?.requestText ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [reading, setReading] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);
  const [form, setForm] = useState<IntakeForm>(
    preview?.form ?? EMPTY_INTAKE_FORM,
  );
  const [evidence, setEvidence] = useState<string[]>(preview?.evidence ?? []);
  const [readByAi, setReadByAi] = useState(preview != null);
  const [templateJobId, setTemplateJobId] = useState<number | null>(null);
  const [recruiterId, setRecruiterId] = useState<number | null>(
    preview?.recruiterId ?? null,
  );
  // Wybór trójstanowy (02.10.2026): `null` = Delivery Lead niczego nie
  // zaznaczył — wtedy osobę proponuje automat, o ile jest dostępny. Wskazany
  // rekruter (podgląd, kliknięcie w listę) to jawne „Wybieram sam”.
  const [assignmentChoice, setAssignmentChoice] =
    useState<RecruiterAssignment | null>(
      preview?.assignment ?? (preview?.recruiterId != null ? "person" : null),
    );
  // Nowa rekrutacja zaczyna od P1 („Pilne”) — zmienia to człowiek.
  const [priorityLevel, setPriorityLevel] = useState<PriorityLevel>(
    preview?.priorityLevel ?? NEW_JOB_PRIORITY_LEVEL,
  );
  const [saving, setSaving] = useState<"create" | "later" | null>(null);
  // 0341: podobne rekrutacje zaznaczone przy tworzeniu — łączone po zapisie.
  const [similarJobIds, setSimilarJobIds] = useState<number[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  // Audyt 06.10.2026 (P9): „Utwórz” bez nazwy od klienta — komunikat przy polu.
  const [clientTitleAttempted, setClientTitleAttempted] = useState(false);
  // 04.10.2026: braki zgłoszone przez serwer przy utworzeniu (422 `job_not_ready`).
  const [serverBlockers, setServerBlockers] = useState<ServerBlocker[] | null>(
    preview?.serverBlockers ?? null,
  );
  // Formularz na koncie autora: id po pierwszym zapisie, stan dla stopki.
  const [intakeFormId, setIntakeFormId] = useState<number | null>(null);
  const [autosave, setAutosave] = useState<AutosaveState>(
    preview?.autosave ?? { status: "idle" },
  );
  const [busyFormId, setBusyFormId] = useState<number | null>(null);
  // Ogłoszenie na RocketJobs / JustJoin.IT — publikowane PO rekrutacji.
  const [portalPlan, setPortalPlan] = useState<NewJobPortalPlan>(
    preview?.portalPlan ?? EMPTY_PORTAL_PLAN,
  );
  const [portalFindings, setPortalFindings] = useState<PublicDraftRead["findings"]>(
    preview?.portalFindings ?? [],
  );
  const [preparingAd, setPreparingAd] = useState(false);
  const [prepareAdError, setPrepareAdError] = useState<string | null>(null);

  // „Skopiuj jako template” z historii requestów: `?from=<id>` otwiera od
  // razu krok 2 z danymi rekrutacji-źródła i tym samym klientem.
  const fromParam = searchParams?.get("from") ?? null;
  useEffect(() => {
    const fromId = fromParam ? Number(fromParam) : NaN;
    if (!Number.isInteger(fromId) || fromId <= 0) return;
    let cancelled = false;
    loadTemplateSource<
      TemplateSourceJob & { client?: { id: number; name: string } | null }
    >(api.get, fromId)
      .then(async (data) => ({ data, rows: await templateRows(data) }))
      .then(({ data, rows }) => {
        if (cancelled) return;
        if (data.client_id != null) {
          setClient({
            id: data.client_id,
            name: data.client?.name ?? "",
          } as ClientRef);
        }
        setForm(applyTemplate({ ...EMPTY_INTAKE_FORM }, data, rows));
        setRequestText(data.description ?? "");
        setTemplateJobId(fromId);
        setStep("review");
      })
      .catch(() => {
        if (!cancelled)
          setReadError("Nie udało się wczytać rekrutacji-szablonu.");
      });
    return () => {
      cancelled = true;
    };
  }, [fromParam]);

  const recruitersQuery = useQuery({
    queryKey: ["handoff-recruiters"],
    enabled: step === "review",
    queryFn: () =>
      api
        .get("/api/users", {
          params: { roles: ["recruiter"] },
          paramsSerializer: { indexes: null },
        })
        .then((r) => r.data as RecruiterOption[]),
  });

  // Kategoria kompetencji (02.10.2026): system podpowiada ją z nazwy roli,
  // Delivery Lead potwierdza. Zapytanie idzie po chwili ciszy w polu roli;
  // opis i wymagania jadą z chwili zapytania (klasyfikator czyta je tylko,
  // gdy nazwa roli nic nie mówi).
  const categoryInput = useDebouncedValue(
    useMemo(
      () => ({ role: form.title.trim(), clientTitle: form.clientTitle.trim() }),
      [form.title, form.clientTitle],
    ),
    600,
  );
  // Pytamy dopiero o rolę, która stoi w polu: zaraz po odczycie requestu
  // opóźniona wartość to jeszcze puste pole, a podpowiedź dla pustej roli
  // mignęłaby na ekranie i zniknęła, zanim przyjdzie właściwa.
  const categoryInputCurrent =
    categoryInput.role === form.title.trim() &&
    categoryInput.clientTitle === form.clientTitle.trim();
  const categoryQuery = useQuery({
    queryKey: ["job-intake-category-suggestion", categoryInput.role, categoryInput.clientTitle],
    enabled: step === "review" && !preview && categoryInputCurrent,
    staleTime: 5 * 60_000,
    retry: false,
    queryFn: () =>
      api
        .post<CategorySuggestion>("/api/job-intake/category-suggestion", {
          role: categoryInput.role || undefined,
          client_title: categoryInput.clientTitle || undefined,
          description: requestText.trim() || undefined,
          must_skills: mustOf(form),
        })
        .then((r) => r.data),
  });
  const categories = preview?.categories ?? categoryQuery.data?.categories ?? [];
  const suggestedCategory = categoryQuery.data?.suggested_id;
  useEffect(() => {
    if (suggestedCategory === undefined || !categoryInputCurrent) return;
    setForm((f) => {
      // Potwierdzonej kategorii podpowiedź już nie zmienia.
      const chosen = f.categoryConfirmed ? f.competenceCategoryId : suggestedCategory;
      if (f.suggestedCategoryId === suggestedCategory && f.competenceCategoryId === chosen)
        return f;
      return { ...f, suggestedCategoryId: suggestedCategory, competenceCategoryId: chosen };
    });
    // `form.suggestedCategoryId`: ponowny odczyt requestu zakłada formularz od
    // nowa (podpowiedź wraca do `null`), a odpowiedź serwera dla tej samej roli
    // się nie zmienia — bez tej zależności kategoria nie byłaby podpowiedziana.
  }, [suggestedCategory, categoryInputCurrent, form.suggestedCategoryId]);

  // Czy da się wybrać automat — ta sama flaga co w handoffie.
  // Tryb „off” znaczy, że automat nikogo nie zaproponuje, więc też wyłączone.
  const handoffOptionsQuery = useQuery({
    queryKey: ["job-intake-handoff-options"],
    enabled: step === "review",
    retry: false,
    queryFn: () =>
      api
        .get("/api/job-intake/handoff-options")
        .then((r) => r.data as HandoffOptions),
  });
  const allocationMode = handoffOptionsQuery.data?.mode;
  const automaticAvailable = automaticAssignmentAvailable(
    handoffOptionsQuery.data?.automatic_enabled,
    allocationMode,
  );
  const assignment = resolveRecruiterAssignment(assignmentChoice, automaticAvailable);
  const automatic = assignment === "automatic";
  const automaticOffNotice = handoffOptionsQuery.isSuccess && !automaticAvailable;
  // „Przyjmujemy kandydatów”: automat takim requestom nikogo nie proponuje.
  const passive = priorityLevel === "accepting";

  // Portale wyłączone flagami (produkcja dziś) = `any_ready: false` → sekcji nie ma.
  const portalConfigQuery = useQuery({
    queryKey: jobPortalKeys.config,
    queryFn: fetchPortalConfig,
    enabled: step === "review",
    staleTime: 5 * 60_000,
  });
  const portalsReady =
    portalConfigQuery.isSuccess && portalConfigQuery.data.any_ready;
  const availablePortals = portalsReady ? readyPortals(portalConfigQuery.data) : [];
  // Zaznaczone portale, których konfiguracja już nie zgłasza, nie idą dalej.
  const activePortalPlan: NewJobPortalPlan = {
    ...portalPlan,
    portals: portalPlan.portals.filter((p) =>
      availablePortals.some((item) => item.portal === p),
    ),
  };
  const portalBlocker = portalPlanBlocker(activePortalPlan);

  const prepareAd = async () => {
    setPreparingAd(true);
    setPrepareAdError(null);
    try {
      const draft = await fetchPublicDraft(
        publicDraftRequest(form, { clientId: client?.id ?? null, requestText }),
      );
      setPortalPlan((plan) => ({
        ...plan,
        draft: {
          publicTitle: draft.public_title,
          subtitle: draft.subtitle,
          about: draft.about,
        },
        // Parametry z pól rekrutacji tylko za pierwszym razem — potem są DL-a.
        options: plan.draft ? plan.options : listingDefaultsFromForm(form),
      }));
      setPortalFindings(draft.findings);
    } catch (e) {
      setPrepareAdError(
        apiErrorMessage(e, "Nie udało się przygotować ogłoszenia — spróbuj ponownie."),
      );
    } finally {
      setPreparingAd(false);
    }
  };

  // Krytyczne (30.09.2026): które wiersze wolno oznaczyć i podpowiedź
  // z historii — dla bieżącej listy. Harness podaje gotowe dane.
  const liveCriticalInfo = useRowCriticalInfo(form.rows, form.title, {
    enabled: !preview && step === "review",
  });
  const criticalInfo = preview?.criticalInfo ?? liveCriticalInfo;
  const missing = useMemo(
    () => missingFor(form, { criticalInfo: criticalInfo.info }),
    [form, criticalInfo.info],
  );
  const segments = useMemo(
    () => highlightSegments(requestText, evidence),
    [requestText, evidence],
  );

  const onRead = async () => {
    if (!client) return;
    setReading(true);
    setReadError(null);
    try {
      let data: { text: string; intake: RequestIntakeResponse };
      if (file) {
        const body = new FormData();
        body.append("client_id", String(client.id));
        body.append("file", file);
        data = (
          await api.post("/api/job-intake/read-file", body, {
            headers: { "Content-Type": "multipart/form-data" },
            timeout: READ_TIMEOUT_MS,
          })
        ).data;
      } else {
        data = (
          await api.post(
            "/api/job-intake/read",
            {
              client_id: client.id,
              text: requestText,
            },
            { timeout: READ_TIMEOUT_MS },
          )
        ).data;
      }
      setRequestText(data.text);
      setFile(null);
      setForm(formFromIntake(data.intake));
      setEvidence(data.intake.evidence ?? []);
      setReadByAi(true);
      setStep("review");
    } catch (e) {
      setReadError(
        readErrorMessage(
          e,
          "Nie udało się odczytać requestu — spróbuj ponownie albo wypełnij ręcznie.",
        ),
      );
    } finally {
      setReading(false);
    }
  };

  const onManual = () => {
    // Powrót do kroku 1 i ponowne „Przejdź do formularza” nie kasuje wpisanych pól.
    if (readByAi) setForm({ ...EMPTY_INTAKE_FORM });
    setEvidence([]);
    setReadByAi(false);
    setStep("review");
  };

  const applyTemplateFromJob = async (jobId: number) => {
    try {
      const data = await loadTemplateSource(api.get, jobId);
      const rows = await templateRows(data);
      setForm((f) => applyTemplate(f, data, rows));
      setTemplateJobId(jobId);
    } catch (e) {
      showError(
        apiErrorMessage(e, "Nie udało się wczytać podobnej rekrutacji."),
      );
    }
  };

  // Nowa rekrutacja, jej priorytet i obsada zmieniają też liczniki listy,
  // pulpit „Requesty i obłożenie” i „Czeka na Ciebie” — stąd wspólne odświeżenie.
  const invalidateJobs = (jobId: number) => {
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    invalidateJobTeam(queryClient, jobId);
  };

  // ── Formularz na koncie autora (04.10.2026) ──────────────────────────────
  // Stan zapisu bez listy braków: podpowiedzi krytycznych doczytują się same
  // i nie mogą wyzwalać zapisu, którego nikt nie zrobił.
  const formState = useMemo(
    () => ({
      version: 1 as const,
      step,
      form,
      evidence,
      readByAi,
      templateJobId,
      recruiterId,
      assignment: assignmentChoice,
      priorityLevel,
      similarJobIds,
    }),
    [
      step,
      form,
      evidence,
      readByAi,
      templateJobId,
      recruiterId,
      assignmentChoice,
      priorityLevel,
      similarJobIds,
    ],
  );
  const snapshot = useMemo(
    () => JSON.stringify({ client: client?.id ?? null, source, requestText, formState }),
    [client, source, requestText, formState],
  );
  const formBody: IntakeFormWrite | null = client
    ? {
        label: intakeFormLabel(form),
        client_id: client.id,
        source,
        request_text: requestText,
        form: { ...formState, missing } satisfies IntakeFormState,
      }
    : null;
  const latestRef = useRef<{ body: IntakeFormWrite | null; snapshot: string }>({
    body: formBody,
    snapshot,
  });
  latestRef.current = { body: formBody, snapshot };
  const formIdRef = useRef<number | null>(null);
  const lastSavedRef = useRef<string | null>(null);
  const inflightRef = useRef<Promise<boolean> | null>(null);
  // Po udanym utworzeniu serwer kasuje formularz — kolejny zapis by go wskrzesił.
  const stoppedRef = useRef(false);
  // Audyt 06.10.2026 (N7): od „Utwórz” do końca `POST /api/jobs` autozapis
  // stoi — serwer kasuje formularz w tej samej transakcji, a zapis w trakcie
  // (np. przy ukryciu karty) zakładałby nowy.
  const creatingRef = useRef(false);
  const markCleanRef = useRef(false);
  const canAutosave =
    !preview && client != null && (step === "review" || requestText.trim() !== "");

  const persistForm = useCallback(async (): Promise<boolean> => {
    while (inflightRef.current) await inflightRef.current;
    if (stoppedRef.current || creatingRef.current) return false;
    const { body, snapshot: snap } = latestRef.current;
    if (!body) return false;
    const run = (async () => {
      setAutosave({ status: "saving" });
      try {
        const saved = await saveIntakeForm(formIdRef.current, body);
        formIdRef.current = saved?.id ?? formIdRef.current;
        setIntakeFormId(formIdRef.current);
        lastSavedRef.current = snap;
        setAutosave({ status: "saved", at: saved?.updated_at ?? new Date().toISOString() });
        void queryClient.invalidateQueries({ queryKey: jobIntakeFormKeys.list });
        return true;
      } catch (e) {
        setAutosave({
          status: "error",
          message: isFormsLimitError(e)
            ? FORMS_LIMIT_TEXT
            : apiErrorMessage(
                e,
                "Formularz nie zapisał się — spróbuję ponownie przy następnej zmianie.",
              ),
        });
        return false;
      }
    })();
    inflightRef.current = run;
    try {
      return await run;
    } finally {
      inflightRef.current = null;
    }
  }, [queryClient]);

  // Wczytany formularz jest już zapisany — bez tego autozapis od razu by go powtórzył.
  useEffect(() => {
    if (!markCleanRef.current) return;
    markCleanRef.current = false;
    lastSavedRef.current = snapshot;
  }, [snapshot]);

  const debouncedSnapshot = useDebouncedValue(snapshot, AUTOSAVE_DELAY_MS);
  useEffect(() => {
    if (!canAutosave || saving != null) return;
    if (debouncedSnapshot !== snapshot) return;
    if (debouncedSnapshot === lastSavedRef.current) return;
    void persistForm();
  }, [debouncedSnapshot, snapshot, canAutosave, saving, persistForm]);

  const unfinishedQuery = useQuery({
    queryKey: jobIntakeFormKeys.list,
    queryFn: fetchIntakeForms,
    enabled: !preview && step === "request",
    staleTime: 30_000,
  });
  const unfinishedForms = (preview?.unfinishedForms ?? unfinishedQuery.data ?? []).filter(
    (item) => item.id !== intakeFormId,
  );

  const applySavedForm = useCallback((data: IntakeFormRead) => {
    const state = (data.form && typeof data.form === "object"
      ? data.form
      : {}) as Partial<IntakeFormState>;
    formIdRef.current = data.id;
    setIntakeFormId(data.id);
    setClient(
      data.client_id != null
        ? ({ id: data.client_id, name: data.client_name ?? "" } as ClientRef)
        : null,
    );
    const savedSource = SOURCES.find((value) => value === data.source) ?? "text";
    // Plik nie wraca (zapisujemy jego odczytaną treść) — krok 1 pokazuje tekst.
    setSource(savedSource === "file" && state.step !== "review" ? "text" : savedSource);
    setRequestText(data.request_text ?? "");
    setFile(null);
    setForm(restoreIntakeForm(state.form));
    setEvidence(Array.isArray(state.evidence) ? state.evidence : []);
    setReadByAi(state.readByAi === true);
    setTemplateJobId(typeof state.templateJobId === "number" ? state.templateJobId : null);
    setRecruiterId(typeof state.recruiterId === "number" ? state.recruiterId : null);
    setAssignmentChoice(state.assignment ?? null);
    if (state.priorityLevel) setPriorityLevel(state.priorityLevel);
    setSimilarJobIds(Array.isArray(state.similarJobIds) ? state.similarJobIds : []);
    // Szkic ogłoszenia nie należy do zapisanego formularza — inaczej wznowiony
    // formularz B opublikowałby ogłoszenie przygotowane dla formularza A.
    setPortalPlan(EMPTY_PORTAL_PLAN);
    setPortalFindings([]);
    setServerBlockers(null);
    setSaveError(null);
    setReadError(null);
    setStep(state.step === "review" ? "review" : "request");
    setAutosave({ status: "saved", at: data.updated_at });
    markCleanRef.current = true;
  }, []);

  // Zmiany sprzed końca odliczania autozapisu nie mogą przepaść — przy
  // wyjściu ze strony, ukryciu karty i przejściu do innego formularza.
  const canAutosaveRef = useRef(canAutosave);
  canAutosaveRef.current = canAutosave;
  const flushPending = useCallback(async (): Promise<void> => {
    if (!canAutosaveRef.current || stoppedRef.current || creatingRef.current) return;
    if (latestRef.current.snapshot === lastSavedRef.current) return;
    await persistForm();
  }, [persistForm]);
  useEffect(() => {
    const onHidden = () => {
      if (document.visibilityState === "hidden") void flushPending();
    };
    document.addEventListener("visibilitychange", onHidden);
    return () => {
      document.removeEventListener("visibilitychange", onHidden);
      void flushPending();
    };
  }, [flushPending]);

  const resumeForm = useCallback(
    async (id: number) => {
      setBusyFormId(id);
      try {
        // Najpierw dokończ zapis bieżącego formularza: odpowiedź zapisu w locie
        // nadpisałaby identyfikator wznawianego formularza.
        await flushPending();
        while (inflightRef.current) await inflightRef.current;
        applySavedForm(await fetchIntakeForm(id));
      } catch (e) {
        showError(apiErrorMessage(e, "Nie udało się wczytać formularza."));
      } finally {
        setBusyFormId(null);
      }
    },
    [applySavedForm, flushPending, showError],
  );

  const removeForm = async (id: number) => {
    setBusyFormId(id);
    try {
      await deleteIntakeForm(id);
      await queryClient.invalidateQueries({ queryKey: jobIntakeFormKeys.list });
      showSuccess("Formularz usunięty.");
    } catch (e) {
      showError(apiErrorMessage(e, "Nie udało się usunąć formularza."));
    } finally {
      setBusyFormId(null);
    }
  };

  // „Dokończ” z pulpitu albo z linku: `?form=<id>` wczytuje formularz od razu.
  const formParam = searchParams?.get("form") ?? null;
  useEffect(() => {
    const id = formParam ? Number(formParam) : NaN;
    if (preview || !Number.isInteger(id) || id <= 0) return;
    void resumeForm(id);
  }, [formParam, preview, resumeForm]);

  const saveForLater = async () => {
    if (!client) return;
    setSaving("later");
    const ok = await persistForm();
    setSaving(null);
    if (!ok) return;
    showSuccess("Formularz zapisany. Dokończysz go w „Nowa rekrutacja”.");
    router.push("/jobs");
  };

  const create = async () => {
    if (!client) return;
    if (!form.title.trim()) {
      setSaveError("Wpisz rolę — bez niej nie da się utworzyć rekrutacji.");
      return;
    }
    if (!jobTitleFor(form)) {
      setClientTitleAttempted(true);
      document
        .getElementById(sectionAnchor("name"))
        ?.scrollIntoView?.({ behavior: "smooth", block: "start" });
      return;
    }
    setSaving("create");
    setSaveError(null);
    setServerBlockers(null);
    // Trwający autozapis kończy się przed utworzeniem — id formularza musi być aktualne.
    while (inflightRef.current) await inflightRef.current;
    creatingRef.current = true;
    const handoff: CreateHandoff = automatic
      ? { assignment_mode: "automatic", channel: "linkedin" }
      : { recruiter_id: recruiterId as number, channel: "linkedin" };
    let jobId: number;
    try {
      const { data } = await api.post<{ id: number }>(
        "/api/jobs",
        buildCreateJobPayload(form, {
          clientId: client.id,
          requestText,
          templateJobId,
          // Kolumna ma cztery wartości, ekran mówi trzema poziomami.
          priority: rawPriorityForLevel(priorityLevel),
          handoff,
          similarJobIds,
          intakeFormId: formIdRef.current,
        }),
      );
      jobId = data.id;
    } catch (e) {
      const blockers = serverBlockersFromError(e);
      if (blockers && blockers.length > 0) setServerBlockers(blockers);
      else setSaveError(readErrorMessage(e, "Nie udało się utworzyć rekrutacji."));
      setSaving(null);
      // Nic nie powstało — autozapis wraca, a formularz zostaje na koncie
      // z ostatnimi zmianami.
      creatingRef.current = false;
      void persistForm();
      return;
    }
    stoppedRef.current = true;
    creatingRef.current = false;
    void queryClient.invalidateQueries({ queryKey: jobIntakeFormKeys.list });
    invalidateJobs(jobId);
    // „Z historii klienta” (sekcja 8) — Luna podsumowuje w tle, co klient
    // odrzucał i o co pytał. Bez `await`: tworzenie rekrutacji na to nie
    // czeka, a awaria to tylko brak bloku (odświeżysz go w profilu).
    const createdJobId = jobId;
    void Promise.resolve()
      .then(() => championApi.refreshClientHistory(createdJobId))
      .then(() =>
        queryClient.invalidateQueries({ queryKey: ["champion-profile", createdJobId] }),
      )
      .catch(() => undefined);
    const portalsTab = `/jobs/${jobId}?tab=portals`;
    if (activePortalPlan.portals.length > 0) {
      const labels = Object.fromEntries(
        availablePortals.map((item) => [item.portal, item.label]),
      );
      const outcome = await publishNewJobToPortals(jobId, activePortalPlan, labels);
      if (!outcome.ok) {
        // Rekrutacja zostaje — w oknie zlecenia da się dokończyć publikację.
        showError(
          `Rekrutacja utworzona, ale ogłoszenie nie wyszło: ${outcome.message}. Dokończ w oknie zlecenia („Portale ogłoszeniowe”).`,
        );
        router.push(portalsTab);
        return;
      }
      showSuccess(
        `Rekrutacja utworzona i opublikowana. Ogłoszenie w kolejce: ${outcome.published
          .map((p) => labels[p] ?? p)
          .join(", ")}.`,
      );
      router.push(`/jobs/${jobId}`);
      return;
    }
    showSuccess(
      automatic
        ? `Rekrutacja utworzona i opublikowana. ${automaticHandoffOutcome(allocationMode, passive)}`
        : "Rekrutacja utworzona i opublikowana.",
    );
    router.push(`/jobs/${jobId}`);
  };

  // Tożsamość listy must zmienia się tylko z wierszami — podpowiedź podobnych
  // rekrutacji czeka na ciszę i nie pyta serwera przy każdej edycji pola obok.
  const similarMust = useMemo(() => mustOf(form), [form.rows]); // eslint-disable-line react-hooks/exhaustive-deps
  const onSimilarChange = useCallback((ids: number[]) => setSimilarJobIds(ids), []);
  // Po odczycie przez AI i przy szablonie braki są podświetlane w polach;
  // przy ręcznym wpisywaniu mówi o nich pasek sekcji i stopka.
  const highlightMissing = readByAi || templateJobId != null;
  const ready = missing.length === 0;
  const hasRecruiter = automatic || recruiterId != null;
  // Krytyczne: dopóki serwer nie powiedział, które wiersze to technologie,
  // nie wiadomo, czy decyzja jest potrzebna — przycisk czeka.
  const criticalPending =
    !preview && criticalInfo.info == null && !criticalInfo.isError;
  const canHandoff =
    ready && hasRecruiter && saving == null && portalBlocker == null && !criticalPending;
  const autosaveText = autosaveLabel(autosave);
  const formIsSaved = autosave.status === "saved";
  const recruiters = recruitersQuery.data ?? [];

  return (
    <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-6 md:px-2 md:pt-2">
      <PageHeader
        title="Nowa rekrutacja"
        description={
          step === "request"
            ? "Wybierz klienta i sposób, w jaki chcesz wypełnić rekrutację."
            : "Sprawdź, co trafiło do pól, i opublikuj rekrutację."
        }
        breadcrumb={[
          { label: "Rekrutacje", href: "/jobs" },
          { label: "Nowa rekrutacja" },
        ]}
        actions={<StepPills step={step} />}
      />

      {step === "request" ? (
        <NewJobSourceStep
          client={client}
          onClientChange={(next) => {
            // Hiring manager to osoba z firmy klienta — inny klient, inna osoba.
            if (next?.id !== client?.id) {
              setForm((f) => ({ ...f, hiringManager: null, hiringManagerNotProvided: false }));
            }
            setClient(next);
          }}
          source={source}
          onSourceChange={(next) => {
            setSource(next);
            setReadError(null);
          }}
          text={requestText}
          onTextChange={setRequestText}
          file={file}
          onFileChange={setFile}
          reading={reading}
          error={readError}
          onRead={onRead}
          onManual={onManual}
          unfinished={
            <UnfinishedIntakeForms
              items={unfinishedForms}
              busyId={busyFormId}
              onResume={(id) => void resumeForm(id)}
              onDelete={(id) => void removeForm(id)}
            />
          }
        />
      ) : (
        // `minmax(0,1fr)` także w jednej kolumnie: przewijany pasek sekcji
        // rozpychałby inaczej stronę na telefonie do szerokości swoich pozycji.
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-foreground">
                Request od klienta{client?.name ? ` · ${client.name}` : ""}
              </h2>
              <button
                type="button"
                className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
                onClick={() => setStep("request")}
              >
                <ArrowLeft className="h-3.5 w-3.5" /> Zmień źródło
              </button>
            </div>
            {requestText.trim() ? (
              <div className="max-h-[35dvh] overflow-auto whitespace-pre-line rounded-xl border border-border bg-card p-4 sm:p-5 xl:max-h-[70dvh] text-sm leading-relaxed text-foreground/80">
                {segments.map((seg, i) =>
                  seg.mark ? (
                    <mark
                      key={i}
                      className="rounded bg-primary/15 px-0.5 text-foreground"
                    >
                      {seg.text}
                    </mark>
                  ) : (
                    <span key={i}>{seg.text}</span>
                  ),
                )}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-border p-5 text-sm text-muted-foreground">
                Wypełniasz ręcznie — bez requestu.
              </div>
            )}
            {evidence.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Podświetlone fragmenty trafiły do pól formularza.
              </p>
            )}
            {!preview && (
              <SimilarRequestsBanner
                clientId={client?.id ?? null}
                title={form.title}
                description={requestText}
                templateJobId={templateJobId}
                onUseAsTemplate={applyTemplateFromJob}
              />
            )}
          </section>

          <div className="flex flex-col gap-4">
            <NewJobSectionNav missing={missing} />
            <NewJobReviewForm
              form={form}
              onChange={setForm}
              missing={missing}
              highlightMissing={highlightMissing}
              clientId={client?.id ?? null}
              countEnabled={!preview}
              criticalInfo={criticalInfo}
              clientTitleError={
                clientTitleAttempted && !jobTitleFor(form) ? CLIENT_TITLE_REQUIRED_TEXT : null
              }
              team={
                <NewJobTeamStep
                  categories={categories}
                  categoriesLoading={!preview && categoryQuery.isPending}
                  categoriesFailed={!preview && categoryQuery.isError && !categoryQuery.data}
                  onCategoriesRetry={() => void categoryQuery.refetch()}
                  categoryId={form.competenceCategoryId}
                  suggestedCategoryId={form.suggestedCategoryId}
                  categoryConfirmed={form.categoryConfirmed}
                  onCategoryChange={(id, confirmed) =>
                    setForm((f) => ({
                      ...f,
                      competenceCategoryId: id,
                      categoryConfirmed: confirmed,
                    }))
                  }
                  categoryMissing={highlightMissing && missing.includes("category")}
                  assignment={assignment}
                  onAssignmentChange={setAssignmentChoice}
                  automaticAvailable={automaticAvailable}
                  automaticOff={automaticOffNotice}
                  mode={allocationMode}
                  recruiters={recruiters}
                  recruitersFailed={recruitersQuery.isError && !recruitersQuery.data}
                  onRecruitersRetry={() => void recruitersQuery.refetch()}
                  recruiterId={recruiterId}
                  onRecruiterChange={(id) => {
                    setRecruiterId(id);
                    // Wskazanie osoby to jawny wybór „Wskażę sam”.
                    if (id != null) setAssignmentChoice("person");
                  }}
                  priorityLevel={priorityLevel}
                  onPriorityChange={setPriorityLevel}
                  disabled={saving != null}
                />
              }
            />
            {!preview && (
              <SimilarJobsPicker
                title={form.title}
                must={similarMust}
                clientId={client?.id ?? null}
                onChange={onSimilarChange}
                initialSelected={similarJobIds}
              />
            )}
            {!preview && <ClientAskedBeforeHint clientId={client?.id ?? null} />}
            {portalsReady && availablePortals.length > 0 && (
              <NewJobPortalsStep
                portals={availablePortals}
                plan={activePortalPlan}
                onPlanChange={setPortalPlan}
                findings={portalFindings}
                preparing={preparingAd}
                prepareError={prepareAdError}
                onPrepare={prepareAd}
                disabled={saving != null}
              />
            )}
          </div>
        </div>
      )}

      {step === "review" && (
        <footer className="sticky bottom-0 z-20 mt-2 -mx-4 border-t [@media(max-height:600px)]:static border-border bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80 md:-mx-8">
          <div className="flex flex-wrap items-center justify-between gap-4 px-4 py-4 md:px-8">
            <div className="flex min-w-0 items-center gap-3">
              <span
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-bold",
                  ready
                    ? "bg-success-muted text-success-muted-foreground"
                    : "bg-warning-muted text-warning-muted-foreground",
                )}
                aria-hidden="true"
              >
                {ready ? <Check className="h-4 w-4" /> : missing.length}
              </span>
              <div className="flex min-w-0 flex-col" aria-live="polite">
                <span className="text-sm font-semibold text-foreground">
                  {ready
                    ? "Gotowa do publikacji"
                    : missingHeadline(missing.length)}
                </span>
                <span className="text-xs text-muted-foreground">
                  {!ready
                    ? missing.map((code, index) => (
                        <span key={code}>
                          {index > 0 ? " · " : null}
                          <a
                            href={`#${sectionAnchor(MISSING_SECTION[code])}`}
                            className="underline-offset-2 hover:text-foreground hover:underline"
                          >
                            {MISSING_LABEL[code]}
                          </a>
                        </span>
                      ))
                    : !hasRecruiter
                      ? "Wybierz rekrutera prowadzącego w sekcji „Kategoria i zespół” — wtedy opublikujesz rekrutację."
                      : portalBlocker
                        ? `Ogłoszenie na portalach: ${portalBlocker}`
                        : automatic
                          ? automaticHandoffOutcome(allocationMode, passive)
                          : "Uczestnikami zostaną wszyscy z potwierdzonej kategorii."}
                </span>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {saveError && (
                <span
                  role="alert"
                  className="max-w-md text-xs text-destructive"
                >
                  {saveError}
                </span>
              )}
              {autosaveText && (
                <span
                  className={cn(
                    "max-w-xs text-xs",
                    autosave.status === "error"
                      ? "text-warning-muted-foreground"
                      : "text-muted-foreground",
                  )}
                  data-testid="new-job-autosave"
                >
                  {autosaveText}
                </span>
              )}
              {/* Kategoria, prowadzący i priorytet mają własną sekcję
                  (`NewJobTeamStep`) — tu zostają tylko przyciski, żeby
                  przyklejona stopka nie zabierała laptopowi jednej trzeciej okna. */}
              <Button
                type="button"
                variant="outline"
                onClick={() => void saveForLater()}
                disabled={saving != null || client == null || preview != null}
                loading={saving === "later"}
              >
                Dokończę później
              </Button>
              <Button
                type="button"
                onClick={() => void create()}
                disabled={!canHandoff}
                loading={saving === "create"}
                title={
                  !ready
                    ? "Uzupełnij braki, żeby opublikować rekrutację"
                    : !hasRecruiter
                      ? automaticAvailable
                        ? "Wybierz rekrutera prowadzącego albo zostaw to automatowi"
                        : "Wybierz rekrutera prowadzącego, żeby opublikować rekrutację"
                      : portalBlocker
                        ? `Ogłoszenie na portalach: ${portalBlocker}`
                        : criticalPending
                          ? "Sprawdzam umiejętności krytyczne…"
                          : undefined
                }
              >
                Utwórz i opublikuj
              </Button>
            </div>
          </div>
          {serverBlockers && serverBlockers.length > 0 && (
            <div
              role="alert"
              data-testid="new-job-server-blockers"
              className="border-t border-border px-4 py-3 md:px-8"
            >
              <p className="text-sm font-semibold text-foreground">
                {serverBlockersHeadline(serverBlockers.length)}
              </p>
              <ul className="mt-1 flex flex-col gap-0.5 text-xs text-foreground">
                {serverBlockers.map((blocker, index) => {
                  const section = serverBlockerSection(blocker.code);
                  return (
                    <li key={`${blocker.code}-${index}`}>
                      {section ? (
                        <a
                          href={`#${sectionAnchor(section)}`}
                          className="underline underline-offset-2 hover:text-primary"
                        >
                          {blocker.message}
                        </a>
                      ) : (
                        blocker.message
                      )}
                    </li>
                  );
                })}
              </ul>
              <p className="mt-1 text-xs text-muted-foreground">
                {formIsSaved
                  ? "Formularz jest zapisany, nic nie przepadło."
                  : "Zapisuję formularz na Twoim koncie — nic nie przepadnie."}
              </p>
            </div>
          )}
        </footer>
      )}
    </div>
  );
}

function StepPills({ step }: { step: Step }) {
  return (
    <ol className="flex items-center gap-2" aria-label="Kroki">
      <li
        aria-current={step === "request" ? "step" : undefined}
        className={cn(
          "rounded-full px-3 py-1 text-xs font-medium",
          step === "request"
            ? "bg-primary text-primary-foreground"
            : "border border-border bg-card text-muted-foreground",
        )}
      >
        1 · Źródło
      </li>
      <li aria-hidden="true" className="h-px w-6 bg-border" />
      <li
        aria-current={step === "review" ? "step" : undefined}
        className={cn(
          "rounded-full px-3 py-1 text-xs font-medium",
          step === "review"
            ? "bg-primary text-primary-foreground"
            : "border border-border bg-card text-muted-foreground",
        )}
      >
        2 · Sprawdź i opublikuj
      </li>
    </ol>
  );
}
