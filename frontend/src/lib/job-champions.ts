/**
 * Championi rekrutacji (decyzje Artura D1–D9, 15.10.2026) — czyste reguły
 * prezentacji. Serwer trzyma listę osób i liczy flagę „nie szukamy”
 * (|championi ∪ zatrudnieni| ≥ miejsca); tu tylko nazywamy stan, grupujemy
 * listę do zaznaczenia i zapowiadamy skutki zapisu albo odrzucenia.
 *
 * Kontrakt API: `GET/PUT /api/jobs/{id}/champions`, w detalu i na liście
 * rekrutacji `champions`, `champion_seats`, `hired_count`, `priority_paused`.
 */

import {
  BOARD_COLUMN_LABEL,
  CPRO_SENT_COLUMN_LABEL,
  type BoardColumnKey,
} from "@/lib/board-stages";
import { shortenPersonName } from "@/lib/job-header-subtitle";
import {
  REQUEST_STATUS_META,
  requestStatusOf,
  type RequestStatusTone,
} from "@/lib/request-status";

/** Champion w detalu i w wierszu listy rekrutacji (kolejność oznaczenia). */
export interface JobChampionBrief {
  candidate_id: number;
  name: string;
  /** Champion stoi w „Zatrudniony” (tylko detal) — liczy się raz z zatrudnionymi. */
  hired?: boolean;
}

/** Pola rekrutacji, z których plakietka statusu liczy swój napis. */
export interface JobChampionsFields {
  request_status?: unknown;
  champions?: readonly JobChampionBrief[] | null;
  champion_seats?: number | null;
  hired_count?: number | null;
  priority_paused?: boolean | null;
}

export type ChampionStatusKind = "legacy" | "named" | "partial" | "plain";

export interface ChampionStatusView {
  kind: ChampionStatusKind;
  /** Cały napis plakietki („Champion: Karol W.”, „Szukamy · 1 z 2”). */
  label: string;
  /** Przy `partial` napis przed pucharem („Szukamy”), za nim `seatsText`. */
  lead: string;
  seatsText: string | null;
  /** Dymek: pełne imiona i nazwiska albo podpowiedź statusu. */
  title: string;
  tone: RequestStatusTone | "champion";
}

/** Liczba miejsc jak na serwerze: `max(headcount, 1)`. */
export function championSeats(fields: Pick<JobChampionsFields, "champion_seats">): number {
  const seats = fields.champion_seats;
  return typeof seats === "number" && Number.isFinite(seats) ? Math.max(Math.floor(seats), 1) : 1;
}

function championsOf(fields: JobChampionsFields): readonly JobChampionBrief[] {
  return Array.isArray(fields.champions) ? fields.champions : [];
}

function shortName(name: string): string {
  return shortenPersonName(name) ?? name;
}

function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] || name;
}

/** „Champion: Karol Wzorcowy” / „Championi: Karol Wzorcowy, Bartek Testowy”. */
export function championsTitle(champions: readonly { name: string }[]): string {
  if (champions.length === 0) return "";
  const names = champions.map((c) => c.name).join(", ");
  return champions.length === 1 ? `Champion: ${names}` : `Championi: ${names}`;
}

/**
 * Napis plakietki statusu w nagłówku rekrutacji:
 *  - „Mamy championa” — flaga sprzed 15.10.2026 bez wskazanej osoby (D1),
 *  - „Champion: Karol W.” / „Championi: Karol W. +1” — nie szukamy,
 *  - „Szukamy · 1 z 2” — championów mniej niż miejsc, szukamy dalej (D5),
 *  - inaczej etykieta statusu requestu jak na liście.
 * Nieznany status (starszy cache) = `null`.
 */
export function championStatusView(fields: JobChampionsFields): ChampionStatusView | null {
  const status = requestStatusOf(fields.request_status);
  if (!status) return null;
  const champions = championsOf(fields);
  const meta = REQUEST_STATUS_META[status];
  const plain = (kind: ChampionStatusKind, tone: ChampionStatusView["tone"]): ChampionStatusView => ({
    kind,
    label: meta.label,
    lead: meta.label,
    seatsText: null,
    title: champions.length > 0 ? `${meta.hint} ${championsTitle(champions)}.` : meta.hint,
    tone,
  });
  if (status === "champion") {
    if (champions.length === 0) return plain("legacy", "champion");
    const first = shortName(champions[0].name);
    const label =
      champions.length === 1
        ? `Champion: ${first}`
        : `Championi: ${first} +${champions.length - 1}`;
    return {
      kind: "named",
      label,
      lead: label,
      seatsText: null,
      title: `${championsTitle(champions)}. Dalej nie szukamy.`,
      tone: "champion",
    };
  }
  if (status === "searching" && champions.length > 0) {
    const seats = championSeats(fields);
    const seatsText = `${champions.length} z ${seats}`;
    return {
      kind: "partial",
      label: `${meta.label} · ${seatsText}`,
      lead: meta.label,
      seatsText,
      title: `Szukamy dalej: ${seatsText} miejsc ma championa. ${championsTitle(champions)}.`,
      tone: meta.tone,
    };
  }
  return plain("plain", meta.tone);
}

// ── Okienko „Championi tej rekrutacji” ──────────────────────────────────────

/** Osoba do zaznaczenia (`eligible` z `GET …/champions`). */
export interface ChampionCandidate {
  candidate_id: number;
  name: string;
  column: string | null;
  stage_label: string | null;
  is_champion?: boolean;
}

export interface ChampionGroup<T extends ChampionCandidate = ChampionCandidate> {
  column: string | null;
  label: string;
  items: T[];
}

/** Od najdalszej kolumny — jak sortuje serwer. */
export const CHAMPION_COLUMN_ORDER: readonly BoardColumnKey[] = [
  "hired",
  "contract",
  "client_interview",
  "cv_sent",
];

/** Lista z wyszukiwarką dopiero od tylu osób (przy ośmiu widać wszystkich). */
export const CHAMPION_SEARCH_MIN = 9;

function columnLabel(column: string | null, cproEnabled: boolean): string {
  if (column === "cv_sent" && cproEnabled) return CPRO_SENT_COLUMN_LABEL;
  if (column && column in BOARD_COLUMN_LABEL) return BOARD_COLUMN_LABEL[column as BoardColumnKey];
  return "Inny etap";
}

/**
 * Grupy po kolumnie Tablicy w kolejności `CHAMPION_COLUMN_ORDER`, w grupie
 * kolejność serwera (alfabetycznie). Kolumna spoza listy — na końcu.
 */
export function groupChampionCandidates<T extends ChampionCandidate>(
  people: readonly T[],
  opts: { cproEnabled?: boolean } = {},
): ChampionGroup<T>[] {
  const rank = (column: string | null) => {
    const index = CHAMPION_COLUMN_ORDER.indexOf(column as BoardColumnKey);
    return index === -1 ? CHAMPION_COLUMN_ORDER.length : index;
  };
  const groups = new Map<string, ChampionGroup<T>>();
  for (const person of people) {
    const key = person.column ?? "";
    let group = groups.get(key);
    if (!group) {
      group = { column: person.column, label: columnLabel(person.column, Boolean(opts.cproEnabled)), items: [] };
      groups.set(key, group);
    }
    group.items.push(person);
  }
  return [...groups.values()].sort((a, b) => rank(a.column) - rank(b.column));
}

function foldText(text: string): string {
  // „ł” nie rozkłada się w NFD — bez tego „lukasz” nie znalazłby „Łukasza”.
  return text
    .toLocaleLowerCase("pl-PL")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/ł/g, "l");
}

/** Szukanie po imieniu i nazwisku — bez wielkości liter i polskich znaków. */
export function filterChampionCandidates<T extends ChampionCandidate>(
  people: readonly T[],
  query: string,
): T[] {
  const needle = foldText(query.trim());
  if (!needle) return [...people];
  return people.filter((person) => foldText(person.name).includes(needle));
}

export interface ChampionEffectsInput {
  /** Zaznaczone osoby (z kolumną — zatrudnieni liczą się raz). */
  selected: readonly { column: string | null }[];
  seats: number;
  hiredCount: number;
  /** Przed zapisem byli championi albo stara flaga bez osób. */
  hadChampions: boolean;
  /** Surowy `jobs.work_state`. */
  workState: string | null | undefined;
}

export const CHAMPION_EFFECT_STOP =
  "Po zapisie rekrutacja nie szuka: P1 wstrzymany, automat zwalnia przydział, zespół dostaje dzwonek.";
export const CHAMPION_EFFECT_RESUME = "Po zapisie rekrutacja wróci do „Szukamy”.";
/** D9: zapis przestawia stan pracy na „Szukamy” — champion jest widoczny tylko tam. */
export function championWorkStateLine(workState: "to_review" | "client_silent"): string {
  const label = workState === "to_review" ? "Do przejrzenia" : "Klient milczy";
  return `Stan „${label}” zmieni się na „Szukamy”, żeby champion był widoczny.`;
}

/**
 * Co zrobi zapis — zdania pod listą, liczone z zaznaczenia. Serwer gasi
 * szukanie, gdy championi i zatrudnieni pokrywają miejsca (D5), a przy stanie
 * „Do przejrzenia” / „Klient milczy” przestawia request na „Szukamy” (D9).
 */
export function championEffectLines(input: ChampionEffectsInput): string[] {
  const lines: string[] = [];
  const count = input.selected.length;
  if (count > 0) {
    const covered = input.hiredCount + input.selected.filter((s) => s.column !== "hired").length;
    lines.push(
      covered >= input.seats
        ? CHAMPION_EFFECT_STOP
        : `Szukamy dalej: ${count} z ${input.seats} miejsc ma championa.`,
    );
    if (input.workState === "to_review" || input.workState === "client_silent") {
      lines.push(championWorkStateLine(input.workState));
    }
  } else if (input.hadChampions) {
    lines.push(CHAMPION_EFFECT_RESUME);
  }
  return lines;
}

/**
 * Zdanie w oknie odrzucenia championa (D7). Liczy z detalu rekrutacji
 * w cache'u; bez listy championów — `null` (okno nie zgaduje).
 */
export function championRemovalOutcome(
  job: JobChampionsFields | null | undefined,
  candidateId: number,
  personName: string,
): string | null {
  if (!job || !Array.isArray(job.champions)) return null;
  const champions = job.champions;
  // Okno mówi o championie tylko wtedy, gdy ta osoba nim jest.
  if (!champions.some((c) => c.candidate_id === candidateId)) return null;
  const seats = championSeats(job);
  const hired = typeof job.hired_count === "number" ? job.hired_count : 0;
  // Serwer liczy sumę zbiorów (championi ∪ zatrudnieni) — zatrudniony
  // champion jest już w `hired_count`.
  const covered = (people: readonly JobChampionBrief[]) =>
    hired + people.filter((c) => c.hired !== true).length;
  const remaining = champions.filter((c) => c.candidate_id !== candidateId);
  const stoppedBefore = covered(champions) >= seats;
  const name = firstName(personName);
  if (remaining.length > 0) {
    if (covered(remaining) >= seats) {
      const names = remaining.map((c) => shortName(c.name)).join(", ");
      return `${name} jest championem. Zostaje ${names}, więc rekrutacja dalej nie szuka.`;
    }
    const left = `${name} jest championem. Po odrzuceniu zostanie ${remaining.length} z ${seats} championów`;
    return stoppedBefore ? `${left} — rekrutacja wróci do „Szukamy”.` : `${left}.`;
  }
  // Zatrudnieni pokrywają miejsca — status „Obsadzona”, szukanie nie wraca.
  if (hired >= seats) return `${name} jest championem.`;
  if (!stoppedBefore) return `${name} jest ostatnim championem tej rekrutacji.`;
  const p1 = job.priority_paused === true ? ", a P1 zacznie działać" : "";
  return `${name} jest ostatnim championem. Po odrzuceniu rekrutacja wróci do „Szukamy”${p1}.`;
}
