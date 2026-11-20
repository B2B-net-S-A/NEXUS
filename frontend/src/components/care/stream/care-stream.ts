// Strumień „Rozmowy i notatki” zakładki „Opieka i rozmowy” kontraktu
// (wariant A, 20.11.2026) — czyste reguły bez Reacta, z testami.
//
// Jeden strumień zamiast trzech kart (karta opieki z „Historią”, „Opinie
// klienta”, „Notatki i rozmowy”): notatki i połączenia kontraktu, rozmowy
// z konsultantem, karty technologiczne, opinie klienta i zmiany w opiece
// (opiekun, rytm, sprawy, przekazanie) — od najnowszych. Zdarzenia umowy
// i zamówień są w nagłówku, „Przeglądzie” i „Historii” strony, plan kontaktów
// w prawej kolumnie, więc tu ich nie powtarzamy.

import type { ContractTimelineItem } from "@/lib/api";
import {
  CHANNEL_LABELS,
  type CareConversation,
  type TechCard,
  type TimelineEvent,
  type TimelineKind,
} from "@/lib/api/care";
import {
  EXTENSION_LABELS,
  FEEDBACK_CHANNEL_LABELS,
  SCORE_LABELS,
  formatAverage,
  type ContractFeedbackItem,
  type ScoreField,
} from "@/lib/api/client-people";
import { personFromEmail } from "@/lib/contract-history";
import { formatIsoDatePl } from "@/lib/date-pl";
import { warsawDateOf } from "@/lib/warsaw-date";

export type StreamKind = "note" | "call" | "consultant" | "project" | "client" | "care";

export interface StreamItem {
  key: string;
  kind: StreamKind;
  /** Dzień w kalendarzu firmy (`RRRR-MM-DD`). */
  day: string;
  /** Chwila do kolejności w obrębie dnia (znacznik czasu albo sam dzień). */
  at: string;
  title: string;
  body: string | null;
  /** Oceny, sygnały i czas trwania — jedna linia drobnym drukiem. */
  facts: string[];
  /** Kto zapisał — imię i nazwisko, nigdy adres e-mail. */
  author: string | null;
  /** Zmiana w opiece bez treści rozmowy — wyszarzona jednym wierszem. */
  quiet: boolean;
  /** Karta technologiczna — „Edytuj” w strumieniu. */
  techCard: { id: number; on: string } | null;
  link: string | null;
}

export type StreamFilter = "all" | "talks" | "notes" | "feedback" | "care";

export const STREAM_FILTERS: { value: StreamFilter; label: string }[] = [
  { value: "all", label: "Wszystko" },
  { value: "talks", label: "Rozmowy" },
  { value: "notes", label: "Notatki" },
  { value: "feedback", label: "Opinie klienta" },
  { value: "care", label: "Zmiany w opiece" },
];

const KIND_FILTER: Record<StreamKind, Exclude<StreamFilter, "all">> = {
  consultant: "talks",
  project: "talks",
  call: "talks",
  note: "notes",
  client: "feedback",
  care: "care",
};

/** Zdarzenia osi opieki, które stoją w strumieniu jako „zmiana w opiece”. */
const CARE_EVENT_KINDS: ReadonlySet<TimelineKind> = new Set<TimelineKind>([
  "owner",
  "cadence",
  "cadence_return",
  "handoff",
  "redeploy",
  "case_opened",
  "case_closed",
  "case_linked",
]);

/** Rodzaj notatki kontraktu słowem (lustro `NoteType`). */
export const NOTE_KIND_LABELS: Record<string, string> = {
  general: "Notatka",
  call: "Notatka · telefon",
  meeting: "Notatka · spotkanie",
  email: "Notatka · e-mail",
  interview: "Notatka · rozmowa rekrutacyjna",
};

const CALL_LABELS: Record<string, string> = {
  inbound: "Połączenie przychodzące",
  outbound: "Połączenie wychodzące",
};

const SCORE_FIELDS: ScoreField[] = ["quality", "communication", "autonomy"];

const MENTION_RE = /@([A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/g;

/** `@jan.kowalski@firma.pl` w treści → `@Jan Kowalski` (wzmianka po ludzku). */
export function withMentionNames(text: string): string {
  return text.replace(MENTION_RE, (_, email: string) => `@${personFromEmail(email) ?? email}`);
}

/** Puste linie usunięte (wąska kolumna), brzegi przycięte; pusta treść → `null`. */
export function tidyText(text: string | null | undefined): string | null {
  if (!text) return null;
  const tidy = text.replace(/\r\n/g, "\n").replace(/\n\s*\n+/g, "\n").trim();
  return tidy || null;
}

/** Treść dłuższa niż trzy linie w kolumnie — pokazujemy „Rozwiń”. */
export function isLongText(text: string | null): boolean {
  if (!text) return false;
  return text.length > 240 || text.split("\n").length > 3;
}

const compact = (parts: (string | null | undefined | false)[]): string[] =>
  parts.filter((part): part is string => Boolean(part));

function minutes(seconds: number | null): string | null {
  if (!seconds) return null;
  return `${Math.max(1, Math.round(seconds / 60))} min`;
}

function noteItem(note: ContractTimelineItem): StreamItem {
  const day = warsawDateOf(note.at) ?? note.at.slice(0, 10);
  const author = personFromEmail(note.author_name);
  if (note.kind === "call") {
    return {
      key: `call-${note.id}`,
      kind: "call",
      day,
      at: note.at,
      title: CALL_LABELS[note.sub_type ?? ""] ?? "Połączenie",
      body: tidyText(note.summary ?? note.content),
      facts: compact([minutes(note.duration_seconds)]),
      author,
      quiet: false,
      techCard: null,
      link: null,
    };
  }
  const content = tidyText(note.content);
  return {
    key: `note-${note.id}`,
    kind: "note",
    day,
    at: note.at,
    title: NOTE_KIND_LABELS[note.sub_type ?? ""] ?? "Notatka",
    body: content ? withMentionNames(content) : null,
    facts: [],
    author,
    quiet: false,
    techCard: null,
    link: null,
  };
}

function conversationItem(talk: CareConversation): StreamItem {
  const channel = CHANNEL_LABELS[talk.channel]?.toLowerCase();
  return {
    key: `talk-${talk.id}`,
    kind: "consultant",
    day: talk.occurred_on,
    at: talk.occurred_on,
    title: compact(["Rozmowa z konsultantem", channel]).join(" · "),
    body: tidyText(talk.note),
    facts: compact([
      talk.satisfaction != null ? `zadowolenie ${talk.satisfaction} / 5` : null,
      talk.attrition_risk && "ryzyko odejścia",
      talk.wants_change && "chce zmiany projektu",
      talk.project_end_on ? `koniec projektu ${formatIsoDatePl(talk.project_end_on)}` : null,
      talk.client_hiring
        ? `klient zatrudnia${talk.client_hiring_note ? `: ${talk.client_hiring_note}` : ""}`
        : null,
      talk.follow_up_on ? `następny kontakt ${formatIsoDatePl(talk.follow_up_on)}` : null,
    ]),
    author: talk.author?.name ?? null,
    quiet: false,
    techCard: null,
    link: null,
  };
}

function techCardItem(card: TechCard): StreamItem {
  const quote = tidyText(card.memorable_quote);
  return {
    key: `tech-${card.id}`,
    kind: "project",
    day: card.interview_on,
    at: card.interview_on,
    title: "Rozmowa o projekcie · karta technologiczna",
    body: quote ? `„${quote}”` : tidyText(card.note),
    facts: compact([
      card.area ? `dział ${card.area.name}` : null,
      card.skills.length ? `technologie: ${card.skills.length}` : null,
      card.team_size ? `zespół ${card.team_size} osób` : null,
      card.satisfaction != null ? `zadowolenie ${card.satisfaction} / 5` : null,
    ]),
    author: card.author?.name ?? null,
    quiet: false,
    techCard: { id: card.id, on: card.interview_on },
    link: null,
  };
}

function feedbackItem(item: ContractFeedbackItem): StreamItem {
  const channel = FEEDBACK_CHANNEL_LABELS[item.channel]?.toLowerCase();
  return {
    key: `feedback-${item.session_id}`,
    kind: "client",
    day: item.held_on,
    at: item.held_on,
    title: compact(["Rozmowa z klientem", channel, item.contact?.name]).join(" · "),
    body: tidyText(item.note),
    facts: compact([
      ...SCORE_FIELDS.map((field) =>
        item[field] != null ? `${SCORE_LABELS[field]} ${item[field]}` : null,
      ),
      item.average != null ? `średnio ${formatAverage(item.average)}` : null,
      item.extension_outlook ? `przedłużenie: ${EXTENSION_LABELS[item.extension_outlook]}` : null,
    ]),
    author: item.author?.name ?? null,
    quiet: false,
    techCard: null,
    link: null,
  };
}

function careEventItem(event: TimelineEvent, index: number): StreamItem {
  return {
    key: `care-${event.kind}-${event.on}-${index}`,
    kind: "care",
    day: event.on,
    at: event.on,
    title: event.title,
    body: null,
    facts: compact([event.detail]),
    author: null,
    quiet: true,
    techCard: null,
    link: event.link,
  };
}

export interface StreamSources {
  notes?: ContractTimelineItem[] | null;
  conversations?: CareConversation[] | null;
  techCards?: TechCard[] | null;
  feedback?: ContractFeedbackItem[] | null;
  timeline?: TimelineEvent[] | null;
}

/**
 * Jeden strumień od najnowszych: dzień w kalendarzu firmy, w obrębie dnia
 * chwila zapisu. Szkice kart technologicznych i to, co przed nami (plan),
 * nie wchodzą; rozmowy, karty i opinie bierzemy z pełnych źródeł, nie
 * z osi opieki (tam treść jest ucięta do jednej linii).
 */
export function buildCareStream(sources: StreamSources): StreamItem[] {
  const items: StreamItem[] = [
    ...(sources.notes ?? []).map(noteItem),
    ...(sources.conversations ?? []).map(conversationItem),
    ...(sources.techCards ?? []).filter((card) => !card.is_draft).map(techCardItem),
    ...(sources.feedback ?? []).map(feedbackItem),
    ...(sources.timeline ?? [])
      .filter((event) => !event.future && CARE_EVENT_KINDS.has(event.kind))
      .map(careEventItem),
  ];
  return items.sort((a, b) => b.day.localeCompare(a.day) || b.at.localeCompare(a.at));
}

export function filterStream(items: StreamItem[], filter: StreamFilter): StreamItem[] {
  return filter === "all" ? items : items.filter((item) => KIND_FILTER[item.kind] === filter);
}

export function streamCounts(items: StreamItem[]): Record<StreamFilter, number> {
  const counts: Record<StreamFilter, number> = { all: 0, talks: 0, notes: 0, feedback: 0, care: 0 };
  for (const item of items) {
    counts.all += 1;
    counts[KIND_FILTER[item.kind]] += 1;
  }
  return counts;
}

/** Filtry z czymś w środku; „Wszystko” zawsze, ale tylko przy dwóch rodzajach. */
export function visibleFilters(counts: Record<StreamFilter, number>): StreamFilter[] {
  const kinds = STREAM_FILTERS.filter((f) => f.value !== "all" && counts[f.value] > 0).map((f) => f.value);
  return kinds.length > 1 ? ["all", ...kinds] : [];
}
