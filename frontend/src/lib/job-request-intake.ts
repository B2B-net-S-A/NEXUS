/**
 * Nowa rekrutacja z requestu klienta — strona `/jobs/new`.
 *
 * Czysta logika (bez Reacta i sieci): kształt formularza, braki wobec
 * „Przekaż do searchu”, payloady zapisu i podświetlenie requestu.
 *
 * Braki są LUSTREM backendu (`services/job_readiness.py`: brief + rubryki,
 * i `services/job_request_intake.py::missing_fields`). Rozjazd znaczyłby
 * przycisk aktywny, który kończy się 422 z serwera, albo odwrotnie.
 */

import type { ChampionExperience, ExperienceItem, ExperienceKind } from "@/lib/api";
import {
  hiringManagerRequestBody,
  type HiringManagerChoice,
} from "@/lib/hiring-manager";
import { composeWorkingTitle } from "@/lib/job-names";
import { sanitizeKeyword } from "@/lib/keyword-requirements";
import {
  criticalDecision,
  criticalDecisionMissing,
  mustHeads,
  niceHeads,
  rowsFromStored,
  toStoredRows,
  type RequirementRowForm,
  type RowCriticalInfo,
  type StoredRequirementRow,
} from "@/lib/requirement-rows";
import {
  officeDaysFields,
  officeDaysFormValue,
  type OfficeDaysPeriod,
} from "@/lib/office-days";

export type RemotePolicyValue = "remote" | "hybrid" | "onsite";

/**
 * Skąd pochodzi wartość pola (od v2 odczytu, 09.2026): „z maila” (fakt
 * z cytatem), „z podobnej rekrutacji” (kontekst klienta), „propozycja AI”,
 * „wpisane” (DL zmienił pole). Chip przy polu mówi to DL, zanim zapisze.
 */
export type FieldBasis = "request" | "client_history" | "ai" | "manual";

export const FIELD_BASIS_LABEL: Record<FieldBasis, string> = {
  request: "z maila",
  client_history: "z podobnej rekrutacji",
  ai: "propozycja AI",
  manual: "wpisane",
};

/** Klucze pól formularza, przy których pokazujemy źródło. */
export type ProvenanceKey =
  | "role"
  | "requirements"
  | "rate"
  | "work_mode"
  | "about"
  | "responsibilities"
  | "experience"
  | "target_companies"
  | "disqualifiers"
  | "selling_points"
  | "questions"
  | "ask_client"
  | "client_title"
  | "client_reference"
  | "hiring_manager"
  | "deadline"
  | "headcount";

export interface AskClientItem {
  key: string;
  text: string;
}

export type QuestionOrigin = "request" | "ai" | "template" | "manual";

export interface IntakeQuestionForm {
  key: string;
  question: string;
  idealAnswer: string;
  origin: QuestionOrigin;
  /** Odpowiedź, która dyskwalifikuje kandydata — wymagana przed przekazaniem. */
  dealBreaker: string;
  /**
   * Delivery Lead potwierdził pytanie (02.10.2026). Propozycja AI i pytanie
   * z szablonu startują niezatwierdzone; każda edycja pola zatwierdza, bo
   * wpisana treść jest już decyzją człowieka.
   */
  approved: boolean;
}

export interface IntakeForm {
  /** Rola (sekcja 1 Championa); bez nazwy od klienta — także tytuł rekrutacji. */
  title: string;
  /** 0380: nazwa stanowiska od klienta — dosłownie z maila; idzie do klienta. */
  clientTitle: string;
  /**
   * Numer zapytania klienta z odczytu maila (ZOB, SAP…). Obowiązuje, dopóki
   * stoi w nazwie od klienta — numer czyta `clientReferenceFor`.
   */
  referenceHint: string;
  /** „To nie ten numer”: wpisany ręcznie (także pusty = bez numeru); `null` = z nazwy. */
  referenceOverride: string | null;
  /** 0380: tytuł dla rekrutera; dopóki `workingTitleTouched` = false, liczony z pól. */
  workingTitle: string;
  workingTitleTouched: boolean;
  /**
   * Wymagania jako słowa kluczowe (`lib/requirement-rows.ts`): wiersz =
   * wymaganie, poziom = krytyczne / musi mieć / mile widziane. Z nich serwer
   * wyprowadza must-have, krytyczne i wiersze wyszukiwania w bazie.
   */
  rows: RequirementRowForm[];
  /** Świadome „Brak krytycznych” — gdy żaden wiersz nie jest krytyczny. */
  noCritical: boolean;
  /** Zdania klienta, które nie są słowami kluczowymi — nie filtrują kandydatów. */
  descriptive: string[];
  seniorityYears: number | null;
  rateBudget: string;
  rateNote: string | null;
  /** v7 (27.09.2026): uwagi z odczytu (np. „bankowość” przeniesiona do mile widzianych). */
  intakeNotes: string[];
  remotePolicy: RemotePolicyValue | "";
  onsiteDays: string;
  /** 0407: „w tygodniu” albo „w miesiącu” (miesięcznie tylko hybrydowo). */
  onsiteDaysPeriod: OfficeDaysPeriod;
  city: string;
  startDate: string;
  about: string;
  responsibilities: string;
  questions: IntakeQuestionForm[];
  // ── od v2: reszta profilu Championa ──
  language: string;
  contractLength: string;
  experience: ChampionExperience;
  searchExclude: string[];
  targetCompanies: string;
  disqualifiers: string[];
  sellingPoints: string;
  askClient: AskClientItem[];
  /** 25.09.2026: kto zamawia po stronie klienta; idzie w `POST /api/jobs`. */
  hiringManager: HiringManagerChoice | null;
  /**
   * 04.10.2026: „Klient nie podał” — świadoma decyzja zamiast pustego pola.
   * Hiring manager i termin są wymagane przed publikacją albo ta decyzja.
   */
  hiringManagerNotProvided: boolean;
  /** Termin od klienta: `RRRR-MM-DD`, pusty = brak. */
  deadline: string;
  /** Godzina terminu `HH:MM` (opcjonalna). */
  deadlineTime: string;
  deadlineNotProvided: boolean;
  /** Liczba osób do zatrudnienia — tekst pola (≥ 1). */
  headcount: string;
  /**
   * Kategoria kompetencji (02.10.2026): od niej zależy, kto dostanie
   * rekrutację. `suggestedCategoryId` to podpowiedź systemu z nazwy roli,
   * `competenceCategoryId` — wybór Delivery Leada, `categoryConfirmed` —
   * kliknięte „Potwierdzam” (wymagane przed przekazaniem).
   */
  competenceCategoryId: number | null;
  suggestedCategoryId: number | null;
  categoryConfirmed: boolean;
  provenance: Partial<Record<ProvenanceKey, FieldBasis>>;
}

/** Pozycja sekcji 4 z odczytu — z dosłownym cytatem z maila. */
export interface IntakeExperienceItem {
  name: string;
  level: "must" | "nice";
  min_years?: number | null;
  quote?: string;
}

/** Odpowiedź `POST /api/job-intake/read[-file]` → `intake`. */
export interface RequestIntakeResponse {
  role_name: string | null;
  must: string[];
  nice: string[];
  seniority_min_years: number | null;
  rate_budget_hourly: number | null;
  rate_quote: string | null;
  rate_note: string | null;
  remote_policy: RemotePolicyValue | null;
  onsite_days_per_week: number | null;
  /** 0407: gdy klient liczy na miesiąc. */
  onsite_days_per_month?: number | null;
  office_city: string | null;
  /** v7: wszystkie miasta biura z maila, po polsku. */
  office_cities?: string[];
  /** v7: co kod zmienił w odczycie modelu (przeniesione wymagania, lata dziedzin). */
  advisories?: string[];
  start_date: string | null;
  project_about: string | null;
  responsibilities: string | null;
  screening_questions: {
    question: string;
    ideal_answer: string;
    /** Od v10: AI proponuje też odpowiedź dyskwalifikującą. */
    deal_breaker?: string;
    from_request: boolean;
  }[];
  // ── od v10 (02.10.2026): wymagania jako słowa kluczowe ──
  requirements?: StoredRequirementRow[];
  descriptive_requirements?: string[];
  evidence: string[];
  missing: string[];
  // ── od v2 (starszy backend ich nie niesie) ──
  language?: string | null;
  contract_length?: string | null;
  experience?: Partial<Record<ExperienceKind, IntakeExperienceItem[]>>;
  target_companies?: string | null;
  disqualifiers?: string[];
  // ── od v5 (25.09.2026): wymagania do wyszukiwania w bazie ──
  search_requirements?: string[][];
  selling_points?: string | null;
  ask_client?: string[];
  provenance?: Partial<Record<string, string>>;
  // ── od v3 (0380) ──
  client_title?: string | null;
  client_reference?: string | null;
  working_title_suggestion?: string | null;
  // ── od v4 (25.09.2026): hiring manager z treści maila ──
  hiring_manager_name?: string | null;
  hiring_manager_position?: string | null;
  hiring_manager_email?: string | null;
  /** Istniejący kontakt klienta — ta sama osoba co w mailu. */
  hiring_manager_contact_id?: number | null;
  /** Imię i nazwisko w pisowni kontaktu (gdy dopasowano). */
  hiring_manager_contact_name?: string | null;
  // ── od v11 (04.10.2026): termin i liczba osób — tylko z cytatem z maila ──
  deadline?: string | null;
  deadline_time?: string | null;
  headcount?: number | null;
}

export const EMPTY_EXPERIENCE_FORM: ChampionExperience = {
  domains: [],
  certifications: [],
  regulations: [],
  notes: "",
};

/**
 * Biuro w formularzu to lista miast (chipy); w rekrutacji i Championie idzie
 * jednym napisem „Warszawa, Gdańsk” — tak czyta je bramka miasta biura.
 */
export function splitCities(city: string): string[] {
  const out: string[] = [];
  for (const part of city.split(/[,;\n]/)) {
    const name = part.trim();
    if (name && !out.some((c) => c.toLowerCase() === name.toLowerCase()))
      out.push(name);
  }
  return out;
}

export function joinCities(cities: string[]): string {
  return splitCities(cities.join(",")).join(", ");
}

export const EMPTY_INTAKE_FORM: IntakeForm = {
  title: "",
  clientTitle: "",
  referenceHint: "",
  referenceOverride: null,
  workingTitle: "",
  workingTitleTouched: false,
  rows: [],
  noCritical: false,
  descriptive: [],
  seniorityYears: null,
  rateBudget: "",
  rateNote: null,
  intakeNotes: [],
  remotePolicy: "",
  onsiteDays: "",
  onsiteDaysPeriod: "week",
  city: "",
  startDate: "",
  about: "",
  responsibilities: "",
  questions: [],
  language: "",
  contractLength: "",
  experience: EMPTY_EXPERIENCE_FORM,
  searchExclude: [],
  targetCompanies: "",
  disqualifiers: [],
  sellingPoints: "",
  askClient: [],
  hiringManager: null,
  hiringManagerNotProvided: false,
  deadline: "",
  deadlineTime: "",
  deadlineNotProvided: false,
  headcount: "1",
  competenceCategoryId: null,
  suggestedCategoryId: null,
  categoryConfirmed: false,
  provenance: {},
};

const LEGACY_PROVENANCE: Record<string, ProvenanceKey> = {
  must: "requirements",
  nice: "requirements",
  search_requirements: "requirements",
};

/**
 * Wiersze z odczytu: od v10 serwer oddaje je wprost; starszy odczyt (must,
 * nice, wiersze wyszukiwania) składamy tak samo, jak robi to serwer — wiersze
 * wyszukiwania zostają, a must i nice dochodzą jako pojedyncze słowa.
 */
function rowsFromIntake(intake: RequestIntakeResponse): RequirementRowForm[] {
  if (Array.isArray(intake.requirements)) return rowsFromStored(intake.requirements);
  const stored: StoredRequirementRow[] = [
    ...(intake.search_requirements ?? []).map((words) => ({
      words,
      level: "must" as const,
    })),
    ...(intake.must ?? []).map((name) => ({ words: [name], level: "must" as const })),
    ...(intake.nice ?? []).map((name) => ({ words: [name], level: "nice" as const })),
  ];
  return rowsFromStored(stored);
}

let questionSeq = 0;
export function newQuestionKey(): string {
  questionSeq += 1;
  return `q-${Date.now().toString(36)}-${questionSeq}`;
}

const BASES: readonly FieldBasis[] = ["request", "client_history", "ai"];

function experienceItems(items: IntakeExperienceItem[] | undefined): ExperienceItem[] {
  return (items ?? []).map((item) => ({
    name: item.name,
    level: item.level === "nice" ? "nice" : "must",
    min_years: item.min_years ?? null,
    note: "",
  }));
}

/** DL zmienił pole — chip źródła mówi odtąd „wpisane”. */
export function markEdited(form: IntakeForm, key: ProvenanceKey): IntakeForm {
  if (!form.provenance[key] || form.provenance[key] === "manual") return form;
  return { ...form, provenance: { ...form.provenance, [key]: "manual" } };
}

/** Podpowiedź HM z maila: istniejący kontakt klienta albo nowa osoba. */
export function hiringManagerFromIntake(
  intake: RequestIntakeResponse,
): HiringManagerChoice | null {
  const name = intake.hiring_manager_name?.trim();
  if (!name) return null;
  if (intake.hiring_manager_contact_id != null) {
    return {
      kind: "contact",
      id: intake.hiring_manager_contact_id,
      name: intake.hiring_manager_contact_name?.trim() || name,
    };
  }
  return {
    kind: "new",
    name,
    position: intake.hiring_manager_position ?? null,
    email: intake.hiring_manager_email ?? null,
  };
}

/**
 * Numer zapytania z maila, którego nie ma w nazwie od klienta, dopisuje się do
 * nazwy w nawiasie — „Python Developer (ZOB-9905)”, jak w rekrutacjach
 * z Traffita. `clientReferenceFor` bierze numer tylko z nazwy, więc bez tego
 * numer odczytany z maila („zapytanie nr ZOB-9905. Szukamy…”) przepadał,
 * a formularz pisał „Nie widzę numeru zapytania w nazwie” (audyt 05.10.2026).
 */
export function clientTitleWithReference(
  clientTitle: string,
  roleName: string,
  reference: string,
): string {
  const ref = reference.replace(/\s+/g, " ").trim();
  const base = clientTitle.trim() || roleName.trim();
  if (!ref || !base) return clientTitle;
  if (base.toLocaleLowerCase("pl").includes(ref.toLocaleLowerCase("pl"))) return clientTitle;
  return `${base} (${ref})`;
}

export function formFromIntake(intake: RequestIntakeResponse): IntakeForm {
  const provenance: IntakeForm["provenance"] = {};
  for (const [key, basis] of Object.entries(intake.provenance ?? {})) {
    if (!BASES.includes(basis as FieldBasis)) continue;
    // Starszy odczyt podawał źródło osobno dla must i wierszy wyszukiwania.
    const target = LEGACY_PROVENANCE[key] ?? (key as ProvenanceKey);
    if (!provenance[target]) provenance[target] = basis as FieldBasis;
  }
  return {
    language: intake.language ?? "",
    contractLength: intake.contract_length ?? "",
    experience: {
      domains: experienceItems(intake.experience?.domains),
      certifications: experienceItems(intake.experience?.certifications),
      regulations: experienceItems(intake.experience?.regulations),
      notes: "",
    },
    searchExclude: [],
    targetCompanies: intake.target_companies ?? "",
    disqualifiers: intake.disqualifiers ?? [],
    sellingPoints: intake.selling_points ?? "",
    askClient: (intake.ask_client ?? []).map((text) => ({
      key: newQuestionKey(),
      text,
    })),
    hiringManager: hiringManagerFromIntake(intake),
    hiringManagerNotProvided: false,
    deadline: intake.deadline ?? "",
    deadlineTime: intake.deadline ? (intake.deadline_time ?? "") : "",
    deadlineNotProvided: false,
    headcount:
      intake.headcount != null && intake.headcount >= 1 ? String(intake.headcount) : "1",
    competenceCategoryId: null,
    suggestedCategoryId: null,
    categoryConfirmed: false,
    provenance,
    title: intake.role_name ?? "",
    clientTitle: clientTitleWithReference(
      intake.client_title ?? "",
      intake.role_name ?? "",
      intake.client_reference ?? "",
    ),
    referenceHint: intake.client_reference ?? "",
    referenceOverride: null,
    workingTitle: "",
    workingTitleTouched: false,
    // Krytyczne wybiera DL — odczyt maila ich nie ustawia (30.09.2026).
    rows: rowsFromIntake(intake),
    noCritical: false,
    descriptive: intake.descriptive_requirements ?? [],
    seniorityYears: intake.seniority_min_years ?? null,
    rateBudget:
      intake.rate_budget_hourly != null
        ? String(intake.rate_budget_hourly)
        : "",
    rateNote: intake.rate_note ?? null,
    intakeNotes: intake.advisories ?? [],
    remotePolicy: intake.remote_policy ?? "",
    onsiteDays: officeDaysFormValue(
      intake.onsite_days_per_week,
      intake.onsite_days_per_month,
    ).value,
    onsiteDaysPeriod: officeDaysFormValue(
      intake.onsite_days_per_week,
      intake.onsite_days_per_month,
    ).period,
    city: intake.office_cities?.length
      ? joinCities(intake.office_cities)
      : (intake.office_city ?? ""),
    startDate: intake.start_date ?? "",
    about: intake.project_about ?? "",
    responsibilities: intake.responsibilities ?? "",
    questions: (intake.screening_questions ?? []).map((q) => ({
      key: newQuestionKey(),
      question: q.question,
      idealAnswer: q.ideal_answer ?? "",
      dealBreaker: q.deal_breaker ?? "",
      origin: q.from_request ? "request" : "ai",
      approved: false,
    })),
  };
}

/** Must-have formularza — pierwsze słowa wierszy krytycznych i „musi mieć”. */
export function mustOf(form: IntakeForm): string[] {
  return mustHeads(form.rows);
}

export function niceOf(form: IntakeForm): string[] {
  return niceHeads(form.rows);
}

const ZOB = /\bZOB[\s_-]*(\d+)\b/gi;

/**
 * Numer u klienta (02.10.2026 — bez osobnego pola): numer z odczytu maila,
 * dopóki stoi w nazwie od klienta; inaczej jednoznaczny „ZOB <cyfry>” z nazwy
 * (lustro `job_working_title.reference_from_title`). „To nie ten numer”
 * wpisuje go ręcznie — także pusty, gdy numer w nazwie nie jest numerem.
 */
export function clientReferenceFor(form: IntakeForm): string {
  if (form.referenceOverride != null) return form.referenceOverride.trim();
  const title = form.clientTitle.replace(/\s+/g, " ").toLocaleLowerCase("pl");
  const hint = form.referenceHint.replace(/\s+/g, " ").trim();
  if (hint && title.includes(hint.toLocaleLowerCase("pl"))) return hint;
  const found = new Set<string>();
  for (const match of form.clientTitle.matchAll(ZOB)) found.add(match[1]);
  return found.size === 1 ? `ZOB ${[...found][0]}` : "";
}

/**
 * Podpowiedź tytułu dla rekrutera z bieżących pól formularza — ta sama reguła
 * co `job_working_title.compose_working_title` na serwerze.
 */
export function suggestedWorkingTitle(form: IntakeForm): string {
  const domain = form.experience.domains.find((d) => d.level !== "nice")?.name ?? null;
  return composeWorkingTitle(form.title, mustOf(form), form.seniorityYears, domain) ?? "";
}

/** Tytuł dla rekrutera widoczny w formularzu: ręczny albo podpowiedź. */
export function effectiveWorkingTitle(form: IntakeForm): string {
  return form.workingTitleTouched ? form.workingTitle : suggestedWorkingTitle(form);
}

/** Tytuł rekrutacji (`jobs.title`): nazwa od klienta, a bez niej rola. */
export function jobTitleFor(form: IntakeForm): string {
  return form.clientTitle.trim() || form.title.trim();
}

// ── Braki wobec „Przekaż do searchu” ─────────────────────────────────────────

export type MissingCode =
  | "role"
  | "must"
  | "budget"
  | "work_mode"
  | "office_days"
  | "office_city"
  | "context"
  | "questions"
  | "critical"
  | "deal_breaker"
  | "questions_review"
  | "category"
  | "hiring_manager"
  | "deadline"
  | "headcount";

export const MISSING_LABEL: Record<MissingCode, string> = {
  role: "rola",
  must: "wymagania (słowa kluczowe)",
  budget: "budżet PLN/h",
  work_mode: "tryb pracy",
  office_days: "dni w biurze",
  office_city: "miasto biura",
  context: "opis projektu",
  questions: "drugie pytanie do kandydata",
  critical: "krytyczne (albo „Brak krytycznych”)",
  deal_breaker: "odpowiedź, która odpada, przy każdym pytaniu",
  questions_review: "zatwierdzenie pytań",
  category: "potwierdzenie kategorii",
  hiring_manager: "hiring manager (albo „Klient nie podał”)",
  deadline: "termin (albo „Klient nie podał”)",
  headcount: "liczba osób",
};

/** Sekcja formularza, w której usuwa się dany brak (pasek sekcji, stopka). */
export type FormSection =
  | "name"
  | "requirements"
  | "terms"
  | "project"
  | "questions"
  | "team";

export const FORM_SECTIONS: { id: FormSection; label: string }[] = [
  { id: "name", label: "Nazwa" },
  { id: "requirements", label: "Wymagania" },
  { id: "terms", label: "Warunki" },
  { id: "project", label: "O projekcie" },
  { id: "questions", label: "Pytania" },
  { id: "team", label: "Kategoria i zespół" },
];

export const MISSING_SECTION: Record<MissingCode, FormSection> = {
  role: "name",
  must: "requirements",
  critical: "requirements",
  budget: "terms",
  work_mode: "terms",
  office_days: "terms",
  office_city: "terms",
  context: "project",
  questions: "questions",
  deal_breaker: "questions",
  questions_review: "questions",
  category: "team",
  hiring_manager: "name",
  deadline: "terms",
  headcount: "terms",
};

/** `id` elementu sekcji — cel linków z paska sekcji i ze stopki. */
export function sectionAnchor(section: FormSection): string {
  return `new-job-section-${section}`;
}

/** Budżet jak w `JobCreate.rate_budget_hourly`: > 0 i ≤ 2000. */
export function parseBudget(value: string): number | null {
  const normalized = value.replace(/\s/g, "").replace(",", ".");
  if (!normalized) return null;
  const n = Number(normalized);
  return Number.isFinite(n) && n > 0 && n <= 2000 ? n : null;
}

/** Liczba osób: liczba całkowita 1–99 (lustro `JobCreate.headcount`). */
export function parseHeadcount(value: string): number | null {
  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const n = Number(trimmed);
  return n >= 1 && n <= 99 ? n : null;
}

export function parseOnsiteDays(value: string): number | null {
  if (value.trim() === "") return null;
  const n = Number(value);
  return Number.isInteger(n) && n >= 0 && n <= 7 ? n : null;
}

/** Para pól zapisu dni w biurze z formularza (0407). */
export function formOfficeDays(form: IntakeForm): {
  onsite_days_per_week: number | null;
  onsite_days_per_month: number | null;
} {
  if (form.remotePolicy === "remote")
    return { onsite_days_per_week: null, onsite_days_per_month: null };
  return officeDaysFields(
    form.onsiteDays,
    form.onsiteDaysPeriod,
    form.remotePolicy || null,
  );
}

export function filledQuestions(form: IntakeForm): IntakeQuestionForm[] {
  return form.questions.filter((q) => q.question.trim().length > 0);
}

/** Puste pytanie dopisane ręcznie — wpisuje je człowiek, więc jest zatwierdzone. */
export function newManualQuestion(): IntakeQuestionForm {
  return {
    key: newQuestionKey(),
    question: "",
    idealAnswer: "",
    dealBreaker: "",
    origin: "manual",
    approved: true,
  };
}

/** Edycja pytania: zmieniona treść jest decyzją Delivery Leada. */
export function editQuestion(
  form: IntakeForm,
  key: string,
  patch: Partial<Pick<IntakeQuestionForm, "question" | "idealAnswer" | "dealBreaker">>,
): IntakeForm {
  return {
    ...form,
    questions: form.questions.map((q) =>
      q.key === key ? { ...q, ...patch, approved: true } : q,
    ),
  };
}

/** „Zatwierdź” / „Zatwierdź wszystkie” — tylko pytania z odpowiedzią, która odpada. */
export function approveQuestions(form: IntakeForm, key?: string): IntakeForm {
  return {
    ...form,
    questions: form.questions.map((q) =>
      (key == null || q.key === key) && q.question.trim() && q.dealBreaker.trim()
        ? { ...q, approved: true }
        : q,
    ),
  };
}

/** Pytanie bez zatwierdzenia: propozycja AI albo kopia z szablonu, której nikt nie ruszył. */
export function unapprovedQuestions(form: IntakeForm): IntakeQuestionForm[] {
  return filledQuestions(form).filter((q) => !q.approved);
}

/**
 * Lustro `job_request_intake.missing_fields` + trzy potwierdzenia formularza
 * (pytania, kategoria). `criticalInfo` = co serwer wie o wierszach (odpowiedź
 * `critical-suggestion` dla BIEŻĄCEJ listy); `null`/brak = jeszcze nie wiadomo
 * — wtedy „critical” nie wchodzi (nie zgadujemy, że lista ma technologie).
 */
export function missingFor(
  form: IntakeForm,
  opts: { criticalInfo?: Record<string, RowCriticalInfo> | null } = {},
): MissingCode[] {
  const missing: MissingCode[] = [];
  if (!form.title.trim()) missing.push("role");
  if (form.hiringManager == null && !form.hiringManagerNotProvided)
    missing.push("hiring_manager");
  if (mustOf(form).length === 0) missing.push("must");
  else if (criticalDecisionMissing(form.rows, form.noCritical, opts.criticalInfo))
    missing.push("critical");
  if (parseBudget(form.rateBudget) == null) missing.push("budget");
  if (!form.remotePolicy) {
    missing.push("work_mode");
  } else if (form.remotePolicy !== "remote") {
    if (formOfficeDays(form).onsite_days_per_week == null)
      missing.push("office_days");
    if (!form.city.trim()) missing.push("office_city");
  }
  if (!form.deadline && !form.deadlineNotProvided) missing.push("deadline");
  if (parseHeadcount(form.headcount) == null) missing.push("headcount");
  if (!form.about.trim() && !form.responsibilities.trim())
    missing.push("context");
  const questions = filledQuestions(form);
  if (questions.length < 2) missing.push("questions");
  if (questions.some((q) => !q.dealBreaker.trim())) missing.push("deal_breaker");
  else if (questions.some((q) => !q.approved)) missing.push("questions_review");
  if (form.competenceCategoryId == null || !form.categoryConfirmed)
    missing.push("category");
  return missing;
}

/** Braki pogrupowane po sekcjach — pasek sekcji nad formularzem. */
export function missingBySection(
  missing: readonly MissingCode[],
): Record<FormSection, MissingCode[]> {
  const out = Object.fromEntries(
    FORM_SECTIONS.map((section) => [section.id, [] as MissingCode[]]),
  ) as Record<FormSection, MissingCode[]>;
  for (const code of missing) out[MISSING_SECTION[code]].push(code);
  return out;
}

/** „Brakuje 2 rzeczy do publikacji” — dopełniacz, więc „rzeczy” dla każdej liczby. */
export function missingHeadline(count: number): string {
  return `Brakuje ${count} rzeczy do publikacji`;
}

// ── Braki z serwera (422 `job_not_ready`) ────────────────────────────────────

/** Brak zgłoszony przez serwer: kod (lustro bramki) i zdanie. */
export interface ServerBlocker {
  code: string;
  message: string;
}

/**
 * Kod braku serwera → brak formularza (sekcja, do której prowadzi link).
 * Kody to klucze `__fixtures__/job-readiness-blockers.json` + decyzje
 * formularza; `champion:<kod>` i nieznane trafiają do listy ogólnej.
 */
const SERVER_BLOCKER_CODE: Record<string, MissingCode> = {
  title: "role",
  context: "context",
  questions: "questions",
  must: "must",
  search: "must",
  budget: "budget",
  work_mode: "work_mode",
  office_days: "office_days",
  office_city: "office_city",
  critical: "critical",
  deal_breaker: "deal_breaker",
  hiring_manager: "hiring_manager",
  deadline: "deadline",
  category: "category",
  headcount: "headcount",
};

/** Sekcja formularza dla kodu braku z serwera; `null` = bez sekcji (lista ogólna). */
export function serverBlockerSection(code: string): FormSection | null {
  const missing = SERVER_BLOCKER_CODE[code];
  return missing ? MISSING_SECTION[missing] : null;
}

/**
 * 422 `job_not_ready` z `POST /api/jobs` → lista braków. Inne błędy → `null`
 * (wołający pokazuje wtedy zdanie z `apiErrorMessage`).
 */
export function serverBlockersFromError(error: unknown): ServerBlocker[] | null {
  const detail = (
    error as { response?: { status?: number; data?: { detail?: unknown } } } | null
  )?.response?.data?.detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const { code, blockers } = detail as { code?: unknown; blockers?: unknown };
  if (code !== "job_not_ready" || !Array.isArray(blockers)) return null;
  const out: ServerBlocker[] = [];
  for (const item of blockers) {
    if (typeof item === "string") {
      out.push({ code: "", message: item });
    } else if (item && typeof item === "object") {
      const message = (item as { message?: unknown }).message;
      const itemCode = (item as { code?: unknown }).code;
      if (typeof message === "string" && message.trim()) {
        out.push({ code: typeof itemCode === "string" ? itemCode : "", message });
      }
    }
  }
  return out;
}

/** „Rekrutacja nie powstała. Uzupełnij 3 rzeczy:” */
export function serverBlockersHeadline(count: number): string {
  return `Rekrutacja nie powstała. Uzupełnij ${count} ${count === 1 ? "rzecz" : "rzeczy"}:`;
}

// ── Payloady zapisu ──────────────────────────────────────────────────────────

/** `POST /api/jobs` — tylko to, co formularz naprawdę zna. */
export function buildJobPayload(
  form: IntakeForm,
  opts: { clientId: number; requestText: string; templateJobId: number | null },
): Record<string, unknown> {
  const remote = form.remotePolicy || null;
  const payload: Record<string, unknown> = {
    title: jobTitleFor(form),
    client_id: opts.clientId,
    auto_suggest_cc: true,
    remote_policy: remote,
    ...formOfficeDays(form),
  };
  const description = opts.requestText.trim();
  if (description) payload.description = description;
  // Numer wpisany ręcznie jedzie zawsze — także pusty („bez numeru”): serwer
  // czyta numer z nazwy tylko wtedy, gdy pola w żądaniu nie ma.
  const reference = clientReferenceFor(form);
  if (reference || form.referenceOverride != null) payload.client_reference = reference;
  if (form.competenceCategoryId != null)
    payload.competence_category_id = form.competenceCategoryId;
  // Bez ręcznej zmiany serwer składa tytuł sam (i przelicza go po Championie).
  if (form.workingTitleTouched && form.workingTitle.trim())
    payload.working_title = form.workingTitle.trim();
  // Pierwsze słowa wierszy; po zapisie profilu serwer podmienia je etykietami.
  const must = mustOf(form);
  const nice = niceOf(form);
  if (must.length > 0) payload.must_skills = must;
  if (nice.length > 0) payload.nice_skills = nice;
  if (remote !== "remote" && form.city.trim())
    payload.location = form.city.trim();
  const budget = parseBudget(form.rateBudget);
  if (budget != null) payload.rate_budget_hourly = budget;
  // Termin: data albo świadome „klient nie podał” (04.10.2026).
  payload.deadline = form.deadlineNotProvided ? null : form.deadline || null;
  payload.deadline_time =
    !form.deadlineNotProvided && form.deadline && form.deadlineTime ? form.deadlineTime : null;
  payload.deadline_not_provided = form.deadlineNotProvided;
  const headcount = parseHeadcount(form.headcount);
  if (headcount != null) payload.headcount = headcount;
  if (opts.templateJobId != null) {
    payload.from_job_id = opts.templateJobId;
    payload.copy_questions = true;
  }
  return payload;
}

const CHAMPION_WORK_MODE: Record<RemotePolicyValue, string> = {
  remote: "zdalnie",
  hybrid: "hybrydowo",
  onsite: "stacjonarnie",
};

/**
 * `PUT /api/jobs/{id}/champion-profile` — cały szkic z propozycji Luny
 * (od 09.2026): podstawy, wymagania (wiersze słów kluczowych), doświadczenie,
 * projekt, argumenty dla kandydata, pytania i „do dopytania u klienta”.
 * Serwer scala payload na zapisanym profilu (sekcje płytko), więc
 * `client: {selling_points}` nie kasuje reszty sekcji klienta.
 */
export function buildChampionPayload(
  form: IntakeForm,
): Record<string, unknown> {
  const remote = form.remotePolicy || null;
  const budget = parseBudget(form.rateBudget);
  return {
    basics: {
      role_name: form.title.trim() || null,
      // Formularz nie ma pola lat (runda 6 audytu): wartość idzie tylko, gdy
      // przyszła z maila albo z szablonu — `null` kasował lata skopiowane
      // z rekrutacji-szablonu, bo serwer scala sekcję `basics` płytko.
      ...(form.seniorityYears != null
        ? { seniority_min_years: form.seniorityYears }
        : {}),
      rate_value: budget,
      work_mode: remote ? CHAMPION_WORK_MODE[remote] : null,
      ...formOfficeDays(form),
      candidate_location_pref:
        remote === "remote" ? null : form.city.trim() || null,
      start_date: form.startDate || null,
      language: form.language.trim() || null,
      contract_length: form.contractLength.trim() || null,
    },
    stack: {
      // Must-have, mile widziane, krytyczne i wiersze wyszukiwania serwer
      // wyprowadza z wierszy (`champion_requirement_rows.expand_patch`).
      rows: toStoredRows(form.rows),
      // `null` = nie zdecydowano, `[]` = „Brak krytycznych” — dwie różne decyzje.
      critical: criticalDecision(form.rows, form.noCritical),
      // Zdania klienta nie filtrują kandydatów — czyta je rekruter i generator CV.
      ...(form.descriptive.length > 0
        ? { notes: form.descriptive.join("\n") }
        : {}),
    },
    experience: form.experience,
    search: {
      target_companies: form.targetCompanies.trim(),
      disqualifiers: form.disqualifiers,
      exclude: form.searchExclude.map(sanitizeKeyword).filter(Boolean),
    },
    project: {
      about: form.about.trim(),
      responsibilities: form.responsibilities.trim(),
    },
    client: { selling_points: form.sellingPoints.trim() },
    screening_questions: filledQuestions(form).map((q, i) => ({
      id: `q${i + 1}`,
      question: q.question.trim(),
      ideal_answer: q.idealAnswer.trim(),
      deal_breaker: q.dealBreaker.trim(),
    })),
    // „Do dopytania u klienta” — notatki sekcji 8, odhaczane w profilu.
    // Wpisy nowe (`new-…`): serwer nada id i autora.
    insights: form.askClient
      .filter((item) => item.text.trim())
      .map((item) => ({
        id: `new-${item.key}`,
        source: "client",
        topic: "ask_client",
        audience: "team",
        text: item.text.trim(),
        done: false,
        origin: "ai_intake",
      })),
  };
}

/** Przekazanie w `POST /api/jobs`: automat albo wskazana osoba. */
export type CreateHandoff =
  | { assignment_mode: "automatic"; channel: "linkedin" }
  | { recruiter_id: number; channel: "linkedin" };

/** Hiring manager w `POST /api/jobs` — osoba albo „klient nie podał”. */
export function hiringManagerForCreate(form: IntakeForm): Record<string, unknown> | null {
  if (form.hiringManagerNotProvided) return { not_provided: true };
  if (form.hiringManager == null) return null;
  return hiringManagerRequestBody(form.hiringManager);
}

/**
 * Jedno `POST /api/jobs` (04.10.2026): rekrutacja powstaje od razu
 * przekazana i opublikowana — razem z profilem Championa, hiring managerem,
 * przekazaniem, podobnymi rekrutacjami i wyborem kategorii. Serwer sprawdza
 * bramkę w jednej transakcji; brak = 422 i nic nie powstaje.
 */
export function buildCreateJobPayload(
  form: IntakeForm,
  opts: {
    clientId: number;
    requestText: string;
    templateJobId: number | null;
    priority: string;
    handoff: CreateHandoff;
    similarJobIds: number[];
    intakeFormId: number | null;
  },
): Record<string, unknown> {
  const categoryChanged =
    form.suggestedCategoryId != null &&
    form.competenceCategoryId != null &&
    form.suggestedCategoryId !== form.competenceCategoryId;
  return {
    ...buildJobPayload(form, opts),
    priority: opts.priority,
    champion_profile: buildChampionPayload(form),
    hiring_manager: hiringManagerForCreate(form),
    handoff: opts.handoff,
    similar_job_ids: opts.similarJobIds,
    // Delivery Lead wybrał inną kategorię niż podpowiedź — dziennik dla reguł.
    cc_override: categoryChanged
      ? { suggested_cc_id: form.suggestedCategoryId, suggested_score: null }
      : null,
    intake_form_id: opts.intakeFormId,
  };
}

// ── Niedokończony formularz na koncie autora ─────────────────────────────────

/** Etykieta formularza na liście „niedokończonych”. */
export function intakeFormLabel(form: IntakeForm): string {
  return form.clientTitle.trim() || form.title.trim() || "Rekrutacja bez nazwy";
}

/**
 * Formularz zapisany przed zmianą kształtu (nowe pola) — brakujące pola
 * dostają wartości z pustego formularza, więc stary zapis da się dokończyć.
 */
export function restoreIntakeForm(saved: unknown): IntakeForm {
  if (!saved || typeof saved !== "object") return { ...EMPTY_INTAKE_FORM };
  const raw = saved as Partial<IntakeForm>;
  return {
    ...EMPTY_INTAKE_FORM,
    ...raw,
    experience: { ...EMPTY_EXPERIENCE_FORM, ...(raw.experience ?? {}) },
    provenance: raw.provenance ?? {},
    rows: Array.isArray(raw.rows) ? raw.rows : [],
    questions: Array.isArray(raw.questions) ? raw.questions : [],
    askClient: Array.isArray(raw.askClient) ? raw.askClient : [],
    descriptive: Array.isArray(raw.descriptive) ? raw.descriptive : [],
    intakeNotes: Array.isArray(raw.intakeNotes) ? raw.intakeNotes : [],
    disqualifiers: Array.isArray(raw.disqualifiers) ? raw.disqualifiers : [],
    searchExclude: Array.isArray(raw.searchExclude) ? raw.searchExclude : [],
  };
}

// ── Podświetlenie requestu ───────────────────────────────────────────────────

export interface TextSegment {
  text: string;
  mark: boolean;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Dzieli request na fragmenty z zaznaczeniem tego, co trafiło do pól.
 * Serwer zwija białe znaki we fragmentach, więc dopasowanie traktuje każdy
 * ciąg białych znaków elastycznie i ignoruje wielkość liter.
 */
export function highlightSegments(
  text: string,
  evidence: string[],
): TextSegment[] {
  const ranges: [number, number][] = [];
  for (const fragment of evidence) {
    const trimmed = fragment.trim();
    if (trimmed.length < 2) continue;
    const pattern = new RegExp(
      trimmed.split(/\s+/).map(escapeRegExp).join("\\s+"),
      "gi",
    );
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      ranges.push([match.index, match.index + match[0].length]);
      if (match[0].length === 0) pattern.lastIndex += 1;
    }
  }
  if (ranges.length === 0) return text ? [{ text, mark: false }] : [];
  ranges.sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const range of ranges) {
    const last = merged[merged.length - 1];
    if (last && range[0] <= last[1]) last[1] = Math.max(last[1], range[1]);
    else merged.push([range[0], range[1]]);
  }
  const out: TextSegment[] = [];
  let cursor = 0;
  for (const [start, end] of merged) {
    if (start > cursor)
      out.push({ text: text.slice(cursor, start), mark: false });
    out.push({ text: text.slice(start, end), mark: true });
    cursor = end;
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor), mark: false });
  return out;
}

/** Minimalna długość requestu — lustro `MIN_REQUEST_CHARS` backendu. */
export const MIN_REQUEST_CHARS = 30;

// ── Szablon z podobnej rekrutacji („Użyj jako szablon”, `?from=`) ────────────

/** Fragment `GET /api/jobs/{id}` czytany przy szablonie. */
export interface TemplateSourceJob {
  id: number;
  title?: string | null;
  client_id?: number | null;
  description?: string | null;
  location?: string | null;
  rate_budget_hourly?: number | null;
  remote_policy?: RemotePolicyValue | null;
  onsite_days_per_week?: number | null;
  onsite_days_per_month?: number | null;
  must_skills?: unknown;
  nice_skills?: unknown;
  champion_profile?: unknown;
}

/**
 * Rekrutacja-szablon z profilem Championa W NOWYM KSZTAŁCIE.
 *
 * Runda 8 (R8-N12-1): `GET /api/jobs/{id}` oddaje surowy JSONB profilu, a 949
 * profili z importu 08.2026 ma stary kształt (`project_context`, `sourcing`).
 * `applyTemplate` czyta wyłącznie nowe sekcje, więc formularz zostawał pusty,
 * a PUT z `/jobs/new` nadpisywał pustymi napisami to, co serwer właśnie
 * skopiował z szablonu (`from_job_id`). Profil bierzemy z
 * `GET …/champion-profile` (`champion_view.api_response` — migracja na
 * serwerze, jedna reguła); gdy ten odczyt padnie, zostaje surowy.
 *
 * Runda 9 (R9-V2-4): `mark_read=false` — kopiowanie szablonu to nie otwarcie
 * rekrutacji, więc nie może gasić powiadomień „Profil Championa zaktualizowany”.
 */
export async function loadTemplateSource<T extends TemplateSourceJob>(
  get: (url: string) => Promise<{ data: unknown }>,
  jobId: number,
): Promise<T> {
  const [jobResponse, profile] = await Promise.all([
    get(`/api/jobs/${jobId}`),
    get(`/api/jobs/${jobId}/champion-profile?mark_read=false`).then(
      ({ data }) =>
        data && typeof data === "object"
          ? (data as { champion_profile?: unknown }).champion_profile
          : undefined,
      () => undefined,
    ),
  ]);
  const job = jobResponse.data as T;
  if (
    profile &&
    typeof profile === "object" &&
    Object.keys(profile as object).length > 0
  ) {
    return { ...job, champion_profile: profile };
  }
  return job;
}

function skillNames(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const item of value) {
    const name =
      typeof item === "string"
        ? item
        : item && typeof item === "object" && "name" in item
          ? String((item as { name: unknown }).name ?? "")
          : "";
    const trimmed = name.trim();
    if (
      trimmed &&
      !out.some((n) => n.toLowerCase() === trimmed.toLowerCase())
    ) {
      out.push(trimmed);
    }
  }
  return out;
}

function championSection(
  profile: unknown,
  key: string,
): Record<string, unknown> {
  if (!profile || typeof profile !== "object") return {};
  const section = (profile as Record<string, unknown>)[key];
  return section && typeof section === "object"
    ? (section as Record<string, unknown>)
    : {};
}

/** Wynik `POST /api/job-intake/requirement-rows` — stare pola jako wiersze. */
export interface TemplateRows {
  rows: StoredRequirementRow[];
  descriptive: string[];
}

function searchRequirementsOf(profile: unknown): string[][] {
  const raw = championSection(profile, "search").requirements;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((row) =>
      Array.isArray(row)
        ? row.filter((w): w is string => typeof w === "string" && w.trim().length > 0)
        : [],
    )
    .filter((row) => row.length > 0);
}

/**
 * Stare pola wymagań szablonu do zamiany na wiersze — `null`, gdy szablon jest
 * już prowadzony wierszami (wtedy zamiana nie jest potrzebna).
 */
export function templateLegacyFields(src: TemplateSourceJob): {
  must: string[];
  nice: string[];
  requirements: string[][];
  critical: null;
} | null {
  const stack = championSection(src.champion_profile, "stack");
  if (Array.isArray(stack.rows) && stack.rows.length > 0) return null;
  const must = skillNames(stack.must);
  const nice = skillNames(stack.nice);
  return {
    must: must.length > 0 ? must : skillNames(src.must_skills),
    nice: nice.length > 0 ? nice : skillNames(src.nice_skills),
    requirements: searchRequirementsOf(src.champion_profile),
    // Kopia rekrutacji nie przenosi decyzji o krytycznych (jak na serwerze).
    critical: null,
  };
}

/**
 * Wypełnia WYŁĄCZNIE puste pola formularza danymi rekrutacji-szablonu.
 * Rola zostaje z requestu (nowa rekrutacja nie udaje starej); pytania
 * dochodzą tylko wtedy, gdy formularz ma ich mniej niż dwa. `converted` to
 * stare pola wymagań szablonu zamienione przez serwer na wiersze; bez niego
 * (awaria zamiany) każde must-have i mile widziane to wiersz z jednym słowem.
 */
export function applyTemplate(
  form: IntakeForm,
  src: TemplateSourceJob,
  converted: TemplateRows | null = null,
): IntakeForm {
  const next: IntakeForm = { ...form };
  const project = championSection(src.champion_profile, "project");
  if (next.rows.length === 0) {
    const stack = championSection(src.champion_profile, "stack");
    const legacy = templateLegacyFields(src);
    const stored: unknown =
      legacy == null
        ? stack.rows
        : converted
          ? converted.rows
          : [
              ...legacy.requirements.map((words) => ({ words, level: "must" })),
              ...legacy.must.map((name) => ({ words: [name], level: "must" })),
              ...legacy.nice.map((name) => ({ words: [name], level: "nice" })),
            ];
    // Krytyczne wybiera Delivery Lead od nowa — kopia ich nie przenosi.
    next.rows = rowsFromStored(stored).map((row) =>
      row.level === "critical" ? { ...row, level: "must" as const } : row,
    );
    if (next.descriptive.length === 0 && converted) next.descriptive = converted.descriptive;
  }
  if (!next.rateBudget && src.rate_budget_hourly != null) {
    next.rateBudget = String(src.rate_budget_hourly);
  }
  if (!next.remotePolicy && src.remote_policy)
    next.remotePolicy = src.remote_policy;
  if (!next.onsiteDays && src.onsite_days_per_week != null) {
    const office = officeDaysFormValue(
      src.onsite_days_per_week,
      src.onsite_days_per_month,
    );
    next.onsiteDays = office.value;
    next.onsiteDaysPeriod = office.period;
  }
  if (!next.city && src.location) next.city = src.location;
  // Pola, które `POST /api/jobs` z `from_job_id` kopiuje z profilu źródłowego,
  // muszą trafić też do formularza: PUT profilu zaraz po utworzeniu wysyła je
  // i serwer scala sekcje płytko — puste pole w formularzu skasowałoby kopię.
  const search = championSection(src.champion_profile, "search");
  const client = championSection(src.champion_profile, "client");
  const basics = championSection(src.champion_profile, "basics");
  const text = (value: unknown) => (typeof value === "string" ? value : "");
  if (next.searchExclude.length === 0 && Array.isArray(search.exclude)) {
    next.searchExclude = search.exclude.filter(
      (w): w is string => typeof w === "string" && w.trim().length > 0,
    );
  }
  if (!next.targetCompanies) next.targetCompanies = text(search.target_companies);
  if (next.disqualifiers.length === 0 && Array.isArray(search.disqualifiers)) {
    next.disqualifiers = search.disqualifiers.filter(
      (d): d is string => typeof d === "string" && d.trim().length > 0,
    );
  }
  if (!next.sellingPoints) next.sellingPoints = text(client.selling_points);
  if (!next.language) next.language = text(basics.language);
  if (!next.contractLength) next.contractLength = text(basics.contract_length);
  if (next.seniorityYears == null && typeof basics.seniority_min_years === "number") {
    next.seniorityYears = basics.seniority_min_years;
  }
  const experience = championSection(src.champion_profile, "experience");
  const kinds: ExperienceKind[] = ["domains", "certifications", "regulations"];
  if (kinds.every((kind) => next.experience[kind].length === 0)) {
    next.experience = {
      ...next.experience,
      ...Object.fromEntries(
        kinds.map((kind) => [
          kind,
          (Array.isArray(experience[kind]) ? (experience[kind] as ExperienceItem[]) : [])
            .filter((item) => item && typeof item.name === "string" && item.name.trim())
            .map((item) => ({
              name: item.name,
              level: item.level === "nice" ? "nice" : "must",
              min_years: kind === "domains" ? (item.min_years ?? null) : null,
              note: item.note ?? "",
            })),
        ]),
      ),
    } as ChampionExperience;
  }
  if (!next.about && typeof project.about === "string")
    next.about = project.about;
  if (!next.responsibilities && typeof project.responsibilities === "string") {
    next.responsibilities = project.responsibilities;
  }
  if (filledQuestions(next).length < 2) {
    const raw =
      src.champion_profile && typeof src.champion_profile === "object"
        ? (src.champion_profile as Record<string, unknown>).screening_questions
        : null;
    const existing = new Set(
      next.questions.map((q) => q.question.trim().toLowerCase()),
    );
    const added: IntakeQuestionForm[] = [];
    if (Array.isArray(raw)) {
      for (const item of raw) {
        if (!item || typeof item !== "object") continue;
        const question = String(
          (item as Record<string, unknown>).question ?? "",
        ).trim();
        if (!question || existing.has(question.toLowerCase())) continue;
        existing.add(question.toLowerCase());
        added.push({
          key: newQuestionKey(),
          question,
          idealAnswer: String(
            (item as Record<string, unknown>).ideal_answer ?? "",
          ),
          dealBreaker: String(
            (item as Record<string, unknown>).deal_breaker ?? "",
          ),
          origin: "template",
          approved: false,
        });
      }
    }
    next.questions = [...next.questions, ...added];
  }
  return next;
}
