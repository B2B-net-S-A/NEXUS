"use client";

/**
 * Krótki modal „Dodaj rekrutację" — zastępuje `AddJobModal`
 * (`components/AppShell.tsx`, usunięty w PR 4) w czterech miejscach:
 * `JobsListV2`, `QuickActionsV2`, `RequestHistorySection` (×2, jako
 * „Skopiuj jako template" pod `fromJobId`).
 *
 * Decyzje z przeglądu 17.09.2026 (`docs/…` — plan
 * `zaplanuj-wszystko-modular-fountain.md`, PR 2):
 *  - 9 pól zamiast 22 — reszta (TAC, Delivery Lead, szablon procesu,
 *    kategoria kompetencji, program/train, priorytet, deadline) żyje w doku
 *    „Zespół" na `/jobs/{id}` (PR 3), a nie w tym modalu.
 *  - DL tworzący rekrutację ląduje jako `delivery_lead_id` (backend, PR 1) —
 *    frontend nie wysyła `tac_id`/`delivery_lead_id`/`recruiter_id`.
 *  - Widełki wynagrodzenia renderują się WYŁĄCZNIE, gdy
 *    `canManageRecruitmentBudget(user)` — DL/TCM bez roli admina i tak
 *    dostają 403 po zapisie (`_assert_delivery_lead_finance_write`).
 *  - Zapis ląduje na `/jobs/{id}?tab=champion[&intake=1]` — pusty Pipeline
 *    zmuszał DL-a do ręcznego przełączenia zakładki.
 */

import { useEffect, useId, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Sparkles } from "lucide-react";

import api, {
  aiWriterApi,
  clientTeamApi,
  type ClientTeamResponse,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { useAuthStore } from "@/store/auth";
import { formatRelativeTime } from "@/lib/utils";
import { extractSkills } from "@/lib/job-skills";
import { parseTagInput } from "@/lib/parse-tag-input";
import { REMOTE_POLICY_OPTIONS } from "@/lib/remote-policy";
import { canManageRecruitmentBudget } from "@/lib/job-budget-access";
import { createdJobUrl } from "@/lib/job-create-landing";
import {
  isJobFormEmpty,
  writeJobDraft,
  type JobDraftFormState,
} from "@/lib/job-draft-storage";
import { useJobDraft } from "@/lib/use-job-draft";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ClientSinglePicker,
  type ClientRef,
} from "@/components/clients/ClientSinglePicker";
import { SimilarRequestsBanner } from "@/components/v2/jobs/SimilarRequestsBanner";
import type { RemotePolicy } from "@/types/client-profile";

/**
 * `apiErrorMessage` (`lib/api-error.ts`) tłumaczy `detail.message`, listy
 * błędów walidacji i 429 — ale NIE `detail.reason`, jedyne pole tekstowe w
 * 503 o wyczerpanej miesięcznej kwocie AI (`{feature, reason, used, limit}`,
 * `POST /api/ai/generate-job`). Bez tej gałęzi DL widział ogólny fallback
 * zamiast „Miesięczny limit wyczerpany". Odczyt jest strukturalny
 * (`detail?: unknown` + sprawdzenie typu) — bezpieczny dla strażnika
 * `api-error-detail-guard.test.ts`.
 */
function jobModalErrorMessage(error: unknown, fallback: string): string {
  const detail = (
    error as { response?: { data?: { detail?: unknown } } } | null | undefined
  )?.response?.data?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const { message, reason } = detail as { message?: unknown; reason?: unknown };
    if (
      typeof message !== "string" &&
      typeof reason === "string" &&
      reason.trim()
    ) {
      return reason;
    }
  }
  return apiErrorMessage(error, fallback);
}

interface CreateJobModalProps {
  onClose: () => void;
  onSuccess: (msg: string, job?: { id: number }) => void;
  /**
   * „Skopiuj jako template" (baner podobnych requestów albo zakładka
   * Historia): modal startuje z polami wypełnionymi z source jobu — TYLKO
   * puste pola (opis, must, miasto, tryb, dni, budżet, typ); tytuł i klient
   * zostają do świadomego wpisania.
   */
  fromJobId?: number | null;
}

const SELECT_CLASS =
  "w-full h-10 px-3 py-2 text-sm bg-card text-foreground border border-border rounded-lg transition-colors duration-150 focus:outline-hidden focus:border-primary disabled:bg-[hsl(var(--border))]/30 disabled:cursor-not-allowed disabled:text-muted-foreground";

const EMPTY_FORM: JobDraftFormState = {
  title: "",
  clientId: null,
  clientName: null,
  recruitmentType: "body_leasing",
  description: "",
  mustHaveInput: "",
  location: "",
  remotePolicy: "",
  onsiteDaysPerWeek: "",
  rateBudgetHourly: "",
  salaryMin: "",
  salaryMax: "",
};

/** Pola, które prefill szablonu WOLNO wypełnić — i tylko gdy są puste. */
type TemplateSeedableField =
  | "description"
  | "mustHaveInput"
  | "location"
  | "remotePolicy"
  | "onsiteDaysPerWeek"
  | "rateBudgetHourly"
  | "recruitmentType";

export function CreateJobModal({
  onClose,
  onSuccess,
  fromJobId = null,
}: CreateJobModalProps) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const canEditBudget = canManageRecruitmentBudget(user);

  const [form, setForm] = useState<JobDraftFormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const [aiGenerating, setAiGenerating] = useState(false);
  const [aiError, setAiError] = useState("");
  const [aiSeniority, setAiSeniority] = useState("");
  const [aiDraft, setAiDraft] = useState<{
    description: string;
    source: string;
  } | null>(null);

  const [templateJobId, setTemplateJobId] = useState<number | null>(
    fromJobId ?? null,
  );
  const [templateSource, setTemplateSource] = useState<{
    jobId: number;
    title: string;
  } | null>(null);
  const [templateSeeded, setTemplateSeeded] = useState<
    Set<TemplateSeedableField>
  >(new Set());

  const [confirmClose, setConfirmClose] = useState(false);

  const titleId = useId();
  const descriptionId = useId();
  const mustHaveId = useId();
  const locationId = useId();
  const remotePolicyId = useId();
  const onsiteDaysId = useId();
  const rateBudgetId = useId();
  const salaryMinId = useId();
  const salaryMaxId = useId();
  const recruitmentTypeId = useId();

  // Szkic w localStorage jest wyłączony dla „Skopiuj jako template" — kopia
  // roli nie jest niezapisanym szkicem do przywrócenia między sesjami.
  const draft = useJobDraft({
    userId: user?.id ?? null,
    form,
    enabled: fromJobId == null,
  });

  // Prefill z szablonu — TYLKO puste pola. Tytuł i klient DL wpisuje sam
  // (audyt B40: kopia zamkniętej rekrutacji nie może udawać, że jest nią
  // nadal — status/deadline i tak nie są już w tym formularzu).
  useEffect(() => {
    if (templateJobId == null) return;
    let cancelled = false;
    api
      .get(`/api/jobs/${templateJobId}`)
      .then((r) => {
        if (cancelled) return;
        const src = r.data;
        const seeded = new Set<TemplateSeedableField>();
        setForm((current) => {
          const next = { ...current };
          if (!next.description.trim() && src.description) {
            next.description = src.description;
            seeded.add("description");
          }
          if (!next.mustHaveInput.trim()) {
            const skills = extractSkills(src.must_skills);
            if (skills.length > 0) {
              next.mustHaveInput = skills.join(", ");
              seeded.add("mustHaveInput");
            }
          }
          if (!next.location.trim() && src.location) {
            next.location = src.location;
            seeded.add("location");
          }
          if (!next.remotePolicy && src.remote_policy) {
            next.remotePolicy = src.remote_policy;
            seeded.add("remotePolicy");
          }
          if (
            !next.onsiteDaysPerWeek.trim() &&
            src.onsite_days_per_week != null
          ) {
            next.onsiteDaysPerWeek = String(src.onsite_days_per_week);
            seeded.add("onsiteDaysPerWeek");
          }
          if (!next.rateBudgetHourly.trim() && src.rate_budget_hourly != null) {
            next.rateBudgetHourly = String(src.rate_budget_hourly);
            seeded.add("rateBudgetHourly");
          }
          if (
            next.recruitmentType === EMPTY_FORM.recruitmentType &&
            src.recruitment_type
          ) {
            next.recruitmentType = src.recruitment_type;
            seeded.add("recruitmentType");
          }
          return next;
        });
        setTemplateSeeded(seeded);
        setTemplateSource({ jobId: templateJobId, title: src.title ?? "" });
      })
      .catch(() => {
        // Cichy fallback — DL może wypełnić ręcznie.
      });
    return () => {
      cancelled = true;
    };
  }, [templateJobId]);

  const undoTemplate = () => {
    setForm((current) => {
      const next = { ...current };
      for (const key of templateSeeded) {
        (next as Record<TemplateSeedableField, string>)[key] =
          EMPTY_FORM[key] as string;
      }
      return next;
    });
    setTemplateJobId(null);
    setTemplateSource(null);
    setTemplateSeeded(new Set());
  };

  const { data: clientTeam } = useQuery<ClientTeamResponse>({
    queryKey: ["client-team", form.clientId],
    queryFn: async () => {
      if (form.clientId === null) return { tacs: [], delivery_leads: [] };
      const res = await clientTeamApi.get(form.clientId);
      return res.data;
    },
    enabled: form.clientId !== null,
    staleTime: 30_000,
  });
  const clientTacs = clientTeam?.tacs ?? [];

  const restoreDraft = () => {
    if (!draft.restorable) return;
    setForm(draft.restorable.form);
    draft.acceptRestorable();
  };

  const handleGenerateAI = async () => {
    if (!form.title.trim()) {
      setAiError("Wpisz najpierw tytuł stanowiska");
      return;
    }
    setAiGenerating(true);
    setAiError("");
    try {
      const { data } = await aiWriterApi.generateJob({
        title: form.title,
        client: form.clientName ?? undefined,
        seniority: aiSeniority || undefined,
        skills: parseTagInput(form.mustHaveInput),
        description_hint: form.description || undefined,
      });
      setAiDraft({ description: data.description, source: data.source });
    } catch (e) {
      setAiError(jobModalErrorMessage(e, "Błąd generowania AI"));
    } finally {
      setAiGenerating(false);
    }
  };

  const attemptClose = () => {
    if (!isJobFormEmpty(form)) {
      setConfirmClose(true);
      return;
    }
    onClose();
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!form.title.trim()) {
      setError("Tytuł jest wymagany");
      return;
    }
    // Backend wymaga `client_id` (JobCreate) — bez tej walidacji DL dostawał
    // surowe 422 po angielsku: „client_id: Field required".
    if (form.clientId == null) {
      setError("Wybierz klienta — bez niego nie da się zapisać rekrutacji");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const payload: Record<string, unknown> = {
        title: form.title,
        client_id: form.clientId,
        recruitment_type: form.recruitmentType,
        description: form.description.trim() || undefined,
        must_skills: parseTagInput(form.mustHaveInput),
        location: form.location.trim() || undefined,
        // 0278: puste = "nieznane" (null), nie "hybrid".
        remote_policy: form.remotePolicy || null,
        onsite_days_per_week:
          form.onsiteDaysPerWeek === ""
            ? null
            : Number(form.onsiteDaysPerWeek),
        rate_budget_hourly: form.rateBudgetHourly
          ? Number(form.rateBudgetHourly)
          : undefined,
        auto_suggest_cc: true,
        // „Skopiuj jako template" — backend kopiuje brakujące pola i pinned
        // interview questions (idempotent, same-client champion only).
        from_job_id: templateJobId ?? undefined,
        copy_questions: templateJobId != null ? true : undefined,
      };
      if (canEditBudget) {
        if (form.salaryMin) payload.salary_min = Number(form.salaryMin);
        if (form.salaryMax) payload.salary_max = Number(form.salaryMax);
      }
      const { data: newJob } = await api.post<{ id: number }>(
        "/api/jobs",
        payload,
      );
      draft.clear();
      onSuccess(
        "Rekrutacja utworzona. Uzupełnij Profil Championa, żeby przekazać ją do searchu.",
        newJob?.id ? { id: newJob.id } : undefined,
      );
      onClose();
      if (newJob?.id) {
        router.push(
          createdJobUrl(newJob.id, {
            hasDescription: form.description.trim().length > 0,
          }),
        );
      }
    } catch (err) {
      setError(jobModalErrorMessage(err, "Błąd podczas zapisywania"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) attemptClose();
      }}
    >
      <DialogContent
        size="lg"
        className="max-h-[85vh]"
        onPointerDownOutside={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>Dodaj rekrutację</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="contents">
          <DialogBody className="space-y-4">
            {error && (
              <div
                role="alert"
                className="rounded-lg bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive"
              >
                {error}
              </div>
            )}

            {draft.restorable && (
              <div className="rounded-lg bg-primary/10 border border-primary/20 px-3 py-2 text-xs flex items-center justify-between gap-3 flex-wrap">
                <span>
                  Masz niezapisany szkic z{" "}
                  {formatRelativeTime(draft.restorable.savedAt)}
                </span>
                <span className="flex items-center gap-3 shrink-0">
                  <button
                    type="button"
                    className="underline font-medium"
                    onClick={restoreDraft}
                  >
                    Przywróć szkic
                  </button>
                  <button
                    type="button"
                    className="underline text-muted-foreground"
                    onClick={() => draft.clear()}
                  >
                    Odrzuć
                  </button>
                </span>
              </div>
            )}

            {templateSource && (
              <div className="rounded-lg bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 px-3 py-2 text-xs text-amber-900 dark:text-amber-200 flex items-center justify-between gap-3 flex-wrap">
                <span>
                  Wypełniono z szablonu: {templateSource.title || `#${templateSource.jobId}`}
                </span>
                <button
                  type="button"
                  className="underline shrink-0"
                  onClick={undoTemplate}
                >
                  Cofnij szablon
                </button>
              </div>
            )}

            <FormField label="Tytuł stanowiska" htmlFor={titleId} required>
              <Input
                id={titleId}
                value={form.title}
                onChange={(e) =>
                  setForm((c) => ({ ...c, title: e.target.value }))
                }
                placeholder="Senior Java Developer"
              />
            </FormField>

            <SimilarRequestsBanner
              clientId={form.clientId}
              title={form.title}
              description={form.description}
              templateJobId={templateJobId}
              onUseAsTemplate={(jobId) => setTemplateJobId(jobId)}
            />

            <FormField label="Klient" required>
              <ClientSinglePicker
                value={
                  form.clientId != null
                    ? ({ id: form.clientId, name: form.clientName ?? "" } as ClientRef)
                    : null
                }
                onChange={(client) =>
                  setForm((c) => ({
                    ...c,
                    clientId: client?.id ?? null,
                    clientName: client?.name ?? null,
                  }))
                }
                queryKey="clients-lookup-create-job"
                allowClear
                placeholder="Wybierz klienta…"
              />
              {form.clientId !== null && clientTeam && clientTacs.length === 0 && (
                <p className="text-[11px] text-amber-700 mt-1">
                  ⚠️ Klient nie ma przypisanego TAC-a. Uzupełnij relację w
                  zakładce „Opiekunowie"; bez niej request zostanie zapisany
                  bez ownera TAC.
                </p>
              )}
              {form.clientId !== null && clientTacs.length > 0 && (
                <p className="text-[11px] text-muted-foreground mt-1">
                  Klient ma {clientTacs.length}{" "}
                  {clientTacs.length === 1 ? "TAC-a" : "TAC-ów"} — ownera
                  wskażesz po utworzeniu w doku „Zespół".
                </p>
              )}
            </FormField>

            <FormField label="Typ rekrutacji" htmlFor={recruitmentTypeId}>
              <select
                id={recruitmentTypeId}
                className={SELECT_CLASS}
                value={form.recruitmentType}
                onChange={(e) =>
                  setForm((c) => ({ ...c, recruitmentType: e.target.value }))
                }
              >
                <option value="body_leasing">Body Leasing</option>
                <option value="sales_project">Sprzedaż</option>
                <option value="tender">Przetarg</option>
              </select>
            </FormField>

            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <label
                  htmlFor={descriptionId}
                  className="text-sm font-medium text-foreground"
                >
                  Opis
                </label>
                <span className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleGenerateAI}
                    disabled={aiGenerating || !form.title.trim()}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs bg-linear-to-r from-blue-600 to-violet-600 text-white rounded-md hover:from-blue-700 hover:to-violet-700 disabled:opacity-50 transition-all font-medium"
                  >
                    {aiGenerating ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />{" "}
                        Generuję…
                      </>
                    ) : (
                      <>
                        <Sparkles className="w-3.5 h-3.5" /> Generuj AI
                      </>
                    )}
                  </button>
                  <label className="text-xs text-muted-foreground">
                    Poziom
                    <select
                      aria-label="Poziom stanowiska do szkicu"
                      value={aiSeniority}
                      onChange={(e) => setAiSeniority(e.target.value)}
                      className="ml-1.5 rounded border bg-background p-1 text-xs"
                    >
                      <option value="">Nie podano</option>
                      <option value="junior">Junior</option>
                      <option value="mid">Mid</option>
                      <option value="senior">Senior</option>
                      <option value="lead">Lead</option>
                    </select>
                  </label>
                </span>
              </div>
              <Textarea
                id={descriptionId}
                value={form.description}
                onChange={(e) =>
                  setForm((c) => ({ ...c, description: e.target.value }))
                }
                rows={3}
                placeholder="Opis stanowiska..."
              />
              {aiError && (
                <div className="text-xs text-destructive bg-destructive/10 rounded-lg px-3 py-2">
                  {aiError}
                </div>
              )}
              {aiDraft && (
                <div className="rounded-lg border p-3 space-y-2">
                  <p className="text-sm font-medium">
                    Szkic opisu —{" "}
                    {aiDraft.source === "template"
                      ? "szablon z podanych danych"
                      : "AI"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Sprawdź zgodność z requestem i popraw treść przed
                    zastosowaniem.
                  </p>
                  <textarea
                    aria-label="Szkic opisu do zatwierdzenia"
                    className="w-full min-h-32 rounded border bg-background p-2 text-sm"
                    value={aiDraft.description}
                    onChange={(e) =>
                      setAiDraft((d) =>
                        d ? { ...d, description: e.target.value } : null,
                      )
                    }
                  />
                  <div className="flex items-center gap-3">
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => {
                        setForm((c) => ({
                          ...c,
                          description: aiDraft.description,
                        }));
                        setAiDraft(null);
                      }}
                    >
                      Zastosuj sprawdzony opis
                    </Button>
                    <button
                      type="button"
                      className="text-sm"
                      onClick={() => setAiDraft(null)}
                    >
                      Odrzuć szkic
                    </button>
                  </div>
                </div>
              )}
            </div>

            <FormField
              label="Must-have"
              htmlFor={mustHaveId}
              description="Oddziel przecinkami"
            >
              <Input
                id={mustHaveId}
                value={form.mustHaveInput}
                onChange={(e) =>
                  setForm((c) => ({ ...c, mustHaveInput: e.target.value }))
                }
                placeholder="Java, Spring, Kafka"
              />
            </FormField>

            <div className="grid grid-cols-3 gap-3">
              <FormField label="Miasto biura" htmlFor={locationId}>
                <Input
                  id={locationId}
                  value={form.location}
                  onChange={(e) =>
                    setForm((c) => ({ ...c, location: e.target.value }))
                  }
                  placeholder="np. Warszawa"
                />
              </FormField>
              <FormField label="Tryb pracy" htmlFor={remotePolicyId}>
                <select
                  id={remotePolicyId}
                  className={SELECT_CLASS}
                  value={form.remotePolicy}
                  onChange={(e) =>
                    setForm((c) => ({
                      ...c,
                      remotePolicy: e.target.value as RemotePolicy | "",
                    }))
                  }
                >
                  {REMOTE_POLICY_OPTIONS.map((opt) => (
                    <option key={opt.value || "unset"} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField label="Dni w biurze / tydzień" htmlFor={onsiteDaysId}>
                <Input
                  id={onsiteDaysId}
                  type="number"
                  min={0}
                  max={7}
                  disabled={form.remotePolicy === "remote"}
                  value={form.onsiteDaysPerWeek}
                  onChange={(e) =>
                    setForm((c) => ({
                      ...c,
                      onsiteDaysPerWeek: e.target.value,
                    }))
                  }
                  placeholder="np. 2"
                />
              </FormField>
            </div>

            <FormField
              label="Budżet PLN/h dla kandydata"
              htmlFor={rateBudgetId}
              description="Puste = użyjemy stawki Championa"
            >
              <Input
                id={rateBudgetId}
                type="number"
                value={form.rateBudgetHourly}
                onChange={(e) =>
                  setForm((c) => ({ ...c, rateBudgetHourly: e.target.value }))
                }
                placeholder="np. 150"
              />
            </FormField>

            {canEditBudget && (
              <div className="grid grid-cols-2 gap-3">
                <FormField
                  label="Wynagrodzenie min (PLN/mies.)"
                  htmlFor={salaryMinId}
                >
                  <Input
                    id={salaryMinId}
                    type="number"
                    value={form.salaryMin}
                    onChange={(e) =>
                      setForm((c) => ({ ...c, salaryMin: e.target.value }))
                    }
                    placeholder="8 000"
                  />
                </FormField>
                <FormField
                  label="Wynagrodzenie max (PLN/mies.)"
                  htmlFor={salaryMaxId}
                >
                  <Input
                    id={salaryMaxId}
                    type="number"
                    value={form.salaryMax}
                    onChange={(e) =>
                      setForm((c) => ({ ...c, salaryMax: e.target.value }))
                    }
                    placeholder="12 000"
                  />
                </FormField>
              </div>
            )}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={attemptClose}>
              Anuluj
            </Button>
            <Button type="submit" loading={saving}>
              Dodaj rekrutację
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>

      {confirmClose && (
        <DiscardDraftDialog
          onReturn={() => setConfirmClose(false)}
          onKeepDraft={() => {
            if (user?.id != null) writeJobDraft(user.id, form);
            setConfirmClose(false);
            onClose();
          }}
          onDiscard={() => {
            draft.clear();
            setConfirmClose(false);
            onClose();
          }}
        />
      )}
    </Dialog>
  );
}

function DiscardDraftDialog({
  onReturn,
  onKeepDraft,
  onDiscard,
}: {
  onReturn: () => void;
  onKeepDraft: () => void;
  onDiscard: () => void;
}) {
  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) onReturn();
      }}
    >
      <DialogContent
        size="sm"
        onPointerDownOutside={(e) => e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>Zamknąć formularz?</DialogTitle>
        </DialogHeader>
        <DialogBody className="text-sm text-muted-foreground">
          Formularz ma niezapisane zmiany.
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onReturn}>
            Wróć do formularza
          </Button>
          <Button type="button" variant="outline" onClick={onKeepDraft}>
            Zamknij i zachowaj szkic
          </Button>
          <Button type="button" variant="destructive" onClick={onDiscard}>
            Odrzuć szkic
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
