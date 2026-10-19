"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import {
  EMPTY_PROFILE_FORM,
  ProfileFieldsForm,
  type ProfileFormState,
} from "@/components/hr/people/ProfileFieldsForm";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import {
  EMPLOYMENT_TYPE_LABELS,
  usePeople,
  useUsersWithoutProfile,
  type HrConfig,
} from "@/lib/api/hr";
import {
  ASSIGNEE_LABELS,
  CATEGORY_LABELS,
  useCreateOnboarding,
  useLifecycleTemplates,
  usePreviewTasks,
  type OnboardingProfileValues,
} from "@/lib/api/hr-lifecycle";
import { cn } from "@/lib/utils";
import { formatWeekdayDayPl } from "@/lib/date-pl";

const STEPS = ["Osoba i konto", "Zatrudnienie", "Zadania", "Podsumowanie"] as const;
const AUTO = "auto";

type PersonMode = "account" | "new";

/** Pola kreatora → kartoteka (status i ostatni dzień ustawia sprawa, nie kreator). */
export function onboardingProfile(form: ProfileFormState): OnboardingProfileValues {
  const text = (value: string) => (value.trim() ? value.trim() : null);
  return {
    // Kreator zawsze ma wybraną formę (start z `EMPTY_PROFILE_FORM`, bez pustej opcji).
    employment_type: form.employment_type || "b2b",
    default_location: form.default_location,
    timesheet_required: form.timesheet_required,
    can_log_overtime: form.can_log_overtime,
    job_title: text(form.job_title),
    department: text(form.department),
    phone: text(form.phone),
  };
}

/** Który krok jeszcze czegoś wymaga (null = można iść dalej). */
export function stepProblem(
  step: number,
  input: { mode: PersonMode; userId: string; email: string; name: string; start: string },
): string | null {
  if (step === 0) {
    if (input.mode === "account" && !input.userId) return "Wybierz konto.";
    if (input.mode === "new") {
      if (!input.name.trim()) return "Podaj imię i nazwisko.";
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(input.email.trim())) {
        return "Podaj poprawny adres e-mail.";
      }
    }
  }
  if (step === 1 && !input.start) return "Podaj datę startu.";
  return null;
}

/** Kreator wejścia nowej osoby (Kadry). */
export function OnboardingWizard({ config }: { config: HrConfig }) {
  const router = useRouter();
  const { showToast } = useToast();
  const canManage = config.me.people_admin || config.me.is_admin;
  const accounts = useUsersWithoutProfile(canManage);
  const directory = usePeople();
  const templates = useLifecycleTemplates("onboarding", canManage);
  const create = useCreateOnboarding();

  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<PersonMode>("account");
  const [userId, setUserId] = useState("");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [form, setForm] = useState<ProfileFormState>({
    ...EMPTY_PROFILE_FORM,
    employment_status: "onboarding",
  });
  const [templateId, setTemplateId] = useState(AUTO);
  const [error, setError] = useState<string | null>(null);

  const managers = (directory.data?.items ?? []).map((row) => ({
    user_id: row.user_id,
    name: row.name,
  }));
  const preview = usePreviewTasks({
    kind: "onboarding",
    anchor: form.work_start_date,
    template_id: templateId === AUTO ? null : Number(templateId),
    employment_type: form.employment_type || "b2b",
    department: form.department.trim() || null,
    enabled: canManage && step >= 2,
  });
  const personLabel = useMemo(() => {
    if (mode === "new") return name.trim() || email.trim();
    const account = (accounts.data ?? []).find((a) => String(a.user_id) === userId);
    return account ? account.name : "";
  }, [mode, name, email, accounts.data, userId]);

  if (!canManage) {
    return (
      <QueryStateNotice state="forbidden" description="Wejście nowej osoby prowadzą Kadry." />
    );
  }

  const next = () => {
    const problem = stepProblem(step, { mode, userId, email, name, start: form.work_start_date });
    setError(problem);
    if (!problem) setStep((value) => Math.min(value + 1, STEPS.length - 1));
  };

  const submit = (start: boolean) => {
    const input = { mode, userId, email, name, start: form.work_start_date };
    for (const required of [0, 1]) {
      const problem = stepProblem(required, input);
      if (problem) {
        setError(problem);
        setStep(required);
        return;
      }
    }
    setError(null);
    create.mutate(
      {
        user_id: mode === "account" ? Number(userId) : null,
        email: mode === "new" ? email.trim() : null,
        name: mode === "new" ? name.trim() : null,
        start_date: form.work_start_date,
        template_id: templateId === AUTO ? null : Number(templateId),
        manager_user_id: form.manager_user_id ? Number(form.manager_user_id) : null,
        profile: onboardingProfile(form),
        start,
      },
      {
        onSuccess: (created) => {
          showToast(start ? "Wejście rozpoczęte" : "Szkic wejścia zapisany", "success");
          router.push(`/people/new/${created.id}`);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać wejścia.")),
      },
    );
  };

  const activeTemplates = (templates.data ?? []).filter(
    // Ścieżki konsultanta wiszą przy kontrakcie — nie dla osoby z kontem.
    (t) => t.is_active && (t.audience ?? "team") === "team",
  );
  const title = personLabel
    ? `${personLabel}${form.job_title.trim() ? ` · ${form.job_title.trim()}` : ""}${
        form.work_start_date ? ` · start ${formatWeekdayDayPl(form.work_start_date)}` : ""
      }`
    : "Nowa osoba";

  return (
    <div className="space-y-4">
      <PageHeader
        title={title}
        description="Wejście: kartoteka, konto, zadania dla przełożonego, Kadr, recepcji i IT."
        breadcrumb={[{ label: "Ludzie", href: "/people" }, { label: "Wejście" }]}
        density="compact"
        actions={
          step > 0 ? (
            <Button variant="outline" disabled={create.isPending} onClick={() => submit(false)}>
              Zapisz szkic
            </Button>
          ) : null
        }
      />
      <ol className="flex flex-wrap gap-2 text-sm" aria-label="Kroki">
        {STEPS.map((label, index) => (
          <li
            key={label}
            aria-current={index === step ? "step" : undefined}
            className={cn(
              "rounded-full border px-3 py-1",
              index === step
                ? "border-primary bg-primary/10 font-medium text-primary"
                : index < step
                  ? "border-border text-foreground"
                  : "border-border text-muted-foreground",
            )}
          >
            {index + 1} · {label}
          </li>
        ))}
      </ol>

      <Card className="max-w-4xl space-y-4 p-5">
        {step === 0 ? (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Kto wchodzi">
              <Button
                variant={mode === "account" ? "primary" : "outline"}
                size="sm"
                role="radio"
                aria-checked={mode === "account"}
                onClick={() => setMode("account")}
              >
                Ma konto w NEXUSIE
              </Button>
              <Button
                variant={mode === "new" ? "primary" : "outline"}
                size="sm"
                role="radio"
                aria-checked={mode === "new"}
                onClick={() => setMode("new")}
              >
                Nowa osoba bez konta
              </Button>
            </div>
            {mode === "account" ? (
              <FormField label="Konto" htmlFor="on-account" required>
                <Select value={userId} onValueChange={setUserId}>
                  <SelectTrigger id="on-account">
                    <SelectValue
                      placeholder={
                        accounts.isLoading
                          ? "Wczytywanie kont…"
                          : accounts.isSuccess && (accounts.data ?? []).length === 0
                            ? "Każde konto ma już kartotekę"
                            : "Wybierz konto"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {(accounts.data ?? []).map((account) => (
                      <SelectItem key={account.user_id} value={String(account.user_id)}>
                        {account.name} · {account.email}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
                <FormField label="Imię i nazwisko" htmlFor="on-name" required>
                  <Input
                    id="on-name"
                    value={name}
                    maxLength={255}
                    onChange={(event) => setName(event.target.value)}
                  />
                </FormField>
                <FormField label="E-mail służbowy" htmlFor="on-email" required>
                  <Input
                    id="on-email"
                    type="email"
                    value={email}
                    maxLength={255}
                    onChange={(event) => setEmail(event.target.value)}
                  />
                </FormField>
                <p className="text-xs text-muted-foreground sm:col-span-2">
                  Konto zakłada admin w Ustawieniach → Użytkownicy albo powstaje przy
                  pierwszym logowaniu przez Microsoft. Szkic można zapisać od razu,
                  „Rozpocznij” zadziała, gdy konto z tym adresem już będzie.
                </p>
              </div>
            )}
            {accounts.isError ? (
              <p role="alert" className="text-sm text-destructive">
                {apiErrorMessage(accounts.error, "Nie udało się wczytać listy kont.")}
              </p>
            ) : null}
          </div>
        ) : null}

        {step === 1 ? (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              „Start pracy” to data wejścia — od niej liczą się terminy zadań. Status
              ustawi sprawa („Wejście”), ostatniego dnia nie podaje się.
            </p>
            <ProfileFieldsForm
              form={form}
              onChange={setForm}
              managers={managers}
              idPrefix="hr-onboarding"
              hide={["employment_status", "last_working_day"]}
            />
          </div>
        ) : null}

        {step === 2 ? (
          <div className="space-y-3">
            <FormField label="Lista zadań" htmlFor="on-template">
              <Select value={templateId} onValueChange={setTemplateId}>
                <SelectTrigger id="on-template" className="max-w-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={AUTO}>Dobierz do formy i działu</SelectItem>
                  {activeTemplates.map((t) => (
                    <SelectItem key={t.id} value={String(t.id)}>
                      {t.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            {preview.isError ? (
              <QueryStateNotice state="error" onRetry={() => preview.refetch()} />
            ) : preview.isLoading ? (
              <p className="text-sm text-muted-foreground">Liczenie terminów…</p>
            ) : preview.isSuccess && preview.data.tasks.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Brak aktywnej listy zadań wejścia — dodaj ją w Ustawieniach → Kadry.
              </p>
            ) : (
              <ul className="divide-y divide-border/60">
                {(preview.data?.tasks ?? []).map((task, index) => (
                  <li key={`${task.title}-${index}`} className="flex items-center gap-3 py-2 text-sm">
                    <span className="w-20 shrink-0 tabular-nums text-muted-foreground">
                      {formatWeekdayDayPl(task.due_date)}
                    </span>
                    <span className="min-w-0 flex-1 text-foreground">{task.title}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {ASSIGNEE_LABELS[task.assignee_kind]} · {CATEGORY_LABELS[task.category]}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-xs text-muted-foreground">
              Terminy w dniach roboczych firmy (bez weekendów, świąt i dni wolnych firmy).
            </p>
          </div>
        ) : null}

        {step === 3 ? (
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-muted-foreground">Osoba</dt>
              <dd className="font-medium">{personLabel || "—"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Start</dt>
              <dd className="font-medium">{formatWeekdayDayPl(form.work_start_date)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Stanowisko i dział</dt>
              <dd className="font-medium">
                {[form.job_title.trim(), form.department.trim()].filter(Boolean).join(" · ") ||
                  "—"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Forma</dt>
              <dd className="font-medium">{EMPLOYMENT_TYPE_LABELS[form.employment_type || "b2b"]}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Przełożony</dt>
              <dd className="font-medium">
                {managers.find((m) => String(m.user_id) === form.manager_user_id)?.name ??
                  "Bez przełożonego"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Zadania</dt>
              <dd className="font-medium">{preview.data?.tasks.length ?? 0}</dd>
            </div>
          </dl>
        ) : null}

        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-4">
          <Button
            variant="ghost"
            disabled={step === 0}
            onClick={() => {
              setError(null);
              setStep((value) => Math.max(value - 1, 0));
            }}
          >
            Wstecz
          </Button>
          {step < STEPS.length - 1 ? (
            <Button onClick={next}>Dalej: {STEPS[step + 1].toLowerCase()}</Button>
          ) : mode === "new" ? (
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-xs text-muted-foreground">
                Bez konta zapisuje się szkic — rozpoczniesz go, gdy konto powstanie.
              </span>
              <Button disabled={create.isPending} onClick={() => submit(false)}>
                Zapisz szkic
              </Button>
            </div>
          ) : (
            <Button disabled={create.isPending} onClick={() => submit(true)}>
              Rozpocznij wejście
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
}
