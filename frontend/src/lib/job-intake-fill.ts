/**
 * `/jobs/new`: odczyt maila, pliku albo rekrutacji-szablonu wypełnia tylko
 * PUSTE pola formularza (decyzja D3, 10.10.2026).
 *
 * Do tej daty każdy odczyt zakładał formularz od nowa (`formFromIntake`
 * w miejsce stanu), więc zmiana źródła kasowała wpisane pola bez pytania.
 * Teraz: nietknięty formularz bierze odczyt w całości, a w formularzu, w którym
 * coś już jest, puste pole się wypełnia, takie samo zostaje, a inne dostaje
 * propozycję „W mailu: … [Użyj] [Zostaw]”. Wzorzec: `applyNoteProposal`
 * w `lib/screening-form.ts` (notatka w formularzu screeningu).
 *
 * Czysta logika — bez Reacta i sieci. Tekst requestu i podświetlenia trzyma
 * strona; tu są tylko pomocnicy do ich łączenia przy kolejnym odczycie.
 */

import type { ChampionExperience, ExperienceItem, ExperienceKind } from "@/lib/api";
import { EXPERIENCE_KINDS, hasExperience } from "@/lib/champion-experience";
import { formatIsoDatePl } from "@/lib/date-pl";
import { personNameKey } from "@/lib/hiring-manager";
import {
  filledQuestions,
  joinCities,
  newQuestionKey,
  parseBudget,
  parseHeadcount,
  splitCities,
  type AskClientItem,
  type FieldBasis,
  type IntakeForm,
  type IntakeQuestionForm,
  type ProvenanceKey,
  type QuestionOrigin,
  type RemotePolicyValue,
} from "@/lib/job-request-intake";
import { countPl } from "@/lib/plural-pl";
import {
  NICE_ROWS_MAX,
  REQUIRED_ROWS_MAX,
  filledRows,
  newRowKey,
  rowHead,
  type RequirementRowForm,
  type StoredRequirementRow,
} from "@/lib/requirement-rows";

/** Skąd przyszły dane: wklejona treść, wgrany plik albo inna rekrutacja. */
export type IntakeSource = "request" | "file" | "template";

/** Początek propozycji przy polu — mówi, gdzie stoi inna wartość. */
export const INTAKE_SOURCE_PREFIX: Record<IntakeSource, string> = {
  request: "W mailu",
  file: "W pliku",
  template: "W szablonie",
};

/**
 * Jednostka porównania: jedno pole albo pola, które mają sens tylko razem
 * (budżet „od–do” z uwagą, tryb pracy z dniami w biurze, termin z godziną).
 */
export const INTAKE_UNITS = [
  "title",
  "clientTitle",
  "hiringManager",
  "rows",
  "seniorityYears",
  "language",
  "budget",
  "workMode",
  "city",
  "deadline",
  "headcount",
  "startDate",
  "contractLength",
  "about",
  "responsibilities",
  "sellingPoints",
  "questions",
  "targetCompanies",
] as const;

export type IntakeUnit = (typeof INTAKE_UNITS)[number];

export const INTAKE_UNIT_LABEL: Record<IntakeUnit, string> = {
  title: "Rola",
  clientTitle: "Nazwa od klienta",
  hiringManager: "Hiring manager",
  rows: "Wymagania",
  seniorityYears: "Lata doświadczenia",
  language: "Język pracy",
  budget: "Budżet PLN/h",
  workMode: "Tryb pracy",
  city: "Miasta biura",
  deadline: "Termin",
  headcount: "Liczba osób",
  startDate: "Start",
  contractLength: "Długość projektu",
  about: "Co to za projekt",
  responsibilities: "Obowiązki",
  sellingPoints: "Co przekona kandydata",
  questions: "Pytania do kandydata",
  targetCompanies: "Firmy docelowe",
};

/** Chip źródła przy polu, którego dotyczy jednostka (nie każda go ma). */
const UNIT_PROVENANCE: Partial<Record<IntakeUnit, ProvenanceKey>> = {
  title: "role",
  clientTitle: "client_title",
  hiringManager: "hiring_manager",
  rows: "requirements",
  budget: "rate",
  workMode: "work_mode",
  deadline: "deadline",
  headcount: "headcount",
  about: "about",
  responsibilities: "responsibilities",
  sellingPoints: "selling_points",
  questions: "questions",
  targetCompanies: "target_companies",
};

/** Pytanie w propozycji — bez klucza (klucz powstaje przy „Dodaj”). */
export interface IntakeOfferQuestion {
  question: string;
  idealAnswer: string;
  dealBreaker: string;
  origin: QuestionOrigin;
}

/**
 * Propozycja przy polu: odczyt ma inną wartość niż ta wpisana. Zwykły obiekt
 * — jedzie w autozapisie formularza, więc przeżywa „Dokończę później”.
 */
export interface IntakeOffer {
  /** Jedna żywa propozycja na jednostkę — kolejny odczyt zastępuje poprzednią. */
  id: IntakeUnit;
  unit: IntakeUnit;
  source: IntakeSource;
  /** Nazwa pola — do nazwy dostępnej przycisków. */
  label: string;
  /** Wartość z odczytu słowami („150–170 PLN/h”, „Hybrydowo, 2 dni w tygodniu”). */
  text: string;
  /** Źródło, które pole dostanie po „Użyj”. */
  basis: FieldBasis;
  /** Pola do ustawienia po „Użyj”. */
  patch?: Partial<IntakeForm>;
  /** Jednostka `rows`: wymagania z odczytu, których formularz nie ma. */
  rows?: StoredRequirementRow[];
  /** Jednostka `questions`: pytania z odczytu, których formularz nie ma. */
  questions?: IntakeOfferQuestion[];
}

/** Pole proste przed wypełnieniem i po nim — cofamy tylko nietknięte potem. */
interface FieldChange {
  key: keyof IntakeForm;
  before: unknown;
  after: unknown;
}

/**
 * Co wypełnienie zmieniło — jako łatka, nie migawka całego formularza.
 * Migawka cofałaby też wszystko, co Delivery Lead poprawił PO odczycie.
 */
export interface IntakeFillUndo {
  fields: FieldChange[];
  rows: RequirementRowForm[];
  questions: IntakeQuestionForm[];
  askClient: AskClientItem[];
  lists: Record<ListKey, string[]>;
  experience: Record<ExperienceKind, ExperienceItem[]>;
  provenance: {
    key: ProvenanceKey;
    before: FieldBasis | undefined;
    after: FieldBasis | undefined;
  }[];
}

export interface IntakeReadResult {
  form: IntakeForm;
  /** Ile pól (jednostek) wypełnił odczyt. */
  filled: number;
  offers: IntakeOffer[];
  undo: IntakeFillUndo;
}

const LIST_KEYS = [
  "descriptive",
  "disqualifiers",
  "intakeNotes",
  "droppedRequirements",
  "searchExclude",
] as const;
type ListKey = (typeof LIST_KEYS)[number];


/**
 * Pola proste formularza — wszystkie poza listami. Pola decyzji człowieka
 * (krytyczne, kategoria, tytuł dla zespołu, numer wpisany ręcznie) są tu po
 * to, żeby cofnięcie odczytu w nietkniętym formularzu było pełne; w formularzu
 * z wpisanymi polami odczyt ich nie dotyka.
 */
const FIELD_KEYS: readonly (keyof IntakeForm)[] = [
  "title",
  "clientTitle",
  "referenceHint",
  "referenceOverride",
  "workingTitle",
  "workingTitleTouched",
  "noCritical",
  "seniorityYears",
  "rateBudget",
  "rateBudgetMin",
  "rateNote",
  "remotePolicy",
  "onsiteDays",
  "onsiteDaysPeriod",
  "city",
  "startDate",
  "about",
  "responsibilities",
  "language",
  "contractLength",
  "targetCompanies",
  "sellingPoints",
  "hiringManager",
  "hiringManagerNotProvided",
  "deadline",
  "deadlineTime",
  "deadlineNotProvided",
  "headcount",
  "competenceCategoryId",
  "suggestedCategoryId",
  "categoryConfirmed",
  "championExtras",
];

const WORK_MODE_LABEL: Record<RemotePolicyValue, string> = {
  remote: "Zdalnie",
  hybrid: "Hybrydowo",
  onsite: "Biuro",
};

/** Długi opis w propozycji jest przycinany — „Użyj” i tak wstawia całość. */
const OFFER_TEXT_MAX = 240;

const blank = (value: string | null | undefined): boolean => !String(value ?? "").trim();

/** Porównanie bez wielkości liter i z jedną spacją między słowami. */
const fold = (value: string | null | undefined): string =>
  String(value ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase("pl");

const sameValue = (a: unknown, b: unknown): boolean =>
  a === b || JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

function clip(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= OFFER_TEXT_MAX) return flat;
  const cut = flat.slice(0, OFFER_TEXT_MAX);
  const space = cut.lastIndexOf(" ");
  return `${cut.slice(0, space > OFFER_TEXT_MAX / 2 ? space : OFFER_TEXT_MAX)}…`;
}

/**
 * Formularz, w którym człowiek jeszcze nic nie wpisał ani nie zdecydował.
 * Pusty wiersz wymagań, puste pytanie i podpowiedź kategorii bez potwierdzenia
 * to nie praca — taki formularz bierze odczyt w całości.
 */
export function isPristineIntake(form: IntakeForm): boolean {
  return (
    blank(form.title) &&
    blank(form.clientTitle) &&
    blank(form.referenceHint) &&
    form.referenceOverride == null &&
    !form.workingTitleTouched &&
    filledRows(form.rows).length === 0 &&
    !form.noCritical &&
    form.descriptive.length === 0 &&
    form.seniorityYears == null &&
    blank(form.rateBudget) &&
    blank(form.rateBudgetMin) &&
    blank(form.rateNote) &&
    form.intakeNotes.length === 0 &&
    form.droppedRequirements.length === 0 &&
    form.remotePolicy === "" &&
    blank(form.onsiteDays) &&
    blank(form.city) &&
    blank(form.startDate) &&
    blank(form.about) &&
    blank(form.responsibilities) &&
    form.questions.every(
      (q) => blank(q.question) && blank(q.idealAnswer) && blank(q.dealBreaker),
    ) &&
    blank(form.language) &&
    blank(form.contractLength) &&
    !hasExperience(form.experience) &&
    blank(form.experience.notes) &&
    form.searchExclude.length === 0 &&
    blank(form.targetCompanies) &&
    form.disqualifiers.length === 0 &&
    blank(form.sellingPoints) &&
    form.askClient.every((item) => blank(item.text)) &&
    form.hiringManager == null &&
    !form.hiringManagerNotProvided &&
    blank(form.deadline) &&
    !form.deadlineNotProvided &&
    blank(form.headcount) &&
    !form.categoryConfirmed &&
    form.championExtras == null
  );
}

// ── Wymagania i pytania ──────────────────────────────────────────────────────

const headKey = (words: readonly string[]): string => fold(rowHead(words));

/**
 * Wymagania z odczytu, których formularz jeszcze nie ma (po pierwszym słowie
 * wiersza), z poziomem jak przy „Dodaj wymaganie”: obowiązkowe, a po dziesiątym
 * — „mile widziane”. Krytycznych odczyt nie nadaje nigdy.
 */
function newRequirementRows(
  existing: readonly RequirementRowForm[],
  incoming: readonly StoredRequirementRow[],
): RequirementRowForm[] {
  const current = filledRows(existing);
  const heads = new Set(current.map((row) => headKey(row.words)));
  let required = current.filter((row) => row.level !== "nice").length;
  let nice = current.length - required;
  const out: RequirementRowForm[] = [];
  for (const row of incoming) {
    const head = headKey(row.words);
    if (!head || heads.has(head)) continue;
    let level: RequirementRowForm["level"] = row.level === "nice" ? "nice" : "must";
    if (level === "must" && required >= REQUIRED_ROWS_MAX) level = "nice";
    if (level === "nice" && nice >= NICE_ROWS_MAX) continue;
    if (level === "nice") nice += 1;
    else required += 1;
    heads.add(head);
    out.push({ key: newRowKey(), words: [...row.words], level });
  }
  return out;
}

function newQuestions(
  existing: readonly IntakeQuestionForm[],
  incoming: readonly IntakeOfferQuestion[],
): IntakeQuestionForm[] {
  const known = new Set(existing.map((q) => fold(q.question)));
  const out: IntakeQuestionForm[] = [];
  for (const item of incoming) {
    const key = fold(item.question);
    if (!key || known.has(key)) continue;
    known.add(key);
    out.push({
      key: newQuestionKey(),
      question: item.question,
      idealAnswer: item.idealAnswer,
      dealBreaker: item.dealBreaker,
      origin: item.origin,
      // Z odczytu i z szablonu pytanie czeka na zatwierdzenie Delivery Leada.
      approved: false,
    });
  }
  return out;
}

const withoutKey = (q: IntakeQuestionForm): IntakeOfferQuestion => ({
  question: q.question,
  idealAnswer: q.idealAnswer,
  dealBreaker: q.dealBreaker,
  origin: q.origin,
});

// ── Porównania jednostek ─────────────────────────────────────────────────────

const budgetKey = (value: string): string => {
  const parsed = parseBudget(value);
  return parsed != null ? String(parsed) : fold(value);
};

const headcountKey = (value: string): string => {
  const parsed = parseHeadcount(value);
  return parsed != null ? String(parsed) : fold(value);
};

const cityKey = (value: string): string =>
  splitCities(value)
    .map((city) => fold(city))
    .sort()
    .join("|");

function samePerson(a: IntakeForm["hiringManager"], b: IntakeForm["hiringManager"]): boolean {
  if (!a || !b) return a == null && b == null;
  if (a.kind === "contact" && b.kind === "contact") return a.id === b.id;
  return personNameKey(a.name) === personNameKey(b.name);
}

function workModeText(form: Pick<IntakeForm, "remotePolicy" | "onsiteDays" | "onsiteDaysPeriod">): string {
  if (!form.remotePolicy) return "";
  const mode = WORK_MODE_LABEL[form.remotePolicy];
  const days = Number(form.onsiteDays);
  if (form.remotePolicy === "remote" || blank(form.onsiteDays) || !Number.isFinite(days)) return mode;
  const period = form.onsiteDaysPeriod === "month" ? "miesiącu" : "tygodniu";
  return `${mode}, ${days === 1 ? "1 dzień" : `${days} dni`} w ${period}`;
}

/** „20.10.2026”; wartość, której nie da się odczytać jako daty, zostaje jak jest. */
function datePl(value: string): string {
  const formatted = formatIsoDatePl(value);
  return formatted === "—" ? value : formatted;
}

function deadlineText(form: Pick<IntakeForm, "deadline" | "deadlineTime">): string {
  const date = datePl(form.deadline);
  return form.deadlineTime ? `${date}, ${form.deadlineTime}` : date;
}

function budgetText(form: Pick<IntakeForm, "rateBudget" | "rateBudgetMin">): string {
  const high = form.rateBudget.trim();
  const low = form.rateBudgetMin.trim();
  if (low && high) return `${low}–${high} PLN/h`;
  return high ? `${high} PLN/h` : `od ${low} PLN/h`;
}

// ── Odczyt → formularz ───────────────────────────────────────────────────────

/** Pola tekstowe porównywane pojedynczo. */
const TEXT_UNITS: {
  unit: IntakeUnit;
  key: "title" | "language" | "startDate" | "contractLength" | "about" | "responsibilities" | "sellingPoints" | "targetCompanies";
  text?: (value: string) => string;
}[] = [
  { unit: "title", key: "title" },
  { unit: "language", key: "language" },
  { unit: "startDate", key: "startDate", text: datePl },
  { unit: "contractLength", key: "contractLength" },
  { unit: "about", key: "about" },
  { unit: "responsibilities", key: "responsibilities" },
  { unit: "sellingPoints", key: "sellingPoints" },
  { unit: "targetCompanies", key: "targetCompanies" },
];

/**
 * Wkłada odczyt do formularza. `read` to odczyt już w kształcie formularza:
 * `formFromIntake(intake)` dla maila i pliku, `applyTemplate(pusty, …)` dla
 * rekrutacji-szablonu.
 *
 * Nigdy nie dotyka decyzji człowieka: „Brak krytycznych”, kategorii, tytułu
 * dla zespołu, numeru wpisanego ręcznie ani poziomów istniejących wierszy.
 */
export function applyIntakeRead(
  current: IntakeForm,
  read: IntakeForm,
  opts: { source?: IntakeSource; basis?: FieldBasis } = {},
): IntakeReadResult {
  const source = opts.source ?? "request";
  const fallback: FieldBasis = opts.basis ?? (source === "template" ? "client_history" : "request");
  const pristine = isPristineIntake(current);
  // Nietknięty formularz liczymy tak samo (żeby wiedzieć, ile pól wypełniono),
  // ale wynik to odczyt w całości — bez zgadywania, co jest „puste”.
  const base = pristine ? { ...current, rows: [], questions: [], askClient: [] } : current;
  const next: IntakeForm = { ...base, provenance: { ...base.provenance } };
  const offers: IntakeOffer[] = [];
  let filled = 0;

  const basisOf = (unit: IntakeUnit): FieldBasis => {
    const key = UNIT_PROVENANCE[unit];
    return (key && read.provenance?.[key]) || fallback;
  };
  const mark = (unit: IntakeUnit) => {
    const key = UNIT_PROVENANCE[unit];
    if (key) next.provenance[key] = basisOf(unit);
    filled += 1;
  };
  const offer = (unit: IntakeUnit, text: string, extra: Partial<IntakeOffer>) =>
    offers.push({
      id: unit,
      unit,
      source,
      label: INTAKE_UNIT_LABEL[unit],
      text: clip(text),
      basis: basisOf(unit),
      ...extra,
    });

  for (const { unit, key, text } of TEXT_UNITS) {
    const proposed = read[key];
    if (blank(proposed)) continue;
    if (blank(next[key])) {
      next[key] = proposed;
      mark(unit);
    } else if (fold(next[key]) !== fold(proposed)) {
      offer(unit, text ? text(proposed) : proposed, { patch: { [key]: proposed } });
    }
  }

  // Nazwa od klienta niesie numer zapytania — idą razem.
  if (!blank(read.clientTitle)) {
    if (blank(next.clientTitle)) {
      next.clientTitle = read.clientTitle;
      if (!blank(read.referenceHint)) next.referenceHint = read.referenceHint;
      mark("clientTitle");
    } else if (fold(next.clientTitle) !== fold(read.clientTitle)) {
      offer("clientTitle", read.clientTitle, {
        patch: {
          clientTitle: read.clientTitle,
          ...(blank(read.referenceHint) ? {} : { referenceHint: read.referenceHint }),
        },
      });
    }
  }
  if (blank(next.referenceHint) && !blank(read.referenceHint)) next.referenceHint = read.referenceHint;

  if (read.seniorityYears != null) {
    if (next.seniorityYears == null) {
      next.seniorityYears = read.seniorityYears;
      mark("seniorityYears");
    } else if (next.seniorityYears !== read.seniorityYears) {
      offer("seniorityYears", String(read.seniorityYears), {
        patch: { seniorityYears: read.seniorityYears },
      });
    }
  }

  // Budżet: „od”, „do” i uwaga z odczytu mają sens tylko razem.
  const budget = {
    rateBudget: read.rateBudget,
    rateBudgetMin: read.rateBudgetMin,
    rateNote: read.rateNote,
  };
  const budgetEmpty = blank(next.rateBudget) && blank(next.rateBudgetMin);
  if (blank(read.rateBudget) && blank(read.rateBudgetMin)) {
    // Sama uwaga („stawka dzienna — nie przeliczam”) tłumaczy puste pole.
    if (budgetEmpty && blank(next.rateNote) && !blank(read.rateNote)) next.rateNote = read.rateNote;
  } else if (budgetEmpty) {
    Object.assign(next, budget);
    mark("budget");
  } else if (
    budgetKey(next.rateBudget) !== budgetKey(read.rateBudget) ||
    budgetKey(next.rateBudgetMin) !== budgetKey(read.rateBudgetMin)
  ) {
    offer("budget", budgetText(read), { patch: budget });
  }

  // Tryb pracy z dniami w biurze.
  if (read.remotePolicy) {
    const mode = {
      remotePolicy: read.remotePolicy,
      onsiteDays: read.onsiteDays,
      onsiteDaysPeriod: read.onsiteDaysPeriod,
    };
    const readHasDays = read.remotePolicy !== "remote" && !blank(read.onsiteDays);
    if (!next.remotePolicy) {
      Object.assign(next, mode);
      mark("workMode");
    } else if (next.remotePolicy !== read.remotePolicy) {
      offer("workMode", workModeText(read), { patch: mode });
    } else if (readHasDays && blank(next.onsiteDays)) {
      next.onsiteDays = read.onsiteDays;
      next.onsiteDaysPeriod = read.onsiteDaysPeriod;
      mark("workMode");
    } else if (
      readHasDays &&
      (fold(next.onsiteDays) !== fold(read.onsiteDays) ||
        next.onsiteDaysPeriod !== read.onsiteDaysPeriod)
    ) {
      offer("workMode", workModeText(read), { patch: mode });
    }
  }

  if (splitCities(read.city).length > 0) {
    if (blank(next.city)) {
      next.city = read.city;
      mark("city");
    } else if (cityKey(next.city) !== cityKey(read.city)) {
      offer("city", joinCities(splitCities(read.city)), { patch: { city: read.city } });
    }
  }

  // Termin: data z godziną; „Klient nie podał” to decyzja, której odczyt nie zdejmuje sam.
  if (!blank(read.deadline)) {
    const deadline = {
      deadline: read.deadline,
      deadlineTime: read.deadlineTime,
      deadlineNotProvided: false,
    };
    if (blank(next.deadline) && !next.deadlineNotProvided) {
      Object.assign(next, deadline);
      mark("deadline");
    } else if (next.deadline !== read.deadline) {
      offer("deadline", deadlineText(read), { patch: deadline });
    } else if (blank(next.deadlineTime) && !blank(read.deadlineTime)) {
      next.deadlineTime = read.deadlineTime;
      mark("deadline");
    } else if (!blank(read.deadlineTime) && next.deadlineTime !== read.deadlineTime) {
      offer("deadline", deadlineText(read), { patch: deadline });
    }
  }

  if (!blank(read.headcount)) {
    if (blank(next.headcount)) {
      next.headcount = read.headcount;
      mark("headcount");
    } else if (headcountKey(next.headcount) !== headcountKey(read.headcount)) {
      offer("headcount", read.headcount, { patch: { headcount: read.headcount } });
    }
  }

  if (read.hiringManager) {
    const person = { hiringManager: read.hiringManager, hiringManagerNotProvided: false };
    if (next.hiringManager == null && !next.hiringManagerNotProvided) {
      Object.assign(next, person);
      mark("hiringManager");
    } else if (!samePerson(next.hiringManager, read.hiringManager)) {
      offer("hiringManager", read.hiringManager.name, { patch: person });
    }
  }

  // Wymagania: bez wpisanych wierszy bierzemy odczyt; inaczej jedna propozycja.
  const readRows = filledRows(read.rows);
  if (readRows.length > 0) {
    if (filledRows(next.rows).length === 0) {
      next.rows = read.rows;
      mark("rows");
    } else {
      const stored = readRows.map((row) => ({ words: row.words, level: row.level }));
      const added = newRequirementRows(next.rows, stored);
      if (added.length > 0) {
        const names = added.map((row) => rowHead(row.words)).join(", ");
        offer(
          "rows",
          `jeszcze ${countPl(added.length, "wymaganie", "wymagania", "wymagań")}: ${names}`,
          { rows: stored },
        );
      }
    }
  }

  // Pytania: do dwóch dopisujemy same (tyle wymaga publikacja), potem pytamy.
  const readQuestions = filledQuestions(read).map(withoutKey);
  if (readQuestions.length > 0) {
    if (filledQuestions(next).length < 2) {
      const known = new Set(next.questions.map((q) => fold(q.question)));
      const added = pristine
        ? read.questions
        : filledQuestions(read).filter((q) => !known.has(fold(q.question)));
      if (added.length > 0) {
        next.questions = [...next.questions, ...added.map((q) => ({ ...q, approved: false }))];
        mark("questions");
      }
    } else {
      const added = newQuestions(next.questions, readQuestions);
      if (added.length > 0) {
        offer(
          "questions",
          `jeszcze ${countPl(added.length, "pytanie", "pytania", "pytań")}: ${added
            .map((q) => q.question)
            .join("; ")}`,
          { questions: readQuestions },
        );
      }
    }
  }

  // Listy: dopisujemy to, czego jeszcze nie ma.
  for (const key of ["descriptive", "disqualifiers", "intakeNotes", "droppedRequirements"] as const) {
    const known = new Set(next[key].map((item) => fold(item)));
    const added = read[key].filter((item) => !blank(item) && !known.has(fold(item)));
    if (added.length === 0) continue;
    next[key] = [...next[key], ...added];
    if (key === "disqualifiers") next.provenance.disqualifiers = read.provenance?.disqualifiers ?? fallback;
    // Uwagi z odczytu to nie pola — nie liczymy ich jako wypełnienia.
    if (key === "descriptive" || key === "disqualifiers") filled += 1;
  }
  // Wykluczenia zawężają wyniki — dopisane po cichu ukryłyby kandydatów.
  if (next.searchExclude.length === 0 && read.searchExclude.length > 0) {
    next.searchExclude = read.searchExclude;
    filled += 1;
  }
  const asked = new Set(next.askClient.map((item) => fold(item.text)));
  const newAsks = read.askClient.filter((item) => !blank(item.text) && !asked.has(fold(item.text)));
  if (newAsks.length > 0) {
    next.askClient = [...next.askClient, ...newAsks];
    next.provenance.ask_client = read.provenance?.ask_client ?? fallback;
    filled += 1;
  }
  let experienceAdded = false;
  const experience: ChampionExperience = { ...next.experience };
  for (const kind of EXPERIENCE_KINDS) {
    const current = experience[kind] ?? [];
    const known = new Set(current.map((item) => fold(item.name)));
    const added = (read.experience[kind] ?? []).filter(
      (item) => !blank(item.name) && !known.has(fold(item.name)),
    );
    if (added.length === 0) continue;
    experience[kind] = [...current, ...added];
    experienceAdded = true;
  }
  if (experienceAdded) {
    next.experience = experience;
    next.provenance.experience = read.provenance?.experience ?? fallback;
    filled += 1;
  }

  // Sekcje pliku Championa bez pola w formularzu: bierzemy pierwsze, które
  // przyszły — drugiego pliku nie mieszamy z pierwszym po cichu.
  if (next.championExtras == null && read.championExtras != null)
    next.championExtras = read.championExtras;

  if (pristine) return { form: read, filled, offers: [], undo: fillUndo(current, read) };
  return { form: next, filled, offers, undo: fillUndo(current, next) };
}

// ── „Użyj” przy propozycji ───────────────────────────────────────────────────

/** „Użyj” / „Dodaj”: wartość z odczytu trafia do pola razem ze swoim źródłem. */
export function acceptIntakeOffer(form: IntakeForm, offer: IntakeOffer): IntakeForm {
  const key = UNIT_PROVENANCE[offer.unit];
  const provenance = key ? { ...form.provenance, [key]: offer.basis } : form.provenance;
  if (offer.unit === "rows") {
    const added = newRequirementRows(form.rows, offer.rows ?? []);
    if (added.length === 0) return form;
    // Pusty wiersz z edytora nie może zostać między wymaganiami.
    return { ...form, rows: [...form.rows.filter((row) => row.words.length > 0), ...added], provenance };
  }
  if (offer.unit === "questions") {
    const added = newQuestions(form.questions, offer.questions ?? []);
    if (added.length === 0) return form;
    return { ...form, questions: [...form.questions, ...added], provenance };
  }
  return { ...form, ...(offer.patch ?? {}), provenance };
}

/** Kolejny odczyt zastępuje propozycję tego samego pola; pozostałe zostają. */
export function mergeIntakeOffers(previous: readonly IntakeOffer[], next: readonly IntakeOffer[]): IntakeOffer[] {
  const replaced = new Set(next.map((offer) => offer.unit));
  return [...previous.filter((offer) => !replaced.has(offer.unit)), ...next];
}

function patchApplied(form: IntakeForm, patch: Partial<IntakeForm>): boolean {
  return (Object.keys(patch) as (keyof IntakeForm)[]).every((key) => {
    const mine = form[key];
    const theirs = patch[key];
    if (key === "city") return cityKey(String(mine ?? "")) === cityKey(String(theirs ?? ""));
    if (key === "hiringManager")
      return samePerson(mine as IntakeForm["hiringManager"], theirs as IntakeForm["hiringManager"]);
    if (typeof mine === "string" || typeof theirs === "string")
      return fold(mine as string) === fold(theirs as string);
    return sameValue(mine, theirs);
  });
}

/**
 * Propozycje, które nadal coś zmieniają. Gdy Delivery Lead sam wpisze tę samą
 * wartość albo doda te same wymagania, propozycja znika bez klikania.
 */
export function liveIntakeOffers(form: IntakeForm, offers: readonly IntakeOffer[]): IntakeOffer[] {
  return offers.filter((offer) => {
    if (offer.unit === "rows") return newRequirementRows(form.rows, offer.rows ?? []).length > 0;
    if (offer.unit === "questions")
      return newQuestions(form.questions, offer.questions ?? []).length > 0;
    return offer.patch != null && !patchApplied(form, offer.patch);
  });
}

const SOURCES: readonly IntakeSource[] = ["request", "file", "template"];

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  value != null && typeof value === "object" && !Array.isArray(value);

function storedRowsFrom(raw: unknown): StoredRequirementRow[] {
  if (!Array.isArray(raw)) return [];
  const out: StoredRequirementRow[] = [];
  for (const row of raw) {
    if (!isPlainObject(row) || !Array.isArray(row.words)) continue;
    const words = row.words.filter((word): word is string => typeof word === "string");
    if (words.length === 0) continue;
    out.push({ words, level: row.level === "nice" ? "nice" : "must" });
  }
  return out;
}

const QUESTION_ORIGINS: readonly QuestionOrigin[] = ["request", "ai", "template", "manual"];

function offerQuestionsFrom(raw: unknown): IntakeOfferQuestion[] {
  if (!Array.isArray(raw)) return [];
  const out: IntakeOfferQuestion[] = [];
  for (const item of raw) {
    if (!isPlainObject(item) || typeof item.question !== "string" || blank(item.question)) continue;
    out.push({
      question: item.question,
      idealAnswer: typeof item.idealAnswer === "string" ? item.idealAnswer : "",
      dealBreaker: typeof item.dealBreaker === "string" ? item.dealBreaker : "",
      origin: QUESTION_ORIGINS.includes(item.origin as QuestionOrigin)
        ? (item.origin as QuestionOrigin)
        : "request",
    });
  }
  return out;
}

/**
 * Propozycje z zapisanego formularza — tylko te o znanym kształcie, razem
 * z wnętrzem: zapis z `rows: [null]` wywracał render strony i formularza nie
 * dało się wznowić (przegląd kodu 11.10.2026).
 */
export function restoreIntakeOffers(saved: unknown): IntakeOffer[] {
  if (!Array.isArray(saved)) return [];
  const out: IntakeOffer[] = [];
  for (const item of saved) {
    if (!isPlainObject(item)) continue;
    const raw = item as Partial<IntakeOffer>;
    const unit = raw.unit as IntakeUnit;
    if (!INTAKE_UNITS.includes(unit)) continue;
    if (!SOURCES.includes(raw.source as IntakeSource) || typeof raw.text !== "string") continue;
    if (out.some((offer) => offer.unit === unit)) continue;
    const base = { ...(raw as IntakeOffer), id: unit, unit };
    if (unit === "rows") {
      const rows = storedRowsFrom(raw.rows);
      if (rows.length > 0) out.push({ ...base, rows, patch: undefined, questions: undefined });
    } else if (unit === "questions") {
      const questions = offerQuestionsFrom(raw.questions);
      if (questions.length > 0) out.push({ ...base, questions, patch: undefined, rows: undefined });
    } else if (isPlainObject(raw.patch)) {
      out.push({ ...base, rows: undefined, questions: undefined });
    }
  }
  return out;
}

// ── „Cofnij wypełnienie” ─────────────────────────────────────────────────────

function fillUndo(before: IntakeForm, after: IntakeForm): IntakeFillUndo {
  const fields: FieldChange[] = [];
  for (const key of FIELD_KEYS) {
    if (!sameValue(before[key], after[key]))
      fields.push({ key, before: before[key], after: after[key] });
  }
  const rowKeys = new Set(before.rows.map((row) => row.key));
  const questionKeys = new Set(before.questions.map((q) => q.key));
  const askKeys = new Set(before.askClient.map((item) => item.key));
  const lists = {} as Record<ListKey, string[]>;
  for (const key of LIST_KEYS) {
    const known = new Set(before[key].map((item) => fold(item)));
    lists[key] = after[key].filter((item) => !known.has(fold(item)));
  }
  const experience = {} as Record<ExperienceKind, ExperienceItem[]>;
  for (const kind of EXPERIENCE_KINDS) {
    const known = new Set((before.experience[kind] ?? []).map((item) => fold(item.name)));
    experience[kind] = (after.experience[kind] ?? []).filter(
      (item) => !known.has(fold(item.name)),
    );
  }
  const provenanceKeys = new Set([
    ...Object.keys(before.provenance ?? {}),
    ...Object.keys(after.provenance ?? {}),
  ]) as Set<ProvenanceKey>;
  const provenance: IntakeFillUndo["provenance"] = [];
  for (const key of provenanceKeys) {
    if (before.provenance?.[key] !== after.provenance?.[key])
      provenance.push({ key, before: before.provenance?.[key], after: after.provenance?.[key] });
  }
  return {
    fields,
    rows: after.rows.filter((row) => !rowKeys.has(row.key)),
    questions: after.questions.filter((q) => !questionKeys.has(q.key)),
    askClient: after.askClient.filter((item) => !askKeys.has(item.key)),
    lists,
    experience,
    provenance,
  };
}

/**
 * Cofa ostatnie wypełnienie. Pole wraca do poprzedniej wartości tylko wtedy,
 * gdy nadal ma tę, którą wpisał odczyt — poprawka zrobiona po odczycie zostaje.
 * To samo z wierszami wymagań i pytaniami: znika tylko to, czego nikt nie ruszył.
 */
export function undoIntakeFill(form: IntakeForm, undo: IntakeFillUndo): IntakeForm {
  const next: IntakeForm = { ...form, provenance: { ...form.provenance } };
  const record = next as unknown as Record<string, unknown>;
  for (const change of undo.fields) {
    if (sameValue(form[change.key], change.after)) record[change.key] = change.before;
  }
  const untouched = <T extends { key: string }>(current: readonly T[], written: readonly T[]) => {
    const byKey = new Map(written.map((item) => [item.key, item]));
    return current.filter((item) => !byKey.has(item.key) || !sameValue(item, byKey.get(item.key)));
  };
  next.rows = untouched(form.rows, undo.rows);
  next.questions = untouched(form.questions, undo.questions);
  next.askClient = untouched(form.askClient, undo.askClient);
  for (const key of LIST_KEYS) {
    const added = new Set(undo.lists[key].map((item) => fold(item)));
    if (added.size > 0) next[key] = form[key].filter((item) => !added.has(fold(item)));
  }
  const experience: ChampionExperience = { ...form.experience };
  for (const kind of EXPERIENCE_KINDS) {
    // Łatka zapisana przed 13.10.2026 nie zna `skills`.
    const written = undo.experience[kind] ?? [];
    if (written.length === 0) continue;
    experience[kind] = (form.experience[kind] ?? []).filter(
      (item) => !written.some((added) => sameValue(added, item)),
    );
  }
  next.experience = experience;
  for (const change of undo.provenance) {
    if (next.provenance[change.key] !== change.after) continue;
    if (change.before === undefined) delete next.provenance[change.key];
    else next.provenance[change.key] = change.before;
  }
  return next;
}

// ── Treść requestu i podświetlenia przy kolejnym odczycie ────────────────────

/** Kreska między treścią pierwszego i kolejnego odczytu. */
export const REQUEST_TEXT_SEPARATOR = "\n\n———\n\n";

/** Kolejny odczyt dopisuje treść pod kreską; ten sam tekst nie dubluje się. */
export function appendRequestText(previous: string, next: string): string {
  const added = next.trim();
  if (!added) return previous;
  if (!previous.trim()) return next;
  if (previous.includes(added)) return previous;
  return `${previous.trimEnd()}${REQUEST_TEXT_SEPARATOR}${added}`;
}

/** Podświetlenia w treści requestu: suma z obu odczytów, bez powtórzeń. */
export function mergeEvidence(previous: readonly string[], next: readonly string[]): string[] {
  const out = [...previous];
  const known = new Set(previous.map((item) => fold(item)));
  for (const item of next) {
    const key = fold(item);
    if (!key || known.has(key)) continue;
    known.add(key);
    out.push(item);
  }
  return out;
}
