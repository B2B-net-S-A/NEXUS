/**
 * Sekcja 8 Profilu Championa — „Wiedza z rozmów” (09.2026).
 *
 * Notatki od klienta i od naszego konsultanta. Serwer zwraca je jako WIDOK
 * (`champion_view.insights`): zapisane notatki + wpisy składane ze starych pól
 * `client.consultant_insight`/`client.historical_questions` (`legacy:*`)
 * i z weryfikacji (`verification:*`, tylko do odczytu).
 *
 * Wpisy `legacy:*` edytuje się przez STARE POLE w sekcji `client` — serwer ich
 * nie zapisuje jako notatek (zapis zwrotny czyściłby stare pola przy każdym
 * zapisie z pustą listą). Dlatego `applyInsightEdit`/`removeInsight` zwracają
 * też łatkę `client`.
 *
 * `audience: "team"` jest domyślne i nie wychodzi poza zespół; szkic opisu na
 * stronę kariery czyta wyłącznie „candidate” (backend `job_public_profile`).
 */

import type {
  ChampionClient,
  InsightAudience,
  InsightNote,
  InsightSource,
  InsightTopic,
} from "@/lib/api";

export const INSIGHT_TOPIC_LABEL: Record<InsightTopic, string> = {
  needs: "Czego naprawdę szukają",
  rejections: "Za co odrzucają",
  decision: "Kto decyduje",
  process: "Proces i rozmowy",
  team: "Zespół i praca na co dzień",
  project: "Projekt",
  pitch: "Co przekonuje kandydatów",
  ask_client: "Do dopytania u klienta",
  other: "Inne",
};

export const INSIGHT_SOURCE_LABEL: Record<InsightSource, string> = {
  client: "Od klienta",
  consultant: "Od naszego konsultanta",
};

export const INSIGHT_AUDIENCE_LABEL: Record<InsightAudience, string> = {
  team: "Tylko zespół",
  candidate: "Można powiedzieć kandydatowi",
};

export interface InsightPrompt {
  topic: InsightTopic;
  question: string;
}

/** „O co zapytać” — lista podpowiedzi nad kolumną; klik ustawia temat notatki. */
export const INSIGHT_PROMPTS: Record<InsightSource, readonly InsightPrompt[]> = {
  client: [
    { topic: "needs", question: "Czego naprawdę szukają — a co w mailu jest „na wszelki wypadek”?" },
    { topic: "rejections", question: "Dlaczego odpadli poprzedni kandydaci?" },
    { topic: "decision", question: "Kto decyduje i jak prowadzi rozmowę techniczną?" },
    { topic: "process", question: "Ile etapów, jak szybko zapada decyzja?" },
    { topic: "needs", question: "Na co patrzą w CV w pierwszej kolejności?" },
    { topic: "rejections", question: "Czego nie napisali, a jest deal-breakerem?" },
  ],
  consultant: [
    { topic: "team", question: "Jak wygląda dzień pracy — spotkania, tempo, zdalnie/biuro?" },
    { topic: "team", question: "Zespół: ile osób, język, kto jest liderem?" },
    { topic: "project", question: "Jakich narzędzi naprawdę używają (vs ogłoszenie)?" },
    { topic: "project", question: "Co jest trudne w projekcie — legacy, presja, dokumentacja?" },
    { topic: "pitch", question: "Co trzyma ludzi w tym projekcie?" },
  ],
};

export const LEGACY_INSIGHT_FIELD: Record<string, keyof ChampionClient> = {
  "legacy:client.consultant_insight": "consultant_insight",
  "legacy:client.historical_questions": "historical_questions",
};

let counter = 0;

export function newInsight(
  source: InsightSource,
  topic: InsightTopic = "other",
  text = "",
): InsightNote {
  counter += 1;
  return {
    id: `new-${Date.now().toString(36)}-${counter}`,
    source,
    topic,
    audience: "team",
    text,
    done: false,
    origin: "manual",
    editable: true,
  };
}

export function isVerificationInsight(note: InsightNote): boolean {
  return note.id.startsWith("verification:");
}

export function isLegacyInsight(note: InsightNote): boolean {
  return note.id in LEGACY_INSIGHT_FIELD;
}

export interface InsightChange {
  insights: InsightNote[];
  /** Łatka sekcji `client` — tylko dla wpisów `legacy:*`. */
  client?: Partial<ChampionClient>;
}

export function applyInsightEdit(
  notes: readonly InsightNote[],
  id: string,
  patch: Partial<InsightNote>,
): InsightChange {
  const insights = notes.map((n) => (n.id === id ? { ...n, ...patch } : n));
  const field = LEGACY_INSIGHT_FIELD[id];
  if (field && typeof patch.text === "string") {
    return { insights, client: { [field]: patch.text } as Partial<ChampionClient> };
  }
  return { insights };
}

export function removeInsight(notes: readonly InsightNote[], id: string): InsightChange {
  const insights = notes.filter((n) => n.id !== id);
  const field = LEGACY_INSIGHT_FIELD[id];
  return field
    ? { insights, client: { [field]: "" } as Partial<ChampionClient> }
    : { insights };
}

export type InsightFilter = "all" | InsightAudience;

export function visibleInsights(
  notes: readonly InsightNote[],
  source: InsightSource,
  filter: InsightFilter,
): InsightNote[] {
  return notes.filter(
    (n) =>
      n.source === source &&
      n.topic !== "ask_client" &&
      (filter === "all" || n.audience === filter),
  );
}

export function askClientItems(notes: readonly InsightNote[]): InsightNote[] {
  return notes.filter((n) => n.topic === "ask_client");
}

export function insightOriginLabel(note: InsightNote): string | null {
  switch (note.origin) {
    case "verification":
      return "z weryfikacji";
    case "legacy":
    case "document":
      return "z importu";
    case "ai_intake":
      return "propozycja AI";
    default:
      return null;
  }
}

/**
 * Wpis „z importu” po zmianie starego pola spoza sekcji 8 (np. panel pytań
 * klienta dopisuje do `historical_questions`) — ten sam tekst w widoku.
 */
export function syncLegacyInsight(
  notes: readonly InsightNote[],
  id: keyof typeof LEGACY_INSIGHT_META,
  text: string,
): InsightNote[] {
  const existing = notes.find((n) => n.id === id);
  if (existing) return notes.map((n) => (n.id === id ? { ...n, text } : n));
  if (!text.trim()) return [...notes];
  return [
    ...notes,
    {
      id,
      ...LEGACY_INSIGHT_META[id],
      audience: "team",
      text,
      origin: "legacy",
      editable: true,
      done: false,
    },
  ];
}

const LEGACY_INSIGHT_META = {
  "legacy:client.consultant_insight": { source: "consultant", topic: "team" },
  "legacy:client.historical_questions": { source: "client", topic: "process" },
} as const satisfies Record<string, { source: InsightSource; topic: InsightTopic }>;
