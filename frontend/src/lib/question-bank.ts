// „Pytania z rozmów” — baza pytań klientów jak dawny Excel, bez ręcznego wpisywania
// (prośba Delivery Leadki z 24.11.2026). Wiersz API = jedno pytanie u jednego
// klienta (bank `interview_questions` jest unikalny po kliencie i treści), ze
// stanowiskami i managerami z rekrutacji, w których padło. Lustro trasy
// `GET /api/interview-cycle/question-bank`.
//
// Od 25.11.2026 (decyzja Artura, wariant A z makiet) ekran pokazuje najpierw
// stanowiska, a pytania z propozycją odpowiedzi dopiero po wejściu
// w stanowisko — stąd grupowanie po rekrutacji niżej.

export type QuestionSource = "debrief" | "archive";
/**
 * `excel` — odpowiedź rekruterów z dawnego Excela; `ai` — nocny bieg F55, do
 * sprawdzenia; `manual` — wpisana w NEXUSIE; `none` — nocny bieg uznał wpis
 * za nagłówek, nie pytanie. `null` — nocny bieg jeszcze go nie widział.
 */
export type AnswerSource = "excel" | "ai" | "manual" | "none";

export interface QuestionRole {
  job_id: number;
  title: string | null;
  job_number: string | null;
  manager: string | null;
}

export interface BankQuestion {
  id: number;
  text: string;
  client_id: number;
  client_name: string | null;
  /** `debrief` — z telefonu po rozmowie; `archive` — import Excela (0383). */
  source: QuestionSource;
  roles: QuestionRole[];
  managers: string[];
  /** W ilu debriefach padło to pytanie (archiwum: 0, dopóki nie padnie znowu). */
  asked_count: number;
  last_asked_at: string | null;
  answer: string | null;
  answer_source: AnswerSource | null;
}

/** Stanowisko na liście: rekrutacja albo archiwum Excela klienta (pytania bez rekrutacji). */
export interface Position {
  /** Wartość `?stanowisko=` w adresie: id rekrutacji albo `excel-<id klienta>`. */
  key: string;
  jobId: number | null;
  jobNumber: string | null;
  /** Nazwa stanowiska bez dopisku z technologiami. */
  name: string;
  /** Dopisek z technologiami i stażem („Java, Spring · 5+ lat”). */
  techLine: string | null;
  clientId: number;
  clientName: string;
  managers: string[];
  questions: BankQuestion[];
  lastAskedAt: string | null;
}

export interface PositionFilters {
  clientId: number | null;
  search: string;
  manager: string | null;
  text: string;
}

export const EMPTY_FILTERS: PositionFilters = { clientId: null, search: "", manager: null, text: "" };

function norm(value: string): string {
  return value
    .toLocaleLowerCase("pl")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function roleLabel(role: QuestionRole): string {
  return [role.job_number, role.title].filter(Boolean).join(" · ") || `Rekrutacja #${role.job_id}`;
}

function splitTitle(title: string | null): { name: string; techLine: string | null } {
  if (!title) return { name: "Stanowisko bez nazwy", techLine: null };
  const [name, ...rest] = title.split(" · ");
  return { name: name.trim(), techLine: rest.length ? rest.join(" · ") : null };
}

/**
 * Debrief z telefonu zapisuje czasem nagłówek działu jako osobne „pytanie”
 * („Java”, „Kolejki i komunikacja asynchroniczna”). Rozpoznaje go nocny bieg
 * F55 (`answer_source: "none"`), nie tekst: krótkie „Playwright” czy „Czy zna
 * RLS” to prawdziwe pytania (pomiar na kopii z 25.11: 28 z 32 krótkich wpisów).
 * Ekran pokazuje nagłówek jako śródtytuł i nie liczy go do pytań.
 */
export function isSectionHeading(q: Pick<BankQuestion, "answer_source">): boolean {
  return q.answer_source === "none";
}

export function questionCount(p: Position): number {
  return p.questions.filter((q) => !isSectionHeading(q)).length;
}

/**
 * Pytania pogrupowane po rekrutacji (pytanie z kilku rekrutacji jest w każdej),
 * pytania z Excela bez rekrutacji — jedna grupa na klienta. Kolejność: rekrutacje
 * od ostatnio zadanego pytania, archiwa Excela na końcu.
 */
export function groupByPosition(items: readonly BankQuestion[]): Position[] {
  const map = new Map<string, Position>();
  const add = (base: Omit<Position, "questions" | "lastAskedAt" | "managers">, q: BankQuestion) => {
    let p = map.get(base.key);
    if (!p) {
      p = { ...base, managers: [], questions: [], lastAskedAt: null };
      map.set(base.key, p);
    }
    p.questions.push(q);
    for (const m of q.managers) if (!p.managers.includes(m)) p.managers.push(m);
    if (q.last_asked_at && (!p.lastAskedAt || q.last_asked_at > p.lastAskedAt)) p.lastAskedAt = q.last_asked_at;
  };
  for (const q of items) {
    const clientName = q.client_name ?? `Klient #${q.client_id}`;
    if (q.roles.length === 0) {
      const key = `excel-${q.client_id}`;
      add({ key, jobId: null, jobNumber: null, name: "Archiwum z Excela", techLine: null, clientId: q.client_id, clientName }, q);
      continue;
    }
    for (const r of q.roles) {
      const { name, techLine } = splitTitle(r.title);
      add({ key: String(r.job_id), jobId: r.job_id, jobNumber: r.job_number, name, techLine, clientId: q.client_id, clientName }, q);
    }
  }
  return [...map.values()].sort((a, b) => {
    if ((a.jobId == null) !== (b.jobId == null)) return a.jobId == null ? 1 : -1;
    return (
      (b.lastAskedAt ?? "").localeCompare(a.lastAskedAt ?? "") ||
      b.questions.length - a.questions.length ||
      a.clientName.localeCompare(b.clientName, "pl")
    );
  });
}

export function filterPositions(positions: readonly Position[], f: PositionFilters): Position[] {
  const search = norm(f.search);
  const text = norm(f.text);
  return positions.filter((p) => {
    if (f.clientId != null && p.clientId !== f.clientId) return false;
    if (f.manager != null && !p.managers.includes(f.manager)) return false;
    if (search && !norm(`${p.jobNumber ?? ""} ${p.name} ${p.techLine ?? ""}`).includes(search)) return false;
    if (text && !p.questions.some((q) => norm(q.text).includes(text))) return false;
    return true;
  });
}

/** Klienci do filtra — najwięcej stanowisk najpierw. */
export function clientOptions(positions: readonly Position[]): { id: number; name: string; count: number }[] {
  const map = new Map<number, { id: number; name: string; count: number }>();
  for (const p of positions) {
    const entry = map.get(p.clientId) ?? { id: p.clientId, name: p.clientName, count: 0 };
    entry.count += 1;
    map.set(p.clientId, entry);
  }
  return [...map.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "pl"));
}

/** Managerowie stanowisk wybranego klienta — lista nie podsuwa cudzych. */
export function managerOptions(positions: readonly Position[], clientId: number | null): string[] {
  const names = new Set<string>();
  for (const p of positions) {
    if (clientId != null && p.clientId !== clientId) continue;
    for (const m of p.managers) names.add(m);
  }
  return [...names].sort((a, b) => a.localeCompare(b, "pl"));
}

/** Tekst do schowka pod prep: śródtytuły, pytania i (na życzenie) odpowiedzi. */
export function positionAsText(p: Position, withAnswers: boolean): string {
  const head = [p.jobNumber, p.name, p.clientName].filter(Boolean).join(" · ");
  const lines: string[] = [head];
  let n = 0;
  for (const q of p.questions) {
    if (isSectionHeading(q)) {
      lines.push("", q.text.toLocaleUpperCase("pl"));
      continue;
    }
    n += 1;
    lines.push(`${n}. ${q.text}`);
    if (withAnswers && q.answer) lines.push(`   Odpowiedź: ${q.answer}`);
  }
  return lines.join("\n");
}
