/**
 * Adres strony rekrutacji (wersja 3: „rekrutacja = jedna tabela").
 *
 * Dwanaście dawnych zakładek zwinęło się do TRZECH widoków (`people`, `board`,
 * `champion`), a reszta stała się segmentem tabeli, sekcją panelu osoby albo
 * oknem wysuwanym. Stare identyfikatory `?tab=` żyją jednak dalej: są
 * zapisane w bazie powiadomień, w mailach i w zakładkach przeglądarek. Ten
 * plik jest JEDYNYM miejscem, które wie, dokąd każdy z nich prowadzi —
 * czyste funkcje, bez Reacta, żeby dało się je przetestować na wartościach.
 *
 * Kształt adresu:
 *   ?tab=people|board|champion   widok (domyślny `board` nie stoi w adresie)
 *   &seg=<RecruitmentSegment>    segment paska etapów
 *   &candidate=<id>              otwiera panel osoby (jednorazowy — strona go zdejmuje)
 *   &panel=<PersonPanelSection>  sekcja panelu osoby
 *   &win=<RecruitmentSlideOver>  okno wysuwane
 *   &wintab=<…>                  zakładka/sekcja startowa okna
 */

import type {
  PersonPanelSection,
  RecruitmentSegment,
  RecruitmentSlideOver,
} from "@/components/v2/recruitment/types";

export type JobDetailView = "people" | "board" | "champion";

// Tablica jest widokiem domyślnym (decyzja Artura 22.09.2026); „Tabela"
// zostaje przełącznikiem. Adres z segmentem albo sekcją panelu osoby bez
// jawnego `tab=` nadal otwiera „Tabelę" — tylko ona ma segmenty i panel.
export const JOB_DETAIL_DEFAULT_VIEW: JobDetailView = "board";

/** Zakładka startowa okna „Historia i czat" (lustro `HistoryChatTab`). */
export type JobHistoryChatTab = "all" | "chat" | "moves" | "request" | "background";
/** Sekcja startowa okna „Zlecenie" (lustro `OrderSlideOverSection`). */
export type JobOrderSection = "team" | "close";

export interface LegacyJobTabTarget {
  view: JobDetailView;
  segment?: RecruitmentSegment;
  panelSection?: PersonPanelSection;
  slideOver?: RecruitmentSlideOver;
  slideOverTab?: JobHistoryChatTab;
  orderSection?: JobOrderSection;
}

const LEGACY_TAB_TARGETS: Readonly<Record<string, LegacyJobTabTarget>> = {
  pipeline: { view: "people" },
  screening: { view: "people", segment: "group:screening", panelSection: "screening" },
  cv: { view: "people", segment: "group:verification", panelSection: "cv" },
  interviews: { view: "people", segment: "group:client", panelSection: "interviews" },
  contract: { view: "people", segment: "group:contract", panelSection: "contract" },
  notes: { view: "people", panelSection: "notes" },
  "ai-matching": { view: "people", segment: "proposals" },
  // Zostaje przy „Do przejrzenia”: `?tab=similar` niosą powiadomienia
  // o propozycjach AI (auto_match_service, candidate_search_worker,
  // similar_job_notify). Panel przepięć otwiera `?win=similar`.
  similar: { view: "people", segment: "proposals" },
  "manual-search": { view: "people", slideOver: "manual-search" },
  // Symulowane portale ogłoszeniowe usunięte 23.09.2026 — stary link otwiera
  // samo okno zlecenia (sekcja „Ogłoszenie i link aplikacyjny" jest w nim).
  portals: { view: "people", slideOver: "order" },
  questions: { view: "people", slideOver: "questions" },
  history: { view: "people", slideOver: "history-chat", slideOverTab: "request" },
  chat: { view: "people", slideOver: "history-chat", slideOverTab: "chat" },
  champion: { view: "champion" },
  "champion-profile": { view: "champion" },
};

/**
 * Dokąd prowadzi dawny identyfikator zakładki. `null` = to nie jest stary
 * identyfikator (nowy widok, literówka, brak parametru).
 *
 * `champion` jest jednocześnie starą zakładką i nowym widokiem — zwracamy cel,
 * żeby strażnik „każdy stary adres jest rozpoznawany" obejmował też jego.
 */
export function resolveLegacyJobTab(
  tab: string | null | undefined,
): LegacyJobTabTarget | null {
  if (tab == null) return null;
  const key = tab.trim();
  if (!Object.prototype.hasOwnProperty.call(LEGACY_TAB_TARGETS, key)) return null;
  return LEGACY_TAB_TARGETS[key];
}

// ── Parsowanie nowych parametrów ─────────────────────────────────────────────

const VIEWS: readonly JobDetailView[] = ["people", "board", "champion"];
const STATIC_SEGMENTS: readonly string[] = [
  "proposals",
  "shortlist",
  "in-process",
  "off-template",
  "closed",
];
const GROUP_SEGMENT = /^group:(posting|intake|screening|verification|client|contract|closed)$/;
const STAGE_SEGMENT = /^stage:[1-9]\d{0,9}$/;
const PANEL_SECTIONS: readonly PersonPanelSection[] = [
  "cv",
  "screening",
  "interviews",
  "contract",
  "match",
  "notes",
];
const SLIDE_OVERS: readonly RecruitmentSlideOver[] = [
  "order",
  "questions",
  "history-chat",
  "manual-search",
  "similar",
];
const HISTORY_TABS: readonly JobHistoryChatTab[] = [
  "all",
  "chat",
  "moves",
  "request",
  "background",
];
const ORDER_SECTIONS: readonly JobOrderSection[] = ["team", "close"];

function oneOf<T extends string>(raw: string | null | undefined, allowed: readonly T[]): T | null {
  if (raw == null) return null;
  const value = raw.trim();
  return (allowed as readonly string[]).includes(value) ? (value as T) : null;
}

export function parseJobDetailView(raw: string | null | undefined): JobDetailView | null {
  return oneOf(raw, VIEWS);
}

/** Adres pisze użytkownik — przyjmujemy wyłącznie kształty, które tabela zna. */
export function parseRecruitmentSegment(
  raw: string | null | undefined,
): RecruitmentSegment | null {
  if (raw == null) return null;
  const value = raw.trim();
  if (STATIC_SEGMENTS.includes(value) || GROUP_SEGMENT.test(value) || STAGE_SEGMENT.test(value)) {
    return value as RecruitmentSegment;
  }
  return null;
}

export function parsePersonPanelSection(
  raw: string | null | undefined,
): PersonPanelSection | null {
  return oneOf(raw, PANEL_SECTIONS);
}

export function parseRecruitmentSlideOver(
  raw: string | null | undefined,
): RecruitmentSlideOver | null {
  return oneOf(raw, SLIDE_OVERS);
}

// ── Stan strony z adresu ─────────────────────────────────────────────────────

export interface JobDetailUrlState {
  /** `null` = adres nie wskazuje widoku (zostaje bieżący / domyślny). */
  view: JobDetailView | null;
  segment: RecruitmentSegment | null;
  panelSection: PersonPanelSection | null;
  slideOver: RecruitmentSlideOver | null;
  slideOverTab: JobHistoryChatTab | null;
  orderSection: JobOrderSection | null;
  /** `?highlight=ai-proposals` — podświetl segment propozycji po wejściu. */
  highlightProposals: boolean;
}

type ParamReader = { get(name: string): string | null };

/**
 * Stan strony wyczytany z adresu — nowego ALBO starego. Nowe parametry
 * wygrywają ze starym `?tab=`, więc adres w połowie przepisany też działa.
 */
export function readJobDetailUrlState(params: ParamReader | null | undefined): JobDetailUrlState {
  const get = (name: string) => params?.get(name) ?? null;
  const rawTab = get("tab");
  const view = parseJobDetailView(rawTab);
  const legacy = view ? null : resolveLegacyJobTab(rawTab);
  const highlightProposals = get("highlight") === "ai-proposals";
  const slideOver = parseRecruitmentSlideOver(get("win")) ?? legacy?.slideOver ?? null;
  const rawWinTab = get("wintab");
  return {
    view:
      view ??
      legacy?.view ??
      (highlightProposals || get("seg") || get("panel") ? "people" : null),
    segment:
      parseRecruitmentSegment(get("seg")) ??
      legacy?.segment ??
      (highlightProposals ? "proposals" : null),
    panelSection: parsePersonPanelSection(get("panel")) ?? legacy?.panelSection ?? null,
    slideOver,
    slideOverTab:
      slideOver === "history-chat"
        ? (oneOf(rawWinTab, HISTORY_TABS) ?? legacy?.slideOverTab ?? null)
        : null,
    orderSection:
      slideOver === "order"
        ? (oneOf(rawWinTab, ORDER_SECTIONS) ?? legacy?.orderSection ?? null)
        : null,
    highlightProposals,
  };
}

/**
 * Stary adres przepisany na nowy kształt. `null` = nie ma czego przepisywać.
 *
 * Pozostałe parametry (`candidate`, `intake`, `from`…) zostają nietknięte.
 * Wołający robi `router.replace`, nie `push` — stary adres nie ma zostawać
 * w historii („Wstecz" wracałoby w pętlę przepisywania).
 */
export function rewriteLegacyJobParams(
  params: URLSearchParams | ParamReader | null | undefined,
): URLSearchParams | null {
  if (!params) return null;
  const rawTab = params.get("tab");
  const isLegacyTab = rawTab != null && parseJobDetailView(rawTab) === null;
  const legacy = isLegacyTab ? resolveLegacyJobTab(rawTab) : null;
  // `champion` jest poprawnym nowym widokiem — nie ma czego przepisywać.
  const highlight = params.get("highlight") === "ai-proposals";
  if (!isLegacyTab && !highlight) return null;

  const next = new URLSearchParams(
    "toString" in params ? (params as URLSearchParams).toString() : "",
  );
  const state = readJobDetailUrlState(params);
  next.delete("tab");
  next.delete("highlight");
  const view = legacy?.view ?? state.view ?? JOB_DETAIL_DEFAULT_VIEW;
  if (view !== JOB_DETAIL_DEFAULT_VIEW) next.set("tab", view);
  if (state.segment) next.set("seg", state.segment);
  if (state.panelSection) next.set("panel", state.panelSection);
  if (state.slideOver) next.set("win", state.slideOver);
  const winTab = state.slideOverTab ?? state.orderSection;
  if (winTab) next.set("wintab", winTab);
  return next;
}
