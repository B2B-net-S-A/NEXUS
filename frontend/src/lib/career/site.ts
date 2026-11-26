/**
 * Strona kariery w układzie nowej strony B2B Network (makiety Artura
 * KarieraA, OfertaA, OfertaManager i ekrany stanów, 23.11.2026, kanwa
 * https://claude.ai/artifact/1RCpsMgFGdPxE5CyBqoRcj) — czysta logika widoków.
 *
 * Wszystko liczy się z publicznych odpowiedzi API (biała lista, bez klienta
 * i stawek). Wielkie słowo nad tytułem i pogrubienie w liście „Co już masz?”
 * biorą się z krótkich nazw umiejętności karty tablicy (`must`/`nice`), nigdy
 * z tekstu dopisanego ręcznie.
 */
import type { CareerBoardCategory, CareerBoardJob } from "./api";
import { filterBoard, type BoardFilters } from "./board";

/** Najdłuższe słowo, które zmieści się nad tytułem bez łamania (Montserrat 800). */
export const BIG_WORD_MAX = 14;

/** Bez polskich znaków i wielkich liter — „python” znajdzie „Pythonie”. */
export function fold(text: string): string {
  return text
    .toLocaleLowerCase("pl-PL")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ł/g, "l");
}

/** Karta tablicy tej rekrutacji: link z tablicy (canonical) albo ten sam slug. */
export function boardCardFor(
  jobs: readonly CareerBoardJob[],
  slugs: readonly (string | null | undefined)[],
): CareerBoardJob | null {
  const wanted = slugs.filter(Boolean).map((s) => (s as string).toLowerCase());
  return jobs.find((j) => wanted.includes(j.slug.toLowerCase())) ?? null;
}

/**
 * Wielkie słowo nad tytułem oferty: pierwsza krótka umiejętność z tablicy
 * („Python”, „AI”). Bez niej brak słowa (tytuł zostaje sam), zamiast wymyślać
 * hasło za rekrutera. Kategorii nie pokazujemy (decyzja Artura 23.11.2026).
 */
export function bigWord(card: Pick<CareerBoardJob, "must"> | null): string | null {
  const skill = (card?.must ?? [])
    .map((s) => s.trim())
    .find((s) => s.length >= 2 && s.length <= BIG_WORD_MAX && s.split(/\s+/).length <= 2);
  return skill ?? null;
}

export interface Highlighted {
  before: string;
  key: string | null;
  after: string;
}

/**
 * Zdanie wymagania z pogrubioną umiejętnością („Doświadczenie w pracy
 * z **REST API**”). Wybiera najdłuższą nazwę z listy, która stoi w zdaniu;
 * porównanie bez polskich znaków. Bez trafienia zdanie zostaje zwykłe.
 */
export function highlightSkill(sentence: string, skills: readonly string[]): Highlighted {
  const folded = fold(sentence);
  let best: { at: number; len: number } | null = null;
  for (const raw of skills) {
    const skill = raw.trim();
    if (skill.length < 2) continue;
    const at = folded.indexOf(fold(skill));
    if (at < 0) continue;
    // Tylko całe słowa: „AI” nie świeci w „szczegółAIch”.
    const prev = folded[at - 1];
    const next = folded[at + skill.length];
    if ((prev && /[a-z0-9]/.test(prev)) || (next && /[a-z0-9]/.test(next))) continue;
    if (!best || skill.length > best.len) best = { at, len: skill.length };
  }
  if (!best) return { before: sentence, key: null, after: "" };
  return {
    before: sentence.slice(0, best.at),
    key: sentence.slice(best.at, best.at + best.len),
    after: sentence.slice(best.at + best.len),
  };
}

/**
 * Podobne otwarte rekrutacje (zamknięta oferta, ekran po wysłaniu): najpierw ta
 * sama kategoria, potem reszta tablicy, bez tej rekrutacji.
 */
export function similarJobs(
  jobs: readonly CareerBoardJob[],
  exclude: readonly (string | null | undefined)[],
  category: CareerBoardCategory | null | undefined,
  limit = 3,
): CareerBoardJob[] {
  const skip = new Set(exclude.filter(Boolean).map((s) => (s as string).toLowerCase()));
  const pool = jobs.filter((j) => !skip.has(j.slug.toLowerCase()));
  const same = category ? pool.filter((j) => j.category === category) : [];
  const rest = pool.filter((j) => !same.includes(j));
  return [...same, ...rest].slice(0, limit);
}

/** „Pokaż kolejne”: pełna paczka albo tyle, ile zostało. */
export function nextBatch(rest: number, step: number): number {
  return Math.max(0, Math.min(step, rest));
}

export type PluralForm = "one" | "few" | "many";

/** Polska odmiana liczebnika: 1 pole, 2–4 pola, 5 pól (12–14 też „many”). */
export function pluralForm(n: number): PluralForm {
  if (n === 1) return "one";
  const ten = n % 10;
  const hundred = n % 100;
  return ten >= 2 && ten <= 4 && (hundred < 12 || hundred > 14) ? "few" : "many";
}

/** „5 wymaganych, 3 mile widziane” pod licznikiem listy „Co już masz?”. */
export function checklistSummary(required: number, nice: number): string {
  const req = `${required} ${pluralForm(required) === "many" ? "wymaganych" : "wymagane"}`;
  return nice > 0 ? `${req}, ${nice} mile widziane` : req;
}

/** „rozmowa z Martą” → „Rozmowa z Martą” (kroki procesu z `processSteps`). */
export function capitalize(text: string): string {
  return text ? text.charAt(0).toLocaleUpperCase("pl-PL") + text.slice(1) : text;
}

/**
 * Hasło bez trafień („COBOL Kraków”): pierwsze słowo, które samo coś znajduje
 * przy tych samych filtrach („Kraków” → rekrutacje w Krakowie). Bez trafień
 * żadnego słowa — `null`, zamiast podsuwać przypadkową ofertę.
 */
export function partialMatch(
  jobs: readonly CareerBoardJob[],
  filters: BoardFilters,
): { word: string; jobs: CareerBoardJob[] } | null {
  const words = filters.query.split(/[\s,;]+/).filter(Boolean);
  if (words.length < 2) return null;
  for (const word of words) {
    const hits = filterBoard(jobs, { ...filters, query: word });
    if (hits.length > 0) return { word, jobs: hits };
  }
  return null;
}

/** „jest teraz 1 rekrutacja”, „są teraz 3 rekrutacje”, „jest teraz 5 rekrutacji”. */
export function openNowLabel(n: number): string {
  const form = pluralForm(n);
  if (form === "one") return "jest teraz 1 rekrutacja";
  if (form === "few") return `są teraz ${n} rekrutacje`;
  return `jest teraz ${n} rekrutacji`;
}

/**
 * Szerokość słowa w em dla Montserrat 800 ze ściśniętą literą (-0,055em):
 * wersaliki i cyfry są szersze niż małe litery. Z tej liczby CSS liczy rozmiar
 * wielkiego słowa tak, żeby zmieściło się w szerokości treści — także „BPMN”
 * na telefonie (wcześniej wychodziło poza ekran).
 */
export function wordEm(word: string): number {
  let em = 0;
  for (const ch of word) {
    if (ch === " ") em += 0.28;
    else if (/[A-ZĄĆĘŁŃÓŚŹŻ0-9]/.test(ch)) em += ch === "I" ? 0.36 : /[MW]/.test(ch) ? 0.98 : 0.8;
    else if (/[iljtfr.,]/.test(ch)) em += 0.36;
    else if (/[mw]/.test(ch)) em += 0.92;
    else em += 0.6;
  }
  return Math.max(em, 2.4) * 1.04;
}

/** Miasto z liczbą otwartych rekrutacji (filtr zamiast kategorii, decyzja 23.11.2026). */
export interface Facet {
  id: string;
  label: string;
  count: number;
}

/**
 * Miasta, które rozpoznajemy w polu miejsca. Pole bywa opisem („Priorytet
 * Gdańsk”, „Tylko Warszawa”, „Gdańsk (preferowana)”), więc szukamy nazw,
 * a nie dzielimy tekstu po przecinkach. „Trójmiasto” liczy się do trzech miast.
 */
const CITIES = [
  "Warszawa", "Gdańsk", "Gdynia", "Sopot", "Łódź", "Kraków", "Katowice", "Wrocław", "Poznań",
  "Bydgoszcz", "Lublin", "Szczecin", "Białystok", "Rzeszów", "Toruń", "Olsztyn", "Kielce",
  "Opole", "Gliwice", "Częstochowa",
];
const TRICITY = ["Gdańsk", "Gdynia", "Sopot"];

export function jobCities(job: Pick<CareerBoardJob, "city">): string[] {
  const text = fold(job.city ?? "");
  if (!text) return [];
  const found = CITIES.filter((c) => new RegExp(`(^|[^a-z])${fold(c)}([^a-z]|$)`).test(text));
  if (/(^|[^a-z])trojmiasto/.test(text)) for (const c of TRICITY) if (!found.includes(c)) found.push(c);
  return found;
}

export function jobFacetIds(job: Pick<CareerBoardJob, "city">): string[] {
  return jobCities(job).map(fold);
}

/** Miasta z liczbami, od najczęstszego; liczone na podanej (już przeszukanej) liście. */
export function facetCounts(jobs: readonly Pick<CareerBoardJob, "city">[]): Facet[] {
  const counts = new Map<string, Facet>();
  for (const job of jobs) {
    for (const label of jobCities(job)) {
      const id = fold(label);
      const f = counts.get(id) ?? { id, label, count: 0 };
      f.count += 1;
      counts.set(id, f);
    }
  }
  return [...counts.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "pl"));
}

/** Najwięcej technologii nad tytułem i najdłuższa nazwa, która się tam mieści. */
const TAGS = 3;
const TAG_MAX = 24;

/** Technologie nad tytułem: najpierw słowo oferty (białe), potem krótkie umiejętności z tablicy. */
export function offerTags(word: string | null, must: readonly string[]): string[] {
  const out = word ? [word] : [];
  for (const t of must) {
    const name = t.trim();
    if (out.length >= TAGS) break;
    if (name && name.length <= TAG_MAX && !out.includes(name)) out.push(name);
  }
  return out;
}
