"use client";

import { useId, useState, type KeyboardEvent } from "react";
import { ChevronDown, ChevronRight, Plus, Trash2, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { ChampionExperienceFields } from "@/components/champion/ChampionExperienceFields";
import { hasExperience } from "@/lib/champion-experience";
import {
  FIELD_BASIS_LABEL,
  markEdited,
  newQuestionKey,
  type FieldBasis,
  type IntakeForm,
  type ProvenanceKey,
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

/**
 * Skąd wartość — „z maila”, „z podobnej rekrutacji”, „propozycja AI”,
 * „wpisane”. Propozycja jest przerywana, fakt z maila pełny: DL od razu
 * widzi, które pola sprawdzić, zanim kliknie „Utwórz”.
 */
export function ProvenanceChip({ basis }: { basis?: FieldBasis }) {
  if (!basis) return null;
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-[11px] font-medium",
        basis === "request" && "bg-primary/10 text-primary",
        basis === "client_history" && "bg-info-muted text-info-muted-foreground",
        basis === "ai" && "border border-dashed border-primary/50 text-primary",
        basis === "manual" && "bg-muted text-muted-foreground",
      )}
      data-testid="provenance-chip"
    >
      {FIELD_BASIS_LABEL[basis]}
    </span>
  );
}

function FieldLabel({
  htmlFor,
  children,
  hint,
  missing,
  basis,
}: {
  htmlFor?: string;
  children: React.ReactNode;
  hint?: string | null;
  missing?: boolean;
  basis?: FieldBasis;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="inline-flex items-baseline gap-2">
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
        <ProvenanceChip basis={basis} />
      </span>
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
  basis,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  tone: "primary" | "muted";
  missing?: boolean;
  placeholder: string;
  basis?: FieldBasis;
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
      <FieldLabel htmlFor={inputId} missing={missing} basis={basis}>
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
  const set = <K extends keyof IntakeForm>(
    key: K,
    value: IntakeForm[K],
    provenanceKey?: ProvenanceKey,
  ) =>
    onChange((f) => {
      const next = { ...f, [key]: value };
      return provenanceKey ? markEdited(next, provenanceKey) : next;
    });
  const basis = (key: ProvenanceKey) => form.provenance?.[key];
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
      <section className="flex flex-col gap-5 rounded-xl border border-border bg-card p-4 sm:p-6">
        <div className="flex flex-col gap-2">
          <FieldLabel
            htmlFor={ids.title}
            missing={isMissing("role")}
            basis={basis("role")}
          >
            Rola
          </FieldLabel>
          <Input
            id={ids.title}
            value={form.title}
            onChange={(e) => set("title", e.target.value, "role")}
            placeholder="np. Senior Java Developer"
            className={cn(isMissing("role") && MISSING_RING)}
          />
          <MissingNote show={isMissing("role")} />
        </div>

        <TagListInput
          label="Must-have"
          values={form.must}
          onChange={(v) => set("must", v, "must")}
          basis={basis("must")}
          tone="primary"
          missing={isMissing("must")}
          placeholder="np. Java, Spring Boot — Enter dodaje"
        />
        <TagListInput
          label="Mile widziane"
          values={form.nice}
          onChange={(v) => set("nice", v, "nice")}
          basis={basis("nice")}
          tone="muted"
          placeholder="opcjonalnie"
        />

        <div className="grid gap-4 md:grid-flow-row-dense md:grid-cols-2 lg:grid-cols-4">
          <div className="flex flex-col gap-2">
            <FieldLabel
              htmlFor={ids.rate}
              missing={isMissing("budget")}
              basis={basis("rate")}
            >
              Budżet PLN/h
            </FieldLabel>
            <Input
              id={ids.rate}
              inputMode="decimal"
              value={form.rateBudget}
              onChange={(e) => set("rateBudget", e.target.value, "rate")}
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
                "flex min-h-10 items-center gap-0.5 rounded-lg bg-muted p-0.5",
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
                      "min-h-9 min-w-0 flex-1 rounded-md px-1 text-sm leading-tight transition-colors",
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
            basis={basis("about")}
          >
            O projekcie
          </FieldLabel>
          <Textarea
            id={ids.about}
            rows={2}
            value={form.about}
            onChange={(e) => set("about", e.target.value, "about")}
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
          "flex flex-col gap-3 rounded-xl border border-border bg-card p-4 sm:p-6",
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

      <ChampionProposalSection form={form} onChange={onChange} />
    </div>
  );
}

/**
 * „Reszta profilu Championa — propozycja”: to, co Luna zaproponowała poza
 * minimum do searchu. Nic tu nie blokuje „Utwórz” — wszystko trafia do
 * profilu i da się poprawić później w zakładce Championa.
 */
function ChampionProposalSection({
  form,
  onChange,
}: {
  form: IntakeForm;
  onChange: (updater: (form: IntakeForm) => IntakeForm) => void;
}) {
  const [open, setOpen] = useState(true);
  const ids = {
    keywords: useId(),
    companies: useId(),
    selling: useId(),
    language: useId(),
    contract: useId(),
  };
  const set = <K extends keyof IntakeForm>(
    key: K,
    value: IntakeForm[K],
    provenanceKey?: ProvenanceKey,
  ) =>
    onChange((f) => {
      const next = { ...f, [key]: value };
      return provenanceKey ? markEdited(next, provenanceKey) : next;
    });
  const basis = (key: ProvenanceKey) => form.provenance?.[key];
  const filled = [
    hasExperience(form.experience),
    Boolean(form.searchKeywords.trim() || form.targetCompanies.trim()),
    form.disqualifiers.length > 0,
    Boolean(form.sellingPoints.trim()),
    form.askClient.length > 0,
  ].filter(Boolean).length;

  return (
    <section
      aria-labelledby="new-job-proposal"
      className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4 sm:p-6"
      data-testid="new-job-champion-proposal"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center justify-between gap-2 text-left"
      >
        <span className="inline-flex items-center gap-2">
          {open ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          )}
          <span id="new-job-proposal" className="text-base font-semibold text-foreground">
            Reszta profilu Championa — propozycja
          </span>
        </span>
        <span className="text-xs text-muted-foreground">
          {filled} z 5 grup wypełnione · nie blokuje utworzenia
        </span>
      </button>

      {open ? (
        <div className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <FieldLabel basis={basis("experience")} hint="dziedzina, certyfikaty, regulacje">
              Doświadczenie poza stackiem
            </FieldLabel>
            <ChampionExperienceFields
              value={form.experience}
              onChange={(experience) => set("experience", experience, "experience")}
              showNotes={false}
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="flex flex-col gap-2">
              <FieldLabel htmlFor={ids.keywords} basis={basis("search_keywords")}>
                Frazy do wyszukiwarki
              </FieldLabel>
              <Textarea
                id={ids.keywords}
                rows={2}
                value={form.searchKeywords}
                onChange={(e) =>
                  set("searchKeywords", e.target.value, "search_keywords")
                }
                placeholder="np. tester manualny, płatności kartowe, ISTQB"
              />
            </div>
            <div className="flex flex-col gap-2">
              <FieldLabel htmlFor={ids.companies} basis={basis("target_companies")}>
                Firmy docelowe
              </FieldLabel>
              <Textarea
                id={ids.companies}
                rows={2}
                value={form.targetCompanies}
                onChange={(e) =>
                  set("targetCompanies", e.target.value, "target_companies")
                }
                placeholder="opcjonalnie"
              />
            </div>
          </div>

          <TagListInput
            label="Kogo odrzucamy od razu"
            values={form.disqualifiers}
            onChange={(v) => set("disqualifiers", v, "disqualifiers")}
            basis={basis("disqualifiers")}
            tone="muted"
            placeholder="opcjonalnie — np. brak polskiego"
          />

          <div className="flex flex-col gap-2">
            <FieldLabel htmlFor={ids.selling} basis={basis("selling_points")}>
              Co przekona kandydata
            </FieldLabel>
            <Textarea
              id={ids.selling}
              rows={2}
              value={form.sellingPoints}
              onChange={(e) => set("sellingPoints", e.target.value, "selling_points")}
              placeholder="np. nowy zespół, greenfield, 4 dni zdalnie"
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="flex flex-col gap-2">
              <FieldLabel htmlFor={ids.language} hint="opcjonalnie">
                Język pracy
              </FieldLabel>
              <Input
                id={ids.language}
                value={form.language}
                onChange={(e) => set("language", e.target.value)}
                placeholder="np. PL, EN B2"
              />
            </div>
            <div className="flex flex-col gap-2">
              <FieldLabel htmlFor={ids.contract} hint="opcjonalnie">
                Długość projektu
              </FieldLabel>
              <Input
                id={ids.contract}
                value={form.contractLength}
                onChange={(e) => set("contractLength", e.target.value)}
                placeholder="np. 6 mies. z przedłużeniem"
              />
            </div>
          </div>

          <AskClientEditor
            items={form.askClient}
            basis={basis("ask_client")}
            onChange={(askClient) => set("askClient", askClient, "ask_client")}
          />

          <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
            Po utworzeniu AI podsumuje historię klienta — za co odrzucał kandydatów
            i o co pytał na rozmowach. Zobaczysz to w profilu Championa, w sekcji
            „8 · Wiedza z rozmów”.
          </p>
        </div>
      ) : null}
    </section>
  );
}

function AskClientEditor({
  items,
  basis,
  onChange,
}: {
  items: IntakeForm["askClient"];
  basis?: FieldBasis;
  onChange: (items: IntakeForm["askClient"]) => void;
}) {
  return (
    <div className="flex flex-col gap-2" data-testid="new-job-ask-client">
      <FieldLabel basis={basis} hint="trafi do profilu jako lista kontrolna">
        Do dopytania u klienta
      </FieldLabel>
      {items.length === 0 ? (
        <p className="text-xs text-muted-foreground">Mail odpowiada na wszystko — albo dopisz pytanie.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {items.map((item, i) => (
            <li key={item.key} className="flex items-center gap-2">
              <Input
                aria-label={`Pytanie do klienta ${i + 1}`}
                value={item.text}
                onChange={(e) =>
                  onChange(
                    items.map((it) =>
                      it.key === item.key ? { ...it, text: e.target.value } : it,
                    ),
                  )
                }
              />
              <button
                type="button"
                aria-label={`Usuń pytanie do klienta ${i + 1}`}
                className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                onClick={() => onChange(items.filter((it) => it.key !== item.key))}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        onClick={() => onChange([...items, { key: newQuestionKey(), text: "" }])}
        className="inline-flex items-center gap-1.5 self-start text-sm font-medium text-primary hover:underline"
      >
        <Plus className="h-4 w-4" /> Dodaj pytanie do klienta
      </button>
    </div>
  );
}
