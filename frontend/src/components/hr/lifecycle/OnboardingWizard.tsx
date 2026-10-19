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
  type LifecycleTemplate,
  type OnboardingProfileValues,
} from "@/lib/api/hr-lifecycle";
import { cn } from "@/lib/utils";
import { formatWeekdayDayPl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";
import { warsawToday } from "@/lib/warsaw-date";
import { personInitials } from "@/components/hr/people/hr-format";
import { Badge } from "@/components/ui/badge";

import { matchAccounts, previewByOwner } from "./lifecycle-format";

const STEPS = ["Osoba i konto", "Zatrudnienie", "Zadania", "Podsumowanie"] as const;
const STEP_HINTS = [
  "kto wchodzi i jaką ścieżką",
  "forma, start, przełożony",
  "kto co przygotuje i do kiedy",
  "sprawdź i uruchom",
] as const;
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

/** Opis karty ścieżki: pierwsze pozycje albo forma i dział, do których pasuje. */
function pathHint(template: LifecycleTemplate): string {
  if (template.items.length) {
    const titles = template.items.slice(0, 4).map((item) => item.title.toLowerCase());
    return titles.join(", ") + (template.items.length > 4 ? "…" : "");
  }
  return [
    template.employment_type ? EMPLOYMENT_TYPE_LABELS[template.employment_type] : "każda forma",
    template.department ?? "każdy dział",
  ].join(" · ");
}

/**
 * „Co powstanie” (makieta 19.10.2026): kartoteka i zadania ze ścieżki
 * pogrupowane wg wykonawcy — liczy serwer bez zapisu (`POST …/preview`).
 */
function WhatWillHappen({
  mode,
  start,
  preview,
}: {
  mode: PersonMode;
  start: string;
  preview: ReturnType<typeof usePreviewTasks>;
}) {
  const groups = previewByOwner(preview.data?.tasks ?? []);
  return (
    <Card className="flex-[1_1_320px] space-y-0 p-4" role="region" aria-labelledby="on-what">
      <div className="flex items-center justify-between gap-2 pb-3">
        <h2 id="on-what" className="text-sm font-semibold">
          Co powstanie
        </h2>
        <Badge variant="neutral">{start ? `start ${formatWeekdayDayPl(start)}` : "start nieustalony"}</Badge>
      </div>
      <section className="space-y-0.5 border-t border-border/60 py-2.5">
        <div className="flex items-center justify-between text-sm font-semibold">
          <span>Kartoteka</span>
          <Badge variant="success" size="sm">
            {mode === "account" ? "z konta" : "szkic"}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          {mode === "account"
            ? "imię, e-mail, telefon z Microsoft 365"
            : "„Rozpocznij” zadziała, gdy konto z tym adresem powstanie"}
        </p>
      </section>
      {preview.isError ? (
        <div className="border-t border-border/60 py-2.5">
          <QueryStateNotice state="error" onRetry={() => preview.refetch()} />
        </div>
      ) : preview.isLoading ? (
        <p className="border-t border-border/60 py-2.5 text-sm text-muted-foreground">
          Liczenie zadań…
        </p>
      ) : preview.isSuccess && groups.length === 0 ? (
        <p className="border-t border-border/60 py-2.5 text-sm text-muted-foreground">
          Brak aktywnej ścieżki wejścia — dodaj ją w Ustawieniach → Kadry.
        </p>
      ) : (
        groups.map((group) => (
          <section key={group.kind} className="space-y-1 border-t border-border/60 py-2.5">
            <div className="flex items-center justify-between text-sm font-semibold">
              <span>{ASSIGNEE_LABELS[group.kind as keyof typeof ASSIGNEE_LABELS] ?? group.kind}</span>
              <span className="text-xs font-medium text-muted-foreground">
                {countPl(group.tasks.length, "zadanie", "zadania", "zadań")}
              </span>
            </div>
            <ul className="space-y-0.5 text-[13px]">
              {group.tasks.map((task, index) => (
                <li key={`${task.title}-${index}`} className="flex justify-between gap-2">
                  <span className="min-w-0">{task.title}</span>
                  {start ? (
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {formatWeekdayDayPl(task.due_date)}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
      {preview.data?.template_name ? (
        <p className="border-t border-border/60 pt-2.5 text-xs text-muted-foreground">
          Listę zadań bierzemy ze ścieżki „{preview.data.template_name}”; w kroku 3 można ją
          zmienić.
        </p>
      ) : null}
    </Card>
  );
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
  // „Co powstanie” liczy się od kroku 1; bez daty startu terminy liczymy od
  // dziś, ale panel ich nie pokazuje (data jeszcze nie padła).
  const preview = usePreviewTasks({
    kind: "onboarding",
    anchor: form.work_start_date || warsawToday(),
    template_id: templateId === AUTO ? null : Number(templateId),
    employment_type: form.employment_type || "b2b",
    department: form.department.trim() || null,
    enabled: canManage,
  });
  const [search, setSearch] = useState("");
  const accountMatches = useMemo(
    () => matchAccounts(accounts.data ?? [], directory.data?.items ?? [], search),
    [accounts.data, directory.data, search],
  );
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
      <Card className="px-4 py-3">
        <ol className="flex flex-wrap gap-x-6 gap-y-2" aria-label="Kroki">
          {STEPS.map((label, index) => (
            <li
              key={label}
              aria-current={index === step ? "step" : undefined}
              className="flex items-center gap-2.5"
            >
              <span
                aria-hidden
                className={cn(
                  "grid h-7 w-7 shrink-0 place-items-center rounded-full text-[13px] font-semibold",
                  index === step
                    ? "bg-primary text-primary-foreground"
                    : index < step
                      ? "bg-primary/15 text-primary"
                      : "bg-muted text-muted-foreground",
                )}
              >
                {index + 1}
              </span>
              <span>
                <span
                  className={cn(
                    "block text-sm font-semibold",
                    index === step ? "text-primary" : "text-foreground",
                  )}
                >
                  {label}
                </span>
                <span className="block text-xs text-muted-foreground">{STEP_HINTS[index]}</span>
              </span>
            </li>
          ))}
        </ol>
      </Card>

      <div className="flex flex-wrap items-start gap-4">
      <Card className="min-w-0 flex-[999_1_600px] space-y-4 p-5">
        {step === 0 ? (
          <div className="space-y-5">
            <div className="space-y-2">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Ścieżka
              </span>
              <div className="grid gap-2.5 sm:grid-cols-2" role="radiogroup" aria-label="Ścieżka">
                {[{ id: AUTO, name: "Dobierz do formy i działu", hint: "ścieżka pasująca do formy i działu z kroku 2" },
                  ...activeTemplates.map((t) => ({
                    id: String(t.id),
                    name: t.name,
                    hint: pathHint(t),
                  })),
                ].map((path) => (
                  <button
                    key={path.id}
                    type="button"
                    role="radio"
                    aria-checked={templateId === path.id}
                    onClick={() => setTemplateId(path.id)}
                    className={cn(
                      "flex flex-col gap-1 rounded-lg border p-3 text-left text-sm transition-colors",
                      templateId === path.id
                        ? "border-primary bg-primary/5 ring-2 ring-primary/20"
                        : "border-border hover:bg-muted/50",
                    )}
                  >
                    <span className="flex items-center justify-between gap-2 font-semibold">
                      {path.name}
                      <span
                        aria-hidden
                        className={cn(
                          "h-4 w-4 shrink-0 rounded-full border",
                          templateId === path.id ? "border-[5px] border-primary" : "border-border",
                        )}
                      />
                    </span>
                    <span className="text-[13px] text-muted-foreground">{path.hint}</span>
                  </button>
                ))}
                <div className="flex flex-col gap-1 rounded-lg border border-dashed border-border p-3 text-left text-sm">
                  <span className="font-semibold text-muted-foreground">Konsultant u klienta</span>
                  <span className="text-[13px] text-muted-foreground">
                    Listę wejścia zakłada kontrakt — zakładka „Wejście” kontraktu.
                  </span>
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Konto w NEXUSIE
                </span>
                <div className="flex flex-wrap gap-1 rounded-lg border border-border p-0.5" role="radiogroup" aria-label="Kto wchodzi">
                  <Button
                    variant={mode === "account" ? "secondary" : "ghost"}
                    size="sm"
                    role="radio"
                    aria-checked={mode === "account"}
                    onClick={() => setMode("account")}
                  >
                    Ma konto w NEXUSIE
                  </Button>
                  <Button
                    variant={mode === "new" ? "secondary" : "ghost"}
                    size="sm"
                    role="radio"
                    aria-checked={mode === "new"}
                    onClick={() => setMode("new")}
                  >
                    Nowa osoba bez konta
                  </Button>
                </div>
              </div>
              {mode === "account" ? (
                <div className="space-y-1.5">
                  <div className="overflow-hidden rounded-lg border border-border focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20">
                    <Input
                      id="on-account"
                      type="search"
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder={
                        accounts.isLoading ? "Wczytywanie kont…" : "Szukaj konta po imieniu albo e-mailu"
                      }
                      aria-label="Szukaj konta po imieniu albo e-mailu"
                      className="h-10 rounded-none border-0 shadow-none focus-visible:ring-0"
                    />
                    <ul role="listbox" aria-label="Konta" className="max-h-64 overflow-y-auto">
                      {accountMatches.map((account) => {
                        const selected = String(account.user_id) === userId;
                        return (
                          <li
                            key={account.user_id}
                            role="option"
                            aria-selected={selected}
                            aria-disabled={account.has_profile}
                            tabIndex={account.has_profile ? -1 : 0}
                            onClick={() => !account.has_profile && setUserId(String(account.user_id))}
                            onKeyDown={(event) => {
                              if ((event.key === "Enter" || event.key === " ") && !account.has_profile) {
                                event.preventDefault();
                                setUserId(String(account.user_id));
                              }
                            }}
                            className={cn(
                              "flex items-center gap-2.5 border-t border-border/60 px-3 py-2 text-sm",
                              account.has_profile
                                ? "cursor-default opacity-70"
                                : "cursor-pointer hover:bg-muted/60",
                              selected && "bg-primary/5",
                            )}
                          >
                            <span
                              aria-hidden
                              className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-muted text-[11px] font-semibold"
                            >
                              {personInitials(account.name)}
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="block truncate font-medium">{account.name}</span>
                              <span className="block truncate text-xs text-muted-foreground">
                                {account.email}
                              </span>
                            </span>
                            <Badge variant={account.has_profile ? "success" : "warning"} size="sm">
                              {account.has_profile ? "ma kartotekę" : "bez kartoteki"}
                            </Badge>
                          </li>
                        );
                      })}
                      {accounts.isSuccess && accountMatches.length === 0 ? (
                        <li className="border-t border-border/60 px-3 py-2 text-sm text-muted-foreground">
                          {(accounts.data ?? []).length === 0
                            ? "Każde konto ma już kartotekę."
                            : "Nie ma takiego konta."}
                        </li>
                      ) : null}
                    </ul>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Najpierw pokazujemy konta bez kartoteki — to zwykle osoby, które właśnie wchodzą.
                  </p>
                </div>
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
      <WhatWillHappen
        mode={mode}
        start={form.work_start_date}
        preview={preview}
      />
      </div>
    </div>
  );
}
