"use client";

import { useId, useState, type KeyboardEvent } from "react";
import { Plus, Trash2, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  newQuestionKey,
  type IntakeForm,
  type IntakeQuestionForm,
  type MissingCode,
  type QuestionOrigin,
  type RemotePolicyValue,
} from "@/lib/job-request-intake";

const WORK_MODES: { value: RemotePolicyValue; label: string }[] = [
  { value: "remote", label: "Zdalnie" },
  { value: "hybrid", label: "Hybrydowo" },
  { value: "onsite", label: "Biuro" },
];

const ORIGIN_LABEL: Record<QuestionOrigin, string> = {
  request: "z requestu",
  ai: "propozycja AI",
  template: "z podobnej rekrutacji",
  manual: "dopisane",
};

/** „2 pytania”, „5 pytań”, „22 pytania” — polska odmiana liczebnika. */
export function questionsLabel(n: number): string {
  const lastTwo = n % 100;
  const last = n % 10;
  if (n === 1) return "1 pytanie";
  if (last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14))
    return `${n} pytania`;
  return `${n} pytań`;
}

const MISSING_RING = "border-warning ring-2 ring-warning-muted";

function FieldLabel({
  htmlFor,
  children,
  hint,
  missing,
}: {
  htmlFor?: string;
  children: React.ReactNode;
  hint?: string | null;
  missing?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      {htmlFor ? (
        <label
          htmlFor={htmlFor}
          className="text-sm font-medium text-foreground"
        >
          {children}
        </label>
      ) : (
        <span className="text-sm font-medium text-foreground">{children}</span>
      )}
      {!missing && hint ? (
        <span className="text-xs text-muted-foreground">{hint}</span>
      ) : null}
    </div>
  );
}

/** Pod polem, nie obok etykiety — w wąskiej kolumnie łamała się i przesuwała pole. */
function MissingNote({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span className="text-xs font-medium text-warning-muted-foreground">
      Brak w requeście — uzupełnij
    </span>
  );
}

function TagListInput({
  label,
  values,
  onChange,
  tone,
  missing,
  placeholder,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  tone: "primary" | "muted";
  missing?: boolean;
  placeholder: string;
}) {
  const inputId = useId();
  const [draft, setDraft] = useState("");

  const commit = () => {
    const parts = draft
      .split(/[,;\n]/)
      .map((p) => p.trim())
      .filter(Boolean);
    if (parts.length === 0) return;
    const next = [...values];
    for (const part of parts) {
      if (!next.some((v) => v.toLowerCase() === part.toLowerCase()))
        next.push(part);
    }
    onChange(next);
    setDraft("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit();
    } else if (e.key === "Backspace" && !draft && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <FieldLabel htmlFor={inputId} missing={missing}>
        {label}
      </FieldLabel>
      <div
        className={cn(
          "flex min-h-10 flex-wrap items-center gap-1.5 rounded-lg border border-border bg-card px-2 py-1.5",
          missing && MISSING_RING,
        )}
      >
        {values.map((value) => (
          <span
            key={value}
            className={cn(
              "inline-flex h-7 items-center gap-1 rounded-md px-2 text-sm font-medium",
              tone === "primary"
                ? "bg-primary/10 text-primary"
                : "bg-muted text-foreground",
            )}
          >
            {value}
            <button
              type="button"
              aria-label={`Usuń ${value}`}
              className="rounded opacity-70 hover:opacity-100"
              onClick={() => onChange(values.filter((v) => v !== value))}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </span>
        ))}
        <input
          id={inputId}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={commit}
          placeholder={values.length === 0 ? placeholder : "dodaj…"}
          className="h-7 min-w-[8rem] flex-1 bg-transparent px-1 text-sm text-foreground outline-hidden placeholder:text-muted-foreground"
        />
      </div>
      <MissingNote show={!!missing} />
    </div>
  );
}

interface NewJobReviewFormProps {
  form: IntakeForm;
  onChange: (updater: (form: IntakeForm) => IntakeForm) => void;
  missing: MissingCode[];
  /** Po odczycie przez AI braki są podświetlane; w trybie ręcznym nie. */
  highlightMissing: boolean;
}

/** Krok 2 strony `/jobs/new`: pola, które wymaga „Przekaż do searchu”. */
export function NewJobReviewForm({
  form,
  onChange,
  missing,
  highlightMissing,
}: NewJobReviewFormProps) {
  const ids = {
    title: useId(),
    rate: useId(),
    days: useId(),
    city: useId(),
    start: useId(),
    about: useId(),
    resp: useId(),
  };
  const isMissing = (code: MissingCode) =>
    highlightMissing && missing.includes(code);
  const set = <K extends keyof IntakeForm>(key: K, value: IntakeForm[K]) =>
    onChange((f) => ({ ...f, [key]: value }));
  const officeNeeded =
    form.remotePolicy !== "" && form.remotePolicy !== "remote";

  const updateQuestion = (key: string, patch: Partial<IntakeQuestionForm>) =>
    onChange((f) => ({
      ...f,
      questions: f.questions.map((q) =>
        q.key === key ? { ...q, ...patch } : q,
      ),
    }));
  const removeQuestion = (key: string) =>
    onChange((f) => ({
      ...f,
      questions: f.questions.filter((q) => q.key !== key),
    }));
  const addQuestion = () =>
    onChange((f) => ({
      ...f,
      questions: [
        ...f.questions,
        {
          key: newQuestionKey(),
          question: "",
          idealAnswer: "",
          origin: "manual",
        },
      ],
    }));
  const filledCount = form.questions.filter((q) => q.question.trim()).length;

  return (
    <div className="flex flex-col gap-4">
      <section className="flex flex-col gap-5 rounded-xl border border-border bg-card p-6">
        <div className="flex flex-col gap-2">
          <FieldLabel htmlFor={ids.title} missing={isMissing("role")}>
            Rola
          </FieldLabel>
          <Input
            id={ids.title}
            value={form.title}
            onChange={(e) => set("title", e.target.value)}
            placeholder="np. Senior Java Developer"
            className={cn(isMissing("role") && MISSING_RING)}
          />
          <MissingNote show={isMissing("role")} />
        </div>

        <TagListInput
          label="Must-have"
          values={form.must}
          onChange={(v) => set("must", v)}
          tone="primary"
          missing={isMissing("must")}
          placeholder="np. Java, Spring Boot — Enter dodaje"
        />
        <TagListInput
          label="Mile widziane"
          values={form.nice}
          onChange={(v) => set("nice", v)}
          tone="muted"
          placeholder="opcjonalnie"
        />

        <div className="grid gap-4 md:grid-cols-4">
          <div className="flex flex-col gap-2">
            <FieldLabel htmlFor={ids.rate} missing={isMissing("budget")}>
              Budżet PLN/h
            </FieldLabel>
            <Input
              id={ids.rate}
              inputMode="decimal"
              value={form.rateBudget}
              onChange={(e) => set("rateBudget", e.target.value)}
              placeholder="np. 160"
              className={cn(isMissing("budget") && MISSING_RING)}
            />
            <MissingNote show={isMissing("budget")} />
            {form.rateNote && (
              <span className="text-xs text-muted-foreground">
                {form.rateNote}
              </span>
            )}
          </div>
          <div className="flex flex-col gap-2 md:col-span-2">
            <FieldLabel missing={isMissing("work_mode")}>Tryb pracy</FieldLabel>
            <div
              role="radiogroup"
              aria-label="Tryb pracy"
              className={cn(
                "flex h-10 items-center gap-0.5 rounded-lg bg-muted p-0.5",
                isMissing("work_mode") && MISSING_RING,
              )}
            >
              {WORK_MODES.map((mode) => {
                const active = form.remotePolicy === mode.value;
                return (
                  <button
                    key={mode.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => set("remotePolicy", mode.value)}
                    className={cn(
                      "h-9 flex-1 rounded-md text-sm transition-colors",
                      active
                        ? "bg-card font-semibold text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {mode.label}
                  </button>
                );
              })}
            </div>
            <MissingNote show={isMissing("work_mode")} />
          </div>
          <div className="flex flex-col gap-2">
            <FieldLabel
              htmlFor={ids.days}
              missing={officeNeeded && isMissing("office_days")}
            >
              Dni w biurze
            </FieldLabel>
            <Input
              id={ids.days}
              type="number"
              min={0}
              max={7}
              disabled={!officeNeeded}
              value={officeNeeded ? form.onsiteDays : ""}
              onChange={(e) => set("onsiteDays", e.target.value)}
              placeholder={officeNeeded ? "np. 2" : "—"}
              className={cn(
                officeNeeded && isMissing("office_days") && MISSING_RING,
              )}
            />
            <MissingNote show={officeNeeded && isMissing("office_days")} />
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          {officeNeeded && (
            <div className="flex flex-col gap-2">
              <FieldLabel htmlFor={ids.city} missing={isMissing("office_city")}>
                Miasto biura
              </FieldLabel>
              <Input
                id={ids.city}
                value={form.city}
                onChange={(e) => set("city", e.target.value)}
                placeholder="np. Warszawa"
                className={cn(isMissing("office_city") && MISSING_RING)}
              />
              <MissingNote show={isMissing("office_city")} />
            </div>
          )}
          <div className="flex flex-col gap-2">
            <FieldLabel htmlFor={ids.start} hint="opcjonalnie">
              Start
            </FieldLabel>
            <Input
              id={ids.start}
              type="date"
              value={form.startDate}
              onChange={(e) => set("startDate", e.target.value)}
            />
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <FieldLabel
            htmlFor={ids.about}
            missing={isMissing("context")}
            hint="2 zdania"
          >
            O projekcie
          </FieldLabel>
          <Textarea
            id={ids.about}
            rows={2}
            value={form.about}
            onChange={(e) => set("about", e.target.value)}
            placeholder="Cel projektu i zespół — to widzi rekruter i model dopasowań."
            className={cn(isMissing("context") && MISSING_RING)}
          />
          <MissingNote show={isMissing("context")} />
        </div>
        {form.responsibilities && (
          <div className="flex flex-col gap-2">
            <FieldLabel htmlFor={ids.resp} hint="opcjonalnie">
              Obowiązki
            </FieldLabel>
            <Textarea
              id={ids.resp}
              rows={2}
              value={form.responsibilities}
              onChange={(e) => set("responsibilities", e.target.value)}
            />
          </div>
        )}
      </section>

      <section
        aria-labelledby="new-job-questions"
        className={cn(
          "flex flex-col gap-3 rounded-xl border border-border bg-card p-6",
          isMissing("questions") && "border-warning",
        )}
      >
        <div className="flex items-baseline justify-between gap-2">
          <h2
            id="new-job-questions"
            className="text-base font-semibold text-foreground"
          >
            Pytania screeningowe
          </h2>
          <span
            className={cn(
              "text-xs",
              filledCount < 2
                ? "font-medium text-warning-muted-foreground"
                : "text-muted-foreground",
            )}
          >
            {filledCount < 2
              ? `${filledCount} z 2 wymaganych`
              : questionsLabel(filledCount)}
          </span>
        </div>
        {form.questions.map((q, i) => (
          <div
            key={q.key}
            className={cn(
              "flex flex-col gap-2 rounded-lg border p-3",
              q.origin === "ai"
                ? "border-dashed border-primary/40 bg-primary/5"
                : "border-border",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">
                Pytanie {i + 1} · {ORIGIN_LABEL[q.origin]}
              </span>
              <button
                type="button"
                aria-label={`Usuń pytanie ${i + 1}`}
                className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                onClick={() => removeQuestion(q.key)}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
            <Input
              aria-label={`Treść pytania ${i + 1}`}
              value={q.question}
              onChange={(e) =>
                updateQuestion(q.key, { question: e.target.value })
              }
              placeholder="Pytanie do kandydata"
            />
            <Input
              aria-label={`Dobra odpowiedź na pytanie ${i + 1}`}
              value={q.idealAnswer}
              onChange={(e) =>
                updateQuestion(q.key, { idealAnswer: e.target.value })
              }
              placeholder="Dobra odpowiedź — czego szukać (opcjonalnie)"
              className="text-muted-foreground"
            />
          </div>
        ))}
        <button
          type="button"
          onClick={addQuestion}
          className="inline-flex items-center gap-1.5 self-start text-sm font-medium text-primary hover:underline"
        >
          <Plus className="h-4 w-4" /> Dodaj pytanie
        </button>
      </section>
    </div>
  );
}
