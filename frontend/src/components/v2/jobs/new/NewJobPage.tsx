"use client";

/**
 * Strona `/jobs/new` — nowa rekrutacja z requestu klienta (22.09.2026).
 *
 * Zastępuje okno „Dodaj rekrutację” (9 pól) + ręczne wypełnianie Championa +
 * dok gotowości. Decyzje Artura: tworzenie przenosimy do NEXUSA, start od
 * maila klienta, AI wypełnia minimum, DL sprawdza i jednym kliknięciem
 * „Utwórz i przekaż do searchu”. Pola spoza minimum (TAC, szablon procesu,
 * kategoria, Program/Train, priorytet, typ, widełki mies.) nie istnieją ani
 * tu, ani w ustawieniach rekrutacji — ustawia je backend.
 *
 * Zapis idzie ZWYKŁYMI trasami (`POST /api/jobs` → `PUT …/champion-profile`
 * → `POST …/handoff` → `POST …/publish`), więc wszystkie bramki uprawnień
 * i gotowości zostają tam, gdzie były. Awaria po utworzeniu rekrutacji nie
 * gubi pracy: ląduje w zakładce Championa z komunikatem, co zostało do zrobienia.
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check } from "lucide-react";

import api, { championApi, jobsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ds/PageHeader";
import type { ClientRef } from "@/components/clients/ClientSinglePicker";
import { SimilarRequestsBanner } from "@/components/v2/jobs/SimilarRequestsBanner";
import {
  EMPTY_INTAKE_FORM,
  MISSING_LABEL,
  applyTemplate,
  buildChampionPayload,
  buildJobPayload,
  formFromIntake,
  highlightSegments,
  missingFor,
  missingHeadline,
  type IntakeForm,
  type RequestIntakeResponse,
  type TemplateSourceJob,
} from "@/lib/job-request-intake";
import { cn } from "@/lib/utils";
import { NewJobRequestStep } from "./NewJobRequestStep";
import { NewJobReviewForm } from "./NewJobReviewForm";
import { SimilarJobsPicker } from "./SimilarJobsPicker";
import { ClientAskedBeforeHint } from "./ClientAskedBeforeHint";
import { plural } from "@/components/v2/jobs/SimilarJobsDialog";
import { similarJobsApi } from "@/lib/similar-jobs-api";
import { saveHiringManager } from "@/lib/hiring-manager";
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

interface RecruiterOption {
  id: number;
  name?: string | null;
  email?: string | null;
}

export type Step = "request" | "review";

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
  requestText: string;
  form: IntakeForm;
  evidence: string[];
  recruiterId?: number | null;
  /** Krok „Ogłoszenie na portalach” (widoczny tylko przy gotowym portalu). */
  portalPlan?: NewJobPortalPlan;
  portalFindings?: PublicDraftRead["findings"];
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
  const [saving, setSaving] = useState<"handoff" | "draft" | null>(null);
  // 0341: podobne rekrutacje zaznaczone przy tworzeniu — łączone po zapisie.
  const [similarJobIds, setSimilarJobIds] = useState<number[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
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
    api
      .get<
        TemplateSourceJob & { client?: { id: number; name: string } | null }
      >(`/api/jobs/${fromId}`)
      .then(({ data }) => {
        if (cancelled) return;
        if (data.client_id != null) {
          setClient({
            id: data.client_id,
            name: data.client?.name ?? "",
          } as ClientRef);
        }
        setForm(applyTemplate({ ...EMPTY_INTAKE_FORM }, data));
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
          params: { roles: ["recruiter", "tac", "sourcer"] },
          paramsSerializer: { indexes: null },
        })
        .then((r) => r.data as RecruiterOption[]),
  });

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

  const missing = useMemo(() => missingFor(form), [form]);
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

  const onSkipAi = () => {
    setForm({ ...EMPTY_INTAKE_FORM });
    setEvidence([]);
    setReadByAi(false);
    setStep("review");
  };

  const applyTemplateFromJob = async (jobId: number) => {
    try {
      const { data } = await api.get<TemplateSourceJob>(`/api/jobs/${jobId}`);
      setForm((f) => applyTemplate(f, data));
      setTemplateJobId(jobId);
    } catch (e) {
      showError(
        apiErrorMessage(e, "Nie udało się wczytać podobnej rekrutacji."),
      );
    }
  };

  const invalidateJobs = () => {
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
  };

  const save = async (mode: "handoff" | "draft") => {
    if (!client) return;
    if (!form.title.trim()) {
      setSaveError("Wpisz rolę — bez niej nie da się zapisać rekrutacji.");
      return;
    }
    setSaving(mode);
    setSaveError(null);
    let jobId: number | null = null;
    try {
      const { data } = await api.post<{ id: number }>(
        "/api/jobs",
        buildJobPayload(form, {
          clientId: client.id,
          requestText,
          templateJobId,
        }),
      );
      jobId = data.id;
    } catch (e) {
      setSaveError(readErrorMessage(e, "Nie udało się zapisać rekrutacji."));
      setSaving(null);
      return;
    }
    invalidateJobs();
    // Hiring manager: osobna trasa, bo nową osobę zakłada jako kontakt
    // klienta. Dodatek — jego awaria nie cofa rekrutacji (da się go ustawić
    // w oknie zlecenia).
    if (form.hiringManager) {
      try {
        await saveHiringManager(jobId, form.hiringManager);
      } catch (e) {
        showError(
          `Rekrutacja zapisana, ale hiring manager nie: ${apiErrorMessage(e, "błąd")}. Ustaw go w oknie zlecenia.`,
        );
      }
    }
    const championTab = `/jobs/${jobId}?tab=champion`;
    try {
      await api.put(
        `/api/jobs/${jobId}/champion-profile`,
        buildChampionPayload(form),
      );
    } catch (e) {
      showError(
        `Rekrutacja zapisana, ale profil nie: ${readErrorMessage(e, "błąd zapisu")}. Uzupełnij go tutaj.`,
      );
      router.push(championTab);
      return;
    }
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
    // Połączenie z podobnymi rekrutacjami i przepięcie osób wysłanych do
    // klienta. Dodatek — jego awaria nie cofa rekrutacji (da się to zrobić
    // później oknem „Podobne rekrutacje").
    if (similarJobIds.length > 0) {
      try {
        const linked = await similarJobsApi.link(jobId, similarJobIds);
        if (linked.reassigned_now > 0) {
          showSuccess(
            `Przepięto ${linked.reassigned_now} ${plural(linked.reassigned_now)} z podobnych rekrutacji do „Do przejrzenia”.`,
          );
        }
      } catch (e) {
        showError(
          `Rekrutacja zapisana, ale nie połączono podobnych: ${apiErrorMessage(e, "błąd")}. Zrób to w rekrutacji („Podobne rekrutacje”).`,
        );
      }
    }
    if (mode === "draft") {
      showSuccess("Szkic rekrutacji zapisany.");
      router.push(championTab);
      return;
    }
    try {
      await jobsApi.handoff(
        jobId,
        recruiterId as number,
        undefined,
        "linkedin",
      );
    } catch (e) {
      showError(
        `Rekrutacja zapisana jako szkic — nie przekazano do searchu: ${readErrorMessage(e, "błąd")}`,
      );
      router.push(championTab);
      return;
    }
    // REC-04: toast sukcesu WYŁĄCZNIE po udanej publikacji — inaczej obok
    // błędu stał komunikat „utworzona i przekazana”, który mu przeczył.
    let published = true;
    try {
      await api.post(`/api/jobs/${jobId}/publish`);
    } catch (e) {
      published = false;
      showError(
        `Rekrutacja w searchu, ale nie opublikowana: ${apiErrorMessage(e, "błąd")}. Opublikuj ją na stronie rekrutacji.`,
      );
    }
    invalidateJobs();
    const portalsTab = `/jobs/${jobId}?tab=portals`;
    if (activePortalPlan.portals.length > 0) {
      if (!published) {
        showError(
          "Ogłoszeń na portalach nie wysłano — rekrutacja nie jest opublikowana. Opublikuj ją i wyślij ogłoszenia z okna zlecenia.",
        );
        router.push(portalsTab);
        return;
      }
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
        `Rekrutacja utworzona i przekazana do searchu. Ogłoszenie w kolejce: ${outcome.published
          .map((p) => labels[p] ?? p)
          .join(", ")}.`,
      );
      router.push(`/jobs/${jobId}`);
      return;
    }
    if (published) showSuccess("Rekrutacja utworzona i przekazana do searchu.");
    router.push(`/jobs/${jobId}`);
  };

  const ready = missing.length === 0;
  const canHandoff =
    ready && recruiterId != null && saving == null && portalBlocker == null;
  const recruiters = recruitersQuery.data ?? [];

  return (
    <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-6 md:px-2 md:pt-2">
      <PageHeader
        title="Nowa rekrutacja"
        description={
          step === "request"
            ? "Wklej maila od klienta. AI wyciągnie z niego to, czego potrzebuje search — Ty tylko sprawdzasz."
            : "Sprawdź, co trafiło do pól, i przekaż rekrutację do searchu."
        }
        breadcrumb={[
          { label: "Rekrutacje", href: "/jobs" },
          { label: "Nowa rekrutacja" },
        ]}
        actions={<StepPills step={step} />}
      />

      {step === "request" ? (
        <NewJobRequestStep
          client={client}
          onClientChange={(next) => {
            // Hiring manager to osoba z firmy klienta — inny klient, inna osoba.
            if (next?.id !== client?.id) {
              setForm((f) => ({ ...f, hiringManager: null }));
            }
            setClient(next);
          }}
          text={requestText}
          onTextChange={setRequestText}
          file={file}
          onFileChange={setFile}
          reading={reading}
          error={readError}
          onRead={onRead}
          onSkipAi={onSkipAi}
        />
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-foreground">
                Request{client?.name ? ` · ${client.name}` : ""}
              </h2>
              <button
                type="button"
                className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
                onClick={() => setStep("request")}
              >
                <ArrowLeft className="h-3.5 w-3.5" /> Zmień request
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
            <NewJobReviewForm
              form={form}
              onChange={setForm}
              missing={missing}
              highlightMissing={readByAi || templateJobId != null}
              clientId={client?.id ?? null}
            />
            {!preview && (
              <SimilarJobsPicker
                title={form.title}
                must={form.must}
                onChange={setSimilarJobIds}
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
                    ? "Gotowa do searchu"
                    : missingHeadline(missing.length)}
                </span>
                <span className="truncate text-xs text-muted-foreground">
                  {!ready
                    ? missing.map((code) => MISSING_LABEL[code]).join(" · ")
                    : recruiterId == null
                      ? "Wybierz, kto poprowadzi rekrutację — wtedy przekażesz ją do searchu."
                      : portalBlocker
                        ? `Ogłoszenie na portalach: ${portalBlocker}`
                        : "Szablon procesu, kategoria i zespół ustawią się same."}
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
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                Prowadzi
                <select
                  aria-label="Rekruter prowadzący"
                  className="h-10 rounded-lg border border-border bg-card px-3 text-sm text-foreground"
                  value={recruiterId ?? ""}
                  onChange={(e) =>
                    setRecruiterId(
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                >
                  <option value="">Wybierz rekrutera…</option>
                  {recruiters.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name || r.email || `#${r.id}`}
                    </option>
                  ))}
                </select>
              </label>
              <Button
                type="button"
                variant="outline"
                onClick={() => save("draft")}
                disabled={saving != null}
                loading={saving === "draft"}
              >
                Zapisz szkic
              </Button>
              <Button
                type="button"
                onClick={() => save("handoff")}
                disabled={!canHandoff}
                loading={saving === "handoff"}
                title={
                  !ready
                    ? "Uzupełnij braki, żeby przekazać do searchu"
                    : recruiterId == null
                      ? "Wybierz rekrutera, który poprowadzi rekrutację"
                      : portalBlocker
                        ? `Ogłoszenie na portalach: ${portalBlocker}`
                        : undefined
                }
              >
                Utwórz i przekaż do searchu
              </Button>
            </div>
          </div>
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
        1 · Request
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
        2 · Sprawdź i przekaż
      </li>
    </ol>
  );
}
