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
  | "must"
  | "nice"
  | "rate"
  | "work_mode"
  | "about"
  | "responsibilities"
  | "experience"
  | "search_keywords"
  | "target_companies"
  | "disqualifiers"
  | "selling_points"
  | "questions"
  | "ask_client";

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
}

export interface IntakeForm {
  title: string;
  must: string[];
  nice: string[];
  seniorityYears: number | null;
  rateBudget: string;
  rateNote: string | null;
  remotePolicy: RemotePolicyValue | "";
  onsiteDays: string;
  city: string;
  startDate: string;
  about: string;
  responsibilities: string;
  questions: IntakeQuestionForm[];
  // ── od v2: reszta profilu Championa ──
  language: string;
  contractLength: string;
  experience: ChampionExperience;
  searchKeywords: string;
  targetCompanies: string;
  disqualifiers: string[];
  sellingPoints: string;
  askClient: AskClientItem[];
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
  office_city: string | null;
  start_date: string | null;
  project_about: string | null;
  responsibilities: string | null;
  screening_questions: {
    question: string;
    ideal_answer: string;
    from_request: boolean;
  }[];
  evidence: string[];
  missing: string[];
  // ── od v2 (starszy backend ich nie niesie) ──
  language?: string | null;
  contract_length?: string | null;
  experience?: Partial<Record<ExperienceKind, IntakeExperienceItem[]>>;
  search_keywords?: string | null;
  target_companies?: string | null;
  disqualifiers?: string[];
  selling_points?: string | null;
  ask_client?: string[];
  provenance?: Partial<Record<string, string>>;
}

export const EMPTY_EXPERIENCE_FORM: ChampionExperience = {
  domains: [],
  certifications: [],
  regulations: [],
  notes: "",
};

export const EMPTY_INTAKE_FORM: IntakeForm = {
  title: "",
  must: [],
  nice: [],
  seniorityYears: null,
  rateBudget: "",
  rateNote: null,
  remotePolicy: "",
  onsiteDays: "",
  city: "",
  startDate: "",
  about: "",
  responsibilities: "",
  questions: [],
  language: "",
  contractLength: "",
  experience: EMPTY_EXPERIENCE_FORM,
  searchKeywords: "",
  targetCompanies: "",
  disqualifiers: [],
  sellingPoints: "",
  askClient: [],
  provenance: {},
};

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

export function formFromIntake(intake: RequestIntakeResponse): IntakeForm {
  const provenance: IntakeForm["provenance"] = {};
  for (const [key, basis] of Object.entries(intake.provenance ?? {})) {
    if (BASES.includes(basis as FieldBasis))
      provenance[key as ProvenanceKey] = basis as FieldBasis;
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
    searchKeywords: intake.search_keywords ?? "",
    targetCompanies: intake.target_companies ?? "",
    disqualifiers: intake.disqualifiers ?? [],
    sellingPoints: intake.selling_points ?? "",
    askClient: (intake.ask_client ?? []).map((text) => ({
      key: newQuestionKey(),
      text,
    })),
    provenance,
    title: intake.role_name ?? "",
    must: intake.must ?? [],
    nice: intake.nice ?? [],
    seniorityYears: intake.seniority_min_years ?? null,
    rateBudget:
      intake.rate_budget_hourly != null
        ? String(intake.rate_budget_hourly)
        : "",
    rateNote: intake.rate_note ?? null,
    remotePolicy: intake.remote_policy ?? "",
    onsiteDays:
      intake.onsite_days_per_week != null
        ? String(intake.onsite_days_per_week)
        : "",
    city: intake.office_city ?? "",
    startDate: intake.start_date ?? "",
    about: intake.project_about ?? "",
    responsibilities: intake.responsibilities ?? "",
    questions: (intake.screening_questions ?? []).map((q) => ({
      key: newQuestionKey(),
      question: q.question,
      idealAnswer: q.ideal_answer ?? "",
      origin: q.from_request ? "request" : "ai",
    })),
  };
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
  | "questions";

export const MISSING_LABEL: Record<MissingCode, string> = {
  role: "rola",
  must: "must-have",
  budget: "budżet PLN/h",
  work_mode: "tryb pracy",
  office_days: "dni w biurze",
  office_city: "miasto biura",
  context: "opis projektu",
  questions: "drugie pytanie screeningowe",
};

/** Budżet jak w `JobCreate.rate_budget_hourly`: > 0 i ≤ 2000. */
export function parseBudget(value: string): number | null {
  const normalized = value.replace(/\s/g, "").replace(",", ".");
  if (!normalized) return null;
  const n = Number(normalized);
  return Number.isFinite(n) && n > 0 && n <= 2000 ? n : null;
}

export function parseOnsiteDays(value: string): number | null {
  if (value.trim() === "") return null;
  const n = Number(value);
  return Number.isInteger(n) && n >= 0 && n <= 7 ? n : null;
}

export function filledQuestions(form: IntakeForm): IntakeQuestionForm[] {
  return form.questions.filter((q) => q.question.trim().length > 0);
}

export function missingFor(form: IntakeForm): MissingCode[] {
  const missing: MissingCode[] = [];
  if (!form.title.trim()) missing.push("role");
  if (form.must.length === 0) missing.push("must");
  if (parseBudget(form.rateBudget) == null) missing.push("budget");
  if (!form.remotePolicy) {
    missing.push("work_mode");
  } else if (form.remotePolicy !== "remote") {
    if (parseOnsiteDays(form.onsiteDays) == null) missing.push("office_days");
    if (!form.city.trim()) missing.push("office_city");
  }
  if (!form.about.trim() && !form.responsibilities.trim())
    missing.push("context");
  if (filledQuestions(form).length < 2) missing.push("questions");
  return missing;
}

/** „Brakuje 2 rzeczy do searchu” — polska odmiana liczebnika. */
export function missingHeadline(count: number): string {
  if (count === 1) return "Brakuje 1 rzeczy do searchu";
  return `Brakuje ${count} rzeczy do searchu`;
}

// ── Payloady zapisu ──────────────────────────────────────────────────────────

/** `POST /api/jobs` — tylko to, co formularz naprawdę zna. */
export function buildJobPayload(
  form: IntakeForm,
  opts: { clientId: number; requestText: string; templateJobId: number | null },
): Record<string, unknown> {
  const remote = form.remotePolicy || null;
  const payload: Record<string, unknown> = {
    title: form.title.trim(),
    client_id: opts.clientId,
    auto_suggest_cc: true,
    remote_policy: remote,
    onsite_days_per_week:
      remote === "remote" ? null : parseOnsiteDays(form.onsiteDays),
  };
  const description = opts.requestText.trim();
  if (description) payload.description = description;
  if (form.must.length > 0) payload.must_skills = form.must;
  if (form.nice.length > 0) payload.nice_skills = form.nice;
  if (remote !== "remote" && form.city.trim())
    payload.location = form.city.trim();
  const budget = parseBudget(form.rateBudget);
  if (budget != null) payload.rate_budget_hourly = budget;
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
 * (od 09.2026): podstawy, stack, doświadczenie, frazy do wyszukiwarki,
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
      seniority_min_years: form.seniorityYears,
      rate_value: budget,
      work_mode: remote ? CHAMPION_WORK_MODE[remote] : null,
      onsite_days_per_week:
        remote === "remote" ? null : parseOnsiteDays(form.onsiteDays),
      candidate_location_pref:
        remote === "remote" ? null : form.city.trim() || null,
      start_date: form.startDate || null,
      language: form.language.trim() || null,
      contract_length: form.contractLength.trim() || null,
    },
    stack: {
      must: form.must.map((name) => ({ name })),
      nice: form.nice.map((name) => ({ name })),
    },
    experience: form.experience,
    search: {
      keywords: form.searchKeywords.trim(),
      target_companies: form.targetCompanies.trim(),
      disqualifiers: form.disqualifiers,
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
      deal_breaker: "",
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
  must_skills?: unknown;
  nice_skills?: unknown;
  champion_profile?: unknown;
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

/**
 * Wypełnia WYŁĄCZNIE puste pola formularza danymi rekrutacji-szablonu.
 * Rola zostaje z requestu (nowa rekrutacja nie udaje starej); pytania
 * dochodzą tylko wtedy, gdy formularz ma ich mniej niż dwa.
 */
export function applyTemplate(
  form: IntakeForm,
  src: TemplateSourceJob,
): IntakeForm {
  const next: IntakeForm = { ...form };
  const project = championSection(src.champion_profile, "project");
  if (next.must.length === 0) next.must = skillNames(src.must_skills);
  if (next.nice.length === 0) next.nice = skillNames(src.nice_skills);
  if (!next.rateBudget && src.rate_budget_hourly != null) {
    next.rateBudget = String(src.rate_budget_hourly);
  }
  if (!next.remotePolicy && src.remote_policy)
    next.remotePolicy = src.remote_policy;
  if (!next.onsiteDays && src.onsite_days_per_week != null) {
    next.onsiteDays = String(src.onsite_days_per_week);
  }
  if (!next.city && src.location) next.city = src.location;
  // Pola, które `POST /api/jobs` z `from_job_id` kopiuje z profilu źródłowego,
  // muszą trafić też do formularza: PUT profilu zaraz po utworzeniu wysyła je
  // i serwer scala sekcje płytko — puste pole w formularzu skasowałoby kopię.
  const search = championSection(src.champion_profile, "search");
  const client = championSection(src.champion_profile, "client");
  const basics = championSection(src.champion_profile, "basics");
  const text = (value: unknown) => (typeof value === "string" ? value : "");
  if (!next.searchKeywords) next.searchKeywords = text(search.keywords);
  if (!next.targetCompanies) next.targetCompanies = text(search.target_companies);
  if (next.disqualifiers.length === 0 && Array.isArray(search.disqualifiers)) {
    next.disqualifiers = search.disqualifiers.filter(
      (d): d is string => typeof d === "string" && d.trim().length > 0,
    );
  }
  if (!next.sellingPoints) next.sellingPoints = text(client.selling_points);
  if (!next.language) next.language = text(basics.language);
  if (!next.contractLength) next.contractLength = text(basics.contract_length);
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
          origin: "template",
        });
      }
    }
    next.questions = [...next.questions, ...added];
  }
  return next;
}
