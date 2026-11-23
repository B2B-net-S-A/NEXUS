/**
 * Wariant 2 „Powtórka” na `/jobs/new` (decyzja Artura 23.11.2026, makiety
 * https://claude.ai/artifact/5CT33qwDPP5vurc1CVY7yV, zakładka „Wariant 2”).
 *
 * 57% nowych rekrutacji (66 ze 116, kopia z 23.11) to powtórka requestu
 * u tego samego klienta. Po odczycie maila baner proponuje: weź poprzednią
 * rekrutację jako bazę, a z maila przeczytaj tylko różnice. Łączenie idzie
 * tą samą drogą co szablon i odczyt (D3): szablon wypełnia formularz,
 * odczyt maila dopisuje tylko PUSTE pola, a inna wartość to propozycja przy
 * polu. Wyjątki — z maila zawsze: nazwa od klienta z numerem i opis projektu
 * (to opis tego requestu, nie poprzedniego). Hiring manager nigdy nie kopiuje
 * się po cichu (u Nordei 36 różnych osób w 47 rekrutacjach): czeka jako
 * „Ta sama osoba co w <nr>” z „Potwierdź” / „Inna osoba”.
 */

import type { HiringManagerChoice } from "@/lib/hiring-manager";
import {
  INTAKE_UNIT_LABEL,
  applyIntakeRead,
  type ClientDefaults,
  type IntakeOffer,
} from "@/lib/job-intake-fill";
import {
  EMPTY_INTAKE_FORM,
  applyTemplate,
  filledQuestions,
  splitCities,
  type IntakeForm,
  type ProvenanceKey,
  type TemplateRows,
  type TemplateSourceJob,
} from "@/lib/job-request-intake";
import { countPl } from "@/lib/plural-pl";
import { filledRows, rowHead } from "@/lib/requirement-rows";

/** Pola `GET /api/jobs/{id}`, które Powtórka bierze ponad zwykły szablon. */
export interface RepeatSourceJob extends TemplateSourceJob {
  deadline_not_provided?: boolean | null;
  competence_category_id?: number | null;
  hiring_manager_contact_id?: number | null;
  hiring_manager_name?: string | null;
  /** Numer zapytania klienta (np. „43260”) — tak DL nazywa poprzedni request. */
  client_reference?: string | null;
}

/** Poprzednia rekrutacja w kształcie formularza i jej hiring manager (osobno). */
export interface RepeatTemplate {
  form: IntakeForm;
  hiringManager: HiringManagerChoice | null;
  /** „43260” (numer zapytania klienta), a bez niego id rekrutacji. */
  label: string;
}

const blank = (value: unknown): boolean => !String(value ?? "").trim();

/**
 * Formularz z poprzedniej rekrutacji: zwykły szablon (`applyTemplate`) plus to,
 * co przy powtórce jest tym samym requestem — krytyczne, „Klient nie podał”
 * przy terminie i kategoria. Termin-data nie przechodzi: należała do starego
 * requestu. Hiring manager wraca osobno, do potwierdzenia.
 */
export function repeatTemplate(
  src: RepeatSourceJob,
  converted: TemplateRows | null,
): RepeatTemplate {
  let form = applyTemplate({ ...EMPTY_INTAKE_FORM }, src, converted, { keepCritical: true });
  if (src.deadline_not_provided) form = { ...form, deadlineNotProvided: true };
  if (src.competence_category_id != null) {
    form = {
      ...form,
      competenceCategoryId: src.competence_category_id,
      categoryConfirmed: true,
    };
  }
  // Plakietka „z <nr>” przy każdym polu, które przyszło z szablonu.
  const provenance = { ...form.provenance };
  const filled: [ProvenanceKey, boolean][] = [
    ["requirements", filledRows(form.rows).length > 0],
    ["rate", !blank(form.rateBudget) || !blank(form.rateBudgetMin)],
    ["work_mode", form.remotePolicy !== ""],
    ["about", !blank(form.about)],
    ["responsibilities", !blank(form.responsibilities)],
    ["selling_points", !blank(form.sellingPoints)],
    ["target_companies", !blank(form.targetCompanies)],
    ["questions", filledQuestions(form).length > 0],
    ["deadline", form.deadlineNotProvided],
    ["headcount", !blank(form.headcount)],
  ];
  for (const [key, has] of filled) if (has) provenance[key] = "client_history";
  form = { ...form, provenance };
  const hiringManager: HiringManagerChoice | null =
    src.hiring_manager_contact_id != null && !blank(src.hiring_manager_name)
      ? {
          kind: "contact",
          id: src.hiring_manager_contact_id,
          name: String(src.hiring_manager_name).trim(),
        }
      : null;
  const label = String(src.client_reference ?? "").trim() || String(src.id);
  return { form, hiringManager, label };
}

/** Wynik „Użyj <nr> i przeczytaj z maila tylko różnice”. */
export interface RepeatMerge {
  form: IntakeForm;
  /** Propozycje przy polach: różnice z maila i hiring manager z szablonu. */
  offers: IntakeOffer[];
  /** Co przyszło z maila (do paska i do kolumny „Z nowego maila”). */
  fromMail: string[];
  /** Pola, przy których mail ma inną wartość niż szablon. */
  differences: string[];
  /** Ile pól wypełniło łączenie (szablon i mail razem). */
  filled: number;
}

/** Wartości, po których poznajemy, że pole wypełnił mail, a nie szablon. */
const MAIL_FILLED: [string, (form: IntakeForm) => unknown][] = [
  ["rola", (f) => f.title],
  ["hiring manager", (f) => f.hiringManager?.name],
  ["wymagania", (f) => filledRows(f.rows).length || ""],
  ["lata doświadczenia", (f) => f.seniorityYears ?? ""],
  ["budżet", (f) => `${f.rateBudgetMin}${f.rateBudget}`],
  ["tryb pracy", (f) => f.remotePolicy],
  ["miasta", (f) => f.city],
  ["termin", (f) => (f.provenance.deadline === "client_pattern" ? "" : f.deadline)],
  ["liczba osób", (f) => (f.provenance.headcount === "client_pattern" ? "" : f.headcount)],
  ["najważniejsze zadanie", (f) => f.keyTask],
  ["pytania", (f) => filledQuestions(f).length || ""],
  ["język", (f) => f.language],
];

/**
 * Szablon + odczyt maila. Z maila zawsze: nazwa od klienta z numerem, opis
 * projektu i obowiązki. Resztę mail tylko dopełnia (D3): puste pole bierze
 * wartość z maila, inna wartość czeka jako propozycja „W mailu: …”.
 */
export function mergeRepeat(
  template: RepeatTemplate,
  read: IntakeForm,
  opts: { clientDefaults?: ClientDefaults | null } = {},
): RepeatMerge {
  const base: IntakeForm = { ...template.form, provenance: { ...template.form.provenance } };
  const fromMail: string[] = [];
  if (!blank(read.clientTitle)) {
    base.clientTitle = read.clientTitle;
    base.referenceHint = read.referenceHint;
    base.provenance.client_title = read.provenance.client_title ?? "request";
    fromMail.push(blank(read.referenceHint) ? "nazwa" : "nazwa i numer");
  }
  if (!blank(read.about)) {
    base.about = read.about;
    base.provenance.about = read.provenance.about ?? "request";
    fromMail.push("opis projektu");
  }
  if (!blank(read.responsibilities)) {
    base.responsibilities = read.responsibilities;
    base.provenance.responsibilities = read.provenance.responsibilities ?? "request";
    fromMail.push("obowiązki");
  }
  const result = applyIntakeRead(base, read, {
    source: "request",
    clientDefaults: opts.clientDefaults ?? null,
  });
  for (const [label, value] of MAIL_FILLED) {
    if (blank(value(base)) && !blank(value(result.form))) fromMail.push(label);
  }
  const offers = [...result.offers];
  const form = result.form;
  if (template.hiringManager && form.hiringManager == null && !form.hiringManagerNotProvided) {
    offers.push({
      id: "hiringManager",
      unit: "hiringManager",
      source: "template",
      label: INTAKE_UNIT_LABEL.hiringManager,
      text: template.hiringManager.name,
      basis: "client_history",
      patch: { hiringManager: template.hiringManager, hiringManagerNotProvided: false },
      sourceLabel: template.label,
    });
  }
  const differences = result.offers.map((offer) => {
    const label = INTAKE_UNIT_LABEL[offer.unit];
    return `${label.charAt(0).toLowerCase()}${label.slice(1)}`;
  });
  return {
    form,
    offers,
    fromMail,
    differences,
    filled: templateFilledCount(template.form) + fromMail.length,
  };
}

function templateFilledCount(form: IntakeForm): number {
  return Object.values(form.provenance).filter((basis) => basis === "client_history").length;
}

const WORK_MODE: Record<string, string> = {
  remote: "zdalnie",
  hybrid: "hybrydowo",
  onsite: "biuro",
};

/** Kolumna „Weźmiemy z <nr>” — krótko, co przyjdzie z poprzedniej rekrutacji. */
export function repeatTakeSummary(template: RepeatTemplate): string[] {
  const f = template.form;
  const parts: string[] = [];
  const rows = filledRows(f.rows);
  if (rows.length > 0) {
    const critical = rows.filter((row) => row.level === "critical").map((row) => rowHead(row.words));
    parts.push(
      `${countPl(rows.length, "wymaganie", "wymagania", "wymagań")}${
        critical.length > 0 ? ` (krytyczne: ${critical.join(", ")})` : ""
      }`,
    );
  }
  const questions = filledQuestions(f);
  if (questions.length > 0) {
    const withBreaker = questions.filter((q) => !blank(q.dealBreaker)).length;
    parts.push(
      withBreaker === questions.length
        ? `${countPl(questions.length, "pytanie", "pytania", "pytań")} z „odpada, gdy”`
        : countPl(questions.length, "pytanie", "pytania", "pytań"),
    );
  }
  if (!blank(f.keyTask)) {
    parts.push(
      f.questions.some((q) => q.keyTask) ? "najważniejsze zadanie + pytanie" : "najważniejsze zadanie",
    );
  }
  if (!blank(f.rateBudget) || !blank(f.rateBudgetMin)) {
    parts.push(
      `budżet ${[f.rateBudgetMin, f.rateBudget].filter((v) => !blank(v)).join("–")}`,
    );
  }
  if (f.remotePolicy) {
    parts.push(
      `${WORK_MODE[f.remotePolicy] ?? f.remotePolicy}${
        f.remotePolicy !== "remote" && !blank(f.onsiteDays) ? ` ${f.onsiteDays} dni` : ""
      }`,
    );
  }
  const cities = splitCities(f.city);
  if (cities.length > 0) parts.push(cities.join(", "));
  if (f.deadlineNotProvided) parts.push("termin: klient nie podał");
  if (!blank(f.headcount)) parts.push(countPl(Number(f.headcount) || 0, "osoba", "osoby", "osób"));
  if (f.competenceCategoryId != null) parts.push("kategoria");
  parts.push("kanały ogłoszenia");
  return parts;
}
