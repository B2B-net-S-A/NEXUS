"use client";

/**
 * Krok 2 strony `/jobs/new` w sześciu sekcjach (decyzje Artura 02.10.2026,
 * makiety https://claude.ai/artifact/UPDv1tSQBeo5t9kLW6WJoH): 1 Nazwa ·
 * 2 Wymagania (słowa kluczowe) · 3 Warunki · 4 O projekcie · 5 Pytania do
 * kandydata · 6 Kategoria i zespół (`NewJobTeamStep`). Pasek sekcji nad
 * formularzem mówi, w której sekcji czegoś brakuje.
 */

import { useId, useState, type KeyboardEvent, type ReactNode } from "react";
import { Check, ChevronDown, ChevronRight, Plus, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { HiringManagerCombobox } from "@/components/jobs/HiringManagerCombobox";
import { OfficeDaysField } from "@/components/jobs/OfficeDaysField";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { ChampionExperienceFields } from "@/components/champion/ChampionExperienceFields";
import { RequirementRowsEditor } from "@/components/champion/RequirementRowsEditor";
import { hasExperience } from "@/lib/champion-experience";
import type { RowCriticalState } from "@/lib/requirement-rows";
import {
  FIELD_BASIS_LABEL,
  FORM_SECTIONS,
  MISSING_LABEL,
  approveQuestions,
  clientReferenceFor,
  editQuestion,
  effectiveWorkingTitle,
  filledQuestions,
  joinCities,
  markEdited,
  missingBySection,
  newManualQuestion,
  newQuestionKey,
  sectionAnchor,
  unapprovedQuestions,
  type FieldBasis,
  type FormSection,
  type IntakeForm,
  type ProvenanceKey,
  type IntakeQuestionForm,
  type MissingCode,
  type QuestionOrigin,
  type RemotePolicyValue,
  splitCities,
} from "@/lib/job-request-intake";
import { blurNumberInputOnWheel } from "@/lib/number-input";

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

export const BUDGET_HELP_TEXT =
  "Rekruter widzi go przy kandydatach jako plakietkę „ponad budżet”. Nikogo nie ukrywa.";

export const DEAL_BREAKER_REQUIRED_TEXT =
  "Wpisz odpowiedź, która dyskwalifikuje kandydata — bez niej rekrutacja nie trafi do searchu.";

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
  id,
  children,
  hint,
  missing,
  basis,
}: {
  htmlFor?: string;
  /** Dla pól bez `<label for>` (combobox) — cel `aria-labelledby`. */
  id?: string;
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
          <span id={id} className="text-sm font-medium text-foreground">
            {children}
          </span>
        )}
        <ProvenanceChip basis={basis} />
      </span>
      {!missing && hint ? (
        <span className="text-xs text-muted-foreground">{hint}</span>
      ) : null}
    </div>
  );
}

/** Pole lat: puste albo 0–40 (to samo co `seniority_min_years` w Championie). */
function parseYears(raw: string): number | null {
  if (!raw.trim()) return null;
  const n = Math.round(Number(raw));
  if (!Number.isFinite(n)) return null;
  return Math.min(40, Math.max(0, n));
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
        {/* Runda 12 (FRONTB): `w-0` — bez szerokości pole liczyło minimum
            kolumny z domyślnego `size=20` (~270 px, zależne od fontu systemu),
            a formularz na 360 px miał kilka px zapasu. */}
        <input
          id={inputId}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={commit}
          placeholder={values.length === 0 ? placeholder : "dodaj…"}
          className="h-7 w-0 min-w-[8rem] flex-1 bg-transparent px-1 text-sm text-foreground outline-hidden placeholder:text-muted-foreground"
        />
      </div>
      <MissingNote show={!!missing} />
    </div>
  );
}

type FormUpdater = (updater: (form: IntakeForm) => IntakeForm) => void;

function SectionCard({
  section,
  number,
  title,
  hint,
  warn,
  children,
}: {
  section: FormSection;
  number: number;
  title: string;
  hint?: string;
  warn?: boolean;
  children: ReactNode;
}) {
  const id = sectionAnchor(section);
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      // Pasek sekcji jest przyklejony — `scroll-mt` zostawia mu miejsce.
      className={cn(
        "flex scroll-mt-28 flex-col gap-5 rounded-xl border border-border bg-card p-4 sm:p-6",
        warn && "border-warning",
      )}
    >
      <div>
        <h2 id={`${id}-title`} className="text-base font-semibold text-foreground">
          {number} · {title}
        </h2>
        {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      </div>
      {children}
    </section>
  );
}

/**
 * Pasek sekcji nad formularzem: ✓ przy sekcji bez braków, liczba braków przy
 * pozostałych. Kliknięcie przewija do sekcji. Stopka strony mówi to samo
 * listą — pasek pokazuje, GDZIE to poprawić.
 */
export function NewJobSectionNav({ missing }: { missing: readonly MissingCode[] }) {
  const bySection = missingBySection(missing);
  return (
    <nav
      aria-label="Sekcje formularza"
      className="sticky top-0 z-10 -mx-1 flex gap-1.5 overflow-x-auto rounded-xl border border-border bg-card/95 p-1.5 backdrop-blur supports-[backdrop-filter]:bg-card/80 [@media(max-height:600px)]:static"
    >
      {FORM_SECTIONS.map((section, index) => {
        const codes = bySection[section.id];
        const done = codes.length === 0;
        return (
          <a
            key={section.id}
            href={`#${sectionAnchor(section.id)}`}
            title={done ? undefined : `Brakuje: ${codes.map((c) => MISSING_LABEL[c]).join(", ")}`}
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors hover:bg-accent",
              done ? "text-muted-foreground" : "bg-warning-muted text-warning-muted-foreground",
            )}
            onClick={(event) => {
              const target = document.getElementById(sectionAnchor(section.id));
              if (!target) return;
              event.preventDefault();
              target.scrollIntoView?.({ behavior: "smooth", block: "start" });
            }}
          >
            {index + 1} {section.label}
            {done ? (
              <Check className="h-3.5 w-3.5 text-success" aria-label="gotowe" />
            ) : (
              <span
                className="flex h-4 min-w-4 items-center justify-center rounded-full bg-warning px-1 text-[11px] font-bold text-warning-foreground"
                aria-label={`brakuje: ${codes.length}`}
              >
                {codes.length}
              </span>
            )}
          </a>
        );
      })}
    </nav>
  );
}

/**
 * Numer u klienta bez osobnego pola (02.10.2026): system czyta go z nazwy
 * i mówi, co rozpoznał. „To nie ten numer” pozwala wpisać inny albo żaden.
 */
function ClientReferenceLine({ form, onChange }: { form: IntakeForm; onChange: FormUpdater }) {
  const inputId = useId();
  const reference = clientReferenceFor(form);
  if (form.referenceOverride != null) {
    return (
      <div className="flex flex-wrap items-center gap-2" data-testid="client-reference">
        <label htmlFor={inputId} className="text-xs font-medium text-foreground">
          Numer u klienta
        </label>
        <Input
          id={inputId}
          value={form.referenceOverride}
          maxLength={120}
          onChange={(e) => onChange((f) => ({ ...f, referenceOverride: e.target.value }))}
          placeholder="np. ZOB 48213 — puste = bez numeru"
          className="h-8 w-56"
        />
        <button
          type="button"
          className="text-xs font-medium text-primary hover:underline"
          onClick={() => onChange((f) => ({ ...f, referenceOverride: null }))}
        >
          Wróć do numeru z nazwy
        </button>
      </div>
    );
  }
  return (
    <p className="text-xs text-muted-foreground" data-testid="client-reference">
      {reference ? (
        <>
          Numer u klienta rozpoznany:{" "}
          <strong className="font-semibold text-foreground">{reference}</strong> — trafi do CV
          i nazwy pliku.{" "}
        </>
      ) : (
        <>Nie widzę numeru zapytania w nazwie. </>
      )}
      <button
        type="button"
        className="font-medium text-primary hover:underline"
        onClick={() => onChange((f) => ({ ...f, referenceOverride: reference }))}
      >
        {reference ? "To nie ten numer" : "Wpisz numer"}
      </button>
    </p>
  );
}

/**
 * Tytuł dla rekrutera (0380) składa się sam z roli, wymagań, lat i dziedziny —
 * ta sama reguła co na serwerze. Do 02.10 był osobnym polem, które powtarzało
 * wymagania; teraz to podgląd z „Zmień”. Nigdy nie idzie do klienta.
 */
function WorkingTitleLine({ form, onChange }: { form: IntakeForm; onChange: FormUpdater }) {
  const id = useId();
  const value = effectiveWorkingTitle(form);
  if (!form.workingTitleTouched) {
    return (
      <div className="flex flex-col gap-1" data-testid="working-title-field">
        <span className="text-xs text-muted-foreground">
          Zespół zobaczy na listach (składa się samo z wymagań)
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-foreground">
            {value || "uzupełni się z roli i słów kluczowych"}
          </span>
          <button
            type="button"
            className="text-xs font-medium text-primary hover:underline"
            onClick={() =>
              onChange((f) => ({ ...f, workingTitle: value, workingTitleTouched: true }))
            }
          >
            Zmień
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2" data-testid="working-title-field">
      <FieldLabel htmlFor={id} basis="manual" hint="widzi go tylko zespół">
        Tytuł dla zespołu
      </FieldLabel>
      <Input
        id={id}
        value={form.workingTitle}
        maxLength={255}
        onChange={(e) => onChange((f) => ({ ...f, workingTitle: e.target.value }))}
      />
      <button
        type="button"
        className="self-start text-xs font-medium text-primary hover:underline"
        onClick={() => onChange((f) => ({ ...f, workingTitle: "", workingTitleTouched: false }))}
      >
        Wróć do podpowiedzi
      </button>
    </div>
  );
}

interface NewJobReviewFormProps {
  form: IntakeForm;
  onChange: FormUpdater;
  missing: MissingCode[];
  /** Po odczycie przez AI braki są podświetlane; w trybie ręcznym nie. */
  highlightMissing: boolean;
  /** Klient z kroku 1 — lista kontaktów do wyboru hiring managera. */
  clientId: number | null;
  /** Harness `/preview/new-job`: bez zapytania o liczbę osób w bazie. */
  countEnabled?: boolean;
  /** Co serwer wie o wierszach wymagań (`useRowCriticalInfo`). */
  criticalInfo: RowCriticalState;
  /** Sekcja 6 „Kategoria i zespół” (`NewJobTeamStep`) — stoi przed „Dodatkowe”. */
  team?: ReactNode;
}

/** Krok 2 strony `/jobs/new`: sekcje 1–5 i „Dodatkowe”. */
export function NewJobReviewForm({
  form,
  onChange,
  missing,
  highlightMissing,
  clientId,
  countEnabled = true,
  criticalInfo,
  team,
}: NewJobReviewFormProps) {
  const ids = {
    hiringManager: useId(),
    title: useId(),
    deadline: useId(),
    deadlineTime: useId(),
    deadlineNotProvided: useId(),
    headcount: useId(),
    clientTitle: useId(),
    rate: useId(),
    days: useId(),
    years: useId(),
    language: useId(),
    start: useId(),
    contract: useId(),
    about: useId(),
    resp: useId(),
    selling: useId(),
  };
  const isMissing = (code: MissingCode) => highlightMissing && missing.includes(code);
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
  const officeNeeded = form.remotePolicy !== "" && form.remotePolicy !== "remote";

  return (
    <div className="flex flex-col gap-4">
      <SectionCard
        section="name"
        number={1}
        title="Nazwa"
        warn={isMissing("role") || isMissing("hiring_manager")}
      >
        <div className="flex flex-col gap-2">
          <FieldLabel
            htmlFor={ids.clientTitle}
            basis={basis("client_title")}
            hint="tak, jak napisał klient"
          >
            Nazwa od klienta, razem z numerem
          </FieldLabel>
          <Input
            id={ids.clientTitle}
            value={form.clientTitle}
            onChange={(e) => set("clientTitle", e.target.value, "client_title")}
            placeholder="np. Programista Java (ZOB 48213)"
          />
          <ClientReferenceLine form={form} onChange={onChange} />
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="flex flex-col gap-2">
            <FieldLabel htmlFor={ids.title} missing={isMissing("role")} basis={basis("role")}>
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
          {/* 25.09.2026: kto zamawia po stronie klienta — z listy kontaktów
              albo wpisany; nowa osoba trafi do kontaktów klienta przy zapisie. */}
          <div className="flex flex-col gap-2" data-testid="new-job-hiring-manager">
            <FieldLabel
              id={ids.hiringManager}
              basis={basis("hiring_manager")}
              missing={isMissing("hiring_manager")}
            >
              Hiring manager
            </FieldLabel>
            <div
              className={cn(
                "rounded-lg",
                isMissing("hiring_manager") && MISSING_RING,
              )}
            >
              <HiringManagerCombobox
                clientId={clientId}
                value={form.hiringManager}
                onChange={(value) =>
                  onChange((f) =>
                    markEdited(
                      {
                        ...f,
                        hiringManager: value,
                        // Wybrana osoba zdejmuje „Klient nie podał”.
                        hiringManagerNotProvided: value ? false : f.hiringManagerNotProvided,
                      },
                      "hiring_manager",
                    ),
                  )
                }
                labelledBy={ids.hiringManager}
                notProvided={form.hiringManagerNotProvided}
                onNotProvidedChange={(notProvided) =>
                  onChange((f) => ({
                    ...f,
                    hiringManagerNotProvided: notProvided,
                    hiringManager: notProvided ? null : f.hiringManager,
                  }))
                }
              />
            </div>
            <MissingNote show={isMissing("hiring_manager")} />
          </div>
        </div>

        <WorkingTitleLine form={form} onChange={onChange} />
      </SectionCard>

      <SectionCard
        section="requirements"
        number={2}
        title="Wymagania — słowa kluczowe"
        hint="Jedna lista. Po tych słowach szukamy w bazie, a krytyczne ukrywają w propozycjach AI osoby, które ich nie mają. Słowa w jednym wierszu to warianty (wystarczy jedno)."
        warn={isMissing("must") || isMissing("critical")}
      >
        <div className="flex flex-col gap-2" data-testid="new-job-requirements">
          <div className="flex justify-end">
            <ProvenanceChip basis={basis("requirements")} />
          </div>
          <RequirementRowsEditor
            rows={form.rows}
            onRowsChange={(rows) => onChange((f) => markEdited({ ...f, rows }, "requirements"))}
            noCritical={form.noCritical}
            onNoCriticalChange={(noCritical) => onChange((f) => ({ ...f, noCritical }))}
            exclude={form.searchExclude}
            onExcludeChange={(searchExclude) => onChange((f) => ({ ...f, searchExclude }))}
            critical={criticalInfo}
            invalid={isMissing("must")}
            criticalMissing={isMissing("critical")}
            countEnabled={countEnabled}
          />
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="flex flex-col gap-2">
            <FieldLabel htmlFor={ids.years} hint="opcjonalnie">
              Lata doświadczenia
            </FieldLabel>
            <Input
              id={ids.years}
              type="number"
              onWheel={blurNumberInputOnWheel}
              min={0}
              max={40}
              value={form.seniorityYears ?? ""}
              onChange={(e) => set("seniorityYears", parseYears(e.target.value))}
              placeholder="np. 5"
            />
          </div>
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
        </div>

        {form.descriptive.length > 0 || form.intakeNotes.length > 0 ? (
          <details className="rounded-lg bg-muted px-3 py-2 text-sm" data-testid="new-job-descriptive">
            <summary className="cursor-pointer font-medium text-foreground">
              Zdania klienta, które nie są słowami kluczowymi ({form.descriptive.length})
            </summary>
            <p className="mt-2 text-xs text-muted-foreground">
              Zostają w profilu dla rekrutera i generatora CV, ale nie filtrują kandydatów.
            </p>
            <ul className="mt-2 flex flex-col gap-1.5">
              {form.descriptive.map((sentence) => (
                <li key={sentence} className="flex items-start gap-2 text-sm text-foreground">
                  <span className="min-w-0 flex-1">„{sentence}”</span>
                  <button
                    type="button"
                    aria-label={`Usuń zdanie: ${sentence}`}
                    className="hit-area rounded p-0.5 text-muted-foreground hover:bg-card hover:text-foreground"
                    onClick={() =>
                      onChange((f) => ({
                        ...f,
                        descriptive: f.descriptive.filter((item) => item !== sentence),
                      }))
                    }
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
            {form.intakeNotes.length > 0 && (
              <ul
                className="mt-2 flex flex-col gap-1 border-t border-border pt-2 text-xs text-muted-foreground"
                aria-label="Uwagi z odczytu maila"
                data-testid="new-job-intake-notes"
              >
                {form.intakeNotes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            )}
          </details>
        ) : null}
      </SectionCard>

      <SectionCard
        section="terms"
        number={3}
        title="Warunki"
        warn={
          isMissing("budget") ||
          isMissing("work_mode") ||
          isMissing("office_days") ||
          isMissing("office_city") ||
          isMissing("deadline") ||
          isMissing("headcount")
        }
      >
        <div className="grid gap-4 md:grid-flow-row-dense md:grid-cols-2 lg:grid-cols-4">
          <div className="flex flex-col gap-2">
            <FieldLabel htmlFor={ids.rate} missing={isMissing("budget")} basis={basis("rate")}>
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
              <span className="text-xs text-muted-foreground">{form.rateNote}</span>
            )}
            <span className="text-xs text-muted-foreground">{BUDGET_HELP_TEXT}</span>
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
                    onClick={() =>
                      onChange((f) =>
                        // Dni w miesiącu są tylko przy hybrydzie (0407).
                        mode.value !== "hybrid" && f.onsiteDaysPeriod === "month"
                          ? {
                              ...f,
                              remotePolicy: mode.value,
                              onsiteDays: "",
                              onsiteDaysPeriod: "week",
                            }
                          : { ...f, remotePolicy: mode.value },
                      )
                    }
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
            <FieldLabel htmlFor={ids.days} missing={officeNeeded && isMissing("office_days")}>
              Dni w biurze
            </FieldLabel>
            <OfficeDaysField
              id={ids.days}
              disabled={!officeNeeded}
              allowMonth={form.remotePolicy === "hybrid"}
              value={form.onsiteDays}
              period={form.onsiteDaysPeriod}
              onValueChange={(v) => set("onsiteDays", v)}
              onPeriodChange={(p) => set("onsiteDaysPeriod", p)}
              inputClassName={cn(officeNeeded && isMissing("office_days") && MISSING_RING)}
            />
            <MissingNote show={officeNeeded && isMissing("office_days")} />
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="flex flex-col gap-2" data-testid="new-job-deadline">
            <FieldLabel
              htmlFor={ids.deadline}
              missing={isMissing("deadline")}
              basis={basis("deadline")}
            >
              Termin
            </FieldLabel>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                id={ids.deadline}
                type="date"
                value={form.deadline}
                disabled={form.deadlineNotProvided}
                onChange={(e) =>
                  onChange((f) =>
                    markEdited(
                      {
                        ...f,
                        deadline: e.target.value,
                        deadlineTime: e.target.value ? f.deadlineTime : "",
                        deadlineNotProvided: e.target.value ? false : f.deadlineNotProvided,
                      },
                      "deadline",
                    ),
                  )
                }
                className={cn("w-0 min-w-[10rem] flex-1", isMissing("deadline") && MISSING_RING)}
              />
              <Input
                id={ids.deadlineTime}
                type="time"
                aria-label="Godzina terminu (opcjonalnie)"
                value={form.deadlineTime}
                disabled={form.deadlineNotProvided || !form.deadline}
                onChange={(e) =>
                  onChange((f) => markEdited({ ...f, deadlineTime: e.target.value }, "deadline"))
                }
                className="w-32"
              />
            </div>
            <label
              htmlFor={ids.deadlineNotProvided}
              className="inline-flex cursor-pointer items-center gap-2 text-sm text-foreground"
            >
              <Checkbox
                id={ids.deadlineNotProvided}
                checked={form.deadlineNotProvided}
                onCheckedChange={(checked) =>
                  onChange((f) => ({
                    ...f,
                    deadlineNotProvided: checked === true,
                    deadline: checked === true ? "" : f.deadline,
                    deadlineTime: checked === true ? "" : f.deadlineTime,
                  }))
                }
              />
              Klient nie podał
            </label>
            <MissingNote show={isMissing("deadline")} />
          </div>
          <div className="flex flex-col gap-2">
            <FieldLabel
              htmlFor={ids.headcount}
              missing={isMissing("headcount")}
              basis={basis("headcount")}
            >
              Liczba osób
            </FieldLabel>
            <Input
              id={ids.headcount}
              type="number"
              inputMode="numeric"
              onWheel={blurNumberInputOnWheel}
              min={1}
              max={99}
              value={form.headcount}
              onChange={(e) =>
                onChange((f) => markEdited({ ...f, headcount: e.target.value }, "headcount"))
              }
              className={cn(isMissing("headcount") && MISSING_RING)}
            />
            <MissingNote show={isMissing("headcount")} />
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {officeNeeded && (
            <TagListInput
              label="Miasta biura"
              values={splitCities(form.city)}
              onChange={(v) => set("city", joinCities(v))}
              tone="muted"
              missing={isMissing("office_city")}
              placeholder="np. Warszawa, Gdańsk — Enter dodaje"
            />
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
      </SectionCard>

      <SectionCard section="project" number={4} title="O projekcie" warn={isMissing("context")}>
        <div className="flex flex-col gap-2">
          <FieldLabel
            htmlFor={ids.about}
            missing={isMissing("context")}
            hint="2 zdania"
            basis={basis("about")}
          >
            Co to za projekt
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
        <div className="flex flex-col gap-2">
          <FieldLabel htmlFor={ids.selling} basis={basis("selling_points")} hint="opcjonalnie">
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
      </SectionCard>

      <QuestionsSection form={form} onChange={onChange} isMissing={isMissing} />

      {team}

      <AdditionalSection form={form} onChange={onChange} />
    </div>
  );
}

/**
 * Pytania do kandydata: pytanie, dobra odpowiedź i odpowiedź, która odpada.
 * AI proponuje komplet; Delivery Lead poprawia albo zatwierdza — bez tego
 * i bez deal breakera przy każdym pytaniu rekrutacja nie idzie do searchu.
 */
function QuestionsSection({
  form,
  onChange,
  isMissing,
}: {
  form: IntakeForm;
  onChange: FormUpdater;
  isMissing: (code: MissingCode) => boolean;
}) {
  const filled = filledQuestions(form);
  const pending = unapprovedQuestions(form);
  const approvable = pending.filter((q) => q.dealBreaker.trim());
  const warn =
    isMissing("questions") || isMissing("deal_breaker") || isMissing("questions_review");
  const edit = (
    key: string,
    patch: Partial<Pick<IntakeQuestionForm, "question" | "idealAnswer" | "dealBreaker">>,
  ) => onChange((f) => markEdited(editQuestion(f, key, patch), "questions"));

  return (
    <SectionCard
      section="questions"
      number={5}
      title="Pytania do kandydata"
      hint="AI proponuje pytanie, dobrą odpowiedź i odpowiedź, która dyskwalifikuje. Popraw albo zatwierdź."
      warn={warn}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span
          className={cn(
            "text-xs",
            filled.length < 2 || pending.length > 0
              ? "font-medium text-warning-muted-foreground"
              : "text-muted-foreground",
          )}
          aria-live="polite"
        >
          {filled.length < 2
            ? `${filled.length} z 2 wymaganych`
            : pending.length > 0
              ? `Zatwierdzone ${filled.length - pending.length} z ${filled.length}`
              : `${questionsLabel(filled.length)} — wszystkie zatwierdzone`}
        </span>
        {pending.length > 0 ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={approvable.length === 0}
            title={
              approvable.length === 0
                ? "Najpierw wpisz przy pytaniach odpowiedź, która odpada"
                : undefined
            }
            onClick={() => onChange((f) => approveQuestions(f))}
          >
            Zatwierdź wszystkie
          </Button>
        ) : null}
      </div>
      {form.questions.map((q, i) => {
        const n = i + 1;
        const noBreaker = q.question.trim().length > 0 && !q.dealBreaker.trim();
        return (
          <div
            key={q.key}
            className={cn(
              "flex flex-col gap-2 rounded-lg border p-3",
              q.approved ? "border-border" : "border-dashed border-primary/40 bg-primary/5",
            )}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">
                Pytanie {n} · {ORIGIN_LABEL[q.origin]}
              </span>
              <span className="flex items-center gap-1">
                {q.approved ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-success-muted px-2 py-0.5 text-[11px] font-medium text-success-muted-foreground">
                    <Check className="h-3 w-3" aria-hidden /> Zatwierdzone
                  </span>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={!q.question.trim() || noBreaker}
                    title={noBreaker ? "Najpierw wpisz odpowiedź, która odpada" : undefined}
                    aria-label={`Zatwierdź pytanie ${n}`}
                    onClick={() => onChange((f) => approveQuestions(f, q.key))}
                  >
                    Zatwierdź
                  </Button>
                )}
                <button
                  type="button"
                  aria-label={`Usuń pytanie ${n}`}
                  className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                  onClick={() =>
                    onChange((f) => ({
                      ...f,
                      questions: f.questions.filter((item) => item.key !== q.key),
                    }))
                  }
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </span>
            </div>
            <Input
              aria-label={`Treść pytania ${n}`}
              value={q.question}
              onChange={(e) => edit(q.key, { question: e.target.value })}
              placeholder="Pytanie do kandydata"
            />
            <div className="grid gap-2 md:grid-cols-2">
              <label className="flex flex-col gap-1 text-xs font-medium text-success-muted-foreground">
                Dobra odpowiedź
                <Textarea
                  aria-label={`Dobra odpowiedź na pytanie ${n}`}
                  rows={2}
                  value={q.idealAnswer}
                  onChange={(e) => edit(q.key, { idealAnswer: e.target.value })}
                  placeholder="Czego szukać w odpowiedzi"
                  className="font-normal text-foreground"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs font-medium text-destructive-muted-foreground">
                Odpada, gdy… (wymagane)
                <Textarea
                  aria-label={`Odpowiedź, która odpada, na pytanie ${n}`}
                  rows={2}
                  value={q.dealBreaker}
                  onChange={(e) => edit(q.key, { dealBreaker: e.target.value })}
                  placeholder="Odpowiedź, która dyskwalifikuje kandydata"
                  className={cn(
                    "font-normal text-foreground",
                    noBreaker && isMissing("deal_breaker") && MISSING_RING,
                  )}
                />
              </label>
            </div>
            {noBreaker && isMissing("deal_breaker") ? (
              <span className="text-xs font-medium text-warning-muted-foreground">
                {DEAL_BREAKER_REQUIRED_TEXT}
              </span>
            ) : null}
          </div>
        );
      })}
      <button
        type="button"
        onClick={() =>
          onChange((f) => ({ ...f, questions: [...f.questions, newManualQuestion()] }))
        }
        className="inline-flex items-center gap-1.5 self-start text-sm font-medium text-primary hover:underline"
      >
        <Plus className="h-4 w-4" /> Dodaj pytanie
      </button>
    </SectionCard>
  );
}

/**
 * „Dodatkowe — nie blokuje utworzenia”: to, co AI zaproponowało poza sześcioma
 * sekcjami. Wszystko trafia do profilu i da się poprawić później w zakładce
 * Championa.
 */
function AdditionalSection({ form, onChange }: { form: IntakeForm; onChange: FormUpdater }) {
  const [open, setOpen] = useState(false);
  const ids = { companies: useId(), body: useId() };
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
  const summary = [
    form.targetCompanies.trim() ? "firmy docelowe" : null,
    form.disqualifiers.length > 0 ? `kogo odrzucamy od razu (${form.disqualifiers.length})` : null,
    form.askClient.length > 0 ? `do dopytania u klienta (${form.askClient.length})` : null,
    hasExperience(form.experience) ? "dziedziny, certyfikaty i regulacje" : null,
  ].filter(Boolean);

  return (
    <section
      aria-labelledby="new-job-additional"
      className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4 sm:p-6"
      data-testid="new-job-additional"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={ids.body}
        className="flex flex-wrap items-center justify-between gap-2 text-left"
      >
        <span className="inline-flex items-center gap-2">
          {open ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          )}
          <span id="new-job-additional" className="text-base font-semibold text-foreground">
            Dodatkowe — nie blokuje utworzenia
          </span>
        </span>
        <span className="text-xs text-muted-foreground">
          {summary.length > 0
            ? summary.join(" · ")
            : "firmy docelowe · kogo odrzucamy od razu · do dopytania u klienta · certyfikaty i regulacje"}
        </span>
      </button>

      <div id={ids.body} hidden={!open} className={cn(open && "flex flex-col gap-5")}>
        <div className="flex flex-col gap-2">
          <FieldLabel basis={basis("experience")} hint="dziedzina, certyfikaty, regulacje">
            Doświadczenie poza słowami kluczowymi
          </FieldLabel>
          <ChampionExperienceFields
            value={form.experience}
            onChange={(experience) => set("experience", experience, "experience")}
            showNotes={false}
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
            onChange={(e) => set("targetCompanies", e.target.value, "target_companies")}
            placeholder="opcjonalnie"
          />
        </div>

        <TagListInput
          label="Kogo odrzucamy od razu"
          values={form.disqualifiers}
          onChange={(v) => set("disqualifiers", v, "disqualifiers")}
          basis={basis("disqualifiers")}
          tone="muted"
          placeholder="opcjonalnie — np. brak polskiego"
        />

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
