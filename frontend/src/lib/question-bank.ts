// „Pytania z rozmów” — baza pytań klientów jak dawny Excel, bez ręcznego wpisywania
// (prośba Delivery Leadki z 24.11.2026). Wiersz = jedno pytanie u jednego
// klienta (bank `interview_questions` jest unikalny po kliencie i treści), ze
// stanowiskami i managerami z rekrutacji, w których padło. Lustro trasy
// `GET /api/interview-cycle/question-bank`.

export type QuestionSource = "debrief" | "archive";

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
}

export interface QuestionBankFilters {
  clientId: number | null;
  role: string;
  manager: string | null;
  text: string;
  source: QuestionSource | "all";
}

export const EMPTY_FILTERS: QuestionBankFilters = {
  clientId: null,
  role: "",
  manager: null,
  text: "",
  source: "all",
};

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

export function filterQuestions(
  items: readonly BankQuestion[],
  f: QuestionBankFilters,
): BankQuestion[] {
  const role = norm(f.role);
  const text = norm(f.text);
  return items.filter((q) => {
    if (f.clientId != null && q.client_id !== f.clientId) return false;
    if (f.source !== "all" && q.source !== f.source) return false;
    if (f.manager != null && !q.managers.includes(f.manager)) return false;
    if (role && !q.roles.some((r) => norm(roleLabel(r)).includes(role))) return false;
    if (text && !norm(q.text).includes(text)) return false;
    return true;
  });
}

/** Klienci do filtra — najwięcej pytań najpierw. */
export function clientOptions(items: readonly BankQuestion[]): { id: number; name: string; count: number }[] {
  const map = new Map<number, { id: number; name: string; count: number }>();
  for (const q of items) {
    const entry = map.get(q.client_id);
    if (entry) entry.count += 1;
    else map.set(q.client_id, { id: q.client_id, name: q.client_name ?? `Klient #${q.client_id}`, count: 1 });
  }
  return [...map.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "pl"));
}

/** Managerowie z wierszy po filtrze klienta — lista nie podsuwa cudzych. */
export function managerOptions(items: readonly BankQuestion[], clientId: number | null): string[] {
  const names = new Set<string>();
  for (const q of items) {
    if (clientId != null && q.client_id !== clientId) continue;
    for (const m of q.managers) names.add(m);
  }
  return [...names].sort((a, b) => a.localeCompare(b, "pl"));
}

/** Tekst do schowka pod prep: pytania pogrupowane po stanowisku, bez powtórzeń. */
export function questionsAsText(items: readonly BankQuestion[]): string {
  const groups = new Map<string, string[]>();
  for (const q of items) {
    const key = q.roles[0] ? roleLabel(q.roles[0]) : "Bez stanowiska";
    const list = groups.get(key) ?? [];
    if (!list.includes(q.text)) list.push(q.text);
    groups.set(key, list);
  }
  return [...groups.entries()].map(([role, qs]) => `${role}\n${qs.map((q) => `- ${q}`).join("\n")}`).join("\n\n");
}
