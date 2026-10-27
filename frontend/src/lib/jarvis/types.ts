/**
 * Kontrakt Jarvisa z backendem (`backend/app/api/jarvis.py`,
 * `backend/app/services/jarvis/*`). Zmieniając kształt po jednej stronie,
 * zmień i tu.
 */

export type JarvisCharacterId =
  | "robot"
  | "owl"
  | "cat"
  | "ghost"
  | "rocket"
  | "star"
  | "dragon"
  | "astronaut"
  | "robot_gold"
  | "trophy";

export type JarvisAccent = "primary" | "violet" | "blue" | "green" | "orange" | "rose" | "graphite";

export interface JarvisPrefs {
  character: JarvisCharacterId;
  name: string;
  accent: JarvisAccent;
  enabled: boolean;
  minimized: boolean;
  sound: boolean;
  daily_brief: boolean;
  /** Dymek „co tu robisz” przy pierwszej wizycie na ekranie. */
  screen_tips: boolean;
  /** „Co Jarvis o mnie wie” — preferencje wpisane przez użytkownika (≤10). */
  notes: string[];
}

export interface JarvisPrefsResponse extends JarvisPrefs {
  unlocked_characters: JarvisCharacterId[];
  locked_characters: Partial<Record<JarvisCharacterId, string>>;
}

export interface JarvisStatus {
  available: boolean;
  reason?: "impersonation" | "disabled" | "not_configured" | null;
  used_today: number;
  soft_limit: number;
  busy: boolean;
  web_enabled?: boolean;
  web_used_today?: number;
  web_limit?: number;
  capabilities?: JarvisCapabilities;
}

export interface JarvisSource {
  url: string;
  title: string;
}

export type JarvisActionStatus = "proposed" | "confirmed" | "rejected" | "executed" | "failed" | "expired";

export interface JarvisAction {
  id: string;
  tool: string;
  status: JarvisActionStatus;
  preview: {
    text: string;
    tool_label?: string;
    warning?: string;
    /** Pełna treść zapisu (np. notatki) — renderowana jako zwykły tekst. */
    body?: string;
  };
  /** `uncertain` = wykonanie przerwane w trakcie — nie wiadomo, czy się zapisało. */
  result?: { ok?: boolean; error?: string; uncertain?: boolean } | null;
  /** Zapis wykonany od razu (notatka, dodanie do rekrutacji, „Moi ludzie”):
   *  stan przycisku „Cofnij”; `null` = tej akcji się nie cofa. */
  undo?: { state: "available" | "running" | "done" | "failed" | "expired"; until: string | null } | null;
}

export interface JarvisLink {
  href: string;
  label: string;
  reason: string;
}

/** Czego Jarvisowi brakuje — lustro `GAP_KINDS` w `services/jarvis/gap_schema.py`. */
export type GapKind = "no_access" | "not_supported" | "no_data";

/** Karta „Tego nie zrobię” (`report_gap`, tabela `jarvis_gaps`). */
export interface JarvisGap {
  id: string;
  kind: GapKind;
  need: string;
  why: string;
  workaround: string;
  reported: boolean;
}

/** Wiersz listy „Czego Jarvis nie umie” (`GET /api/jarvis/gaps`, admin). */
export interface JarvisGapReportRow extends JarvisGap {
  role: string;
  created_at: string;
}

/** Pusty panel: co Jarvis zrobi za tę rolę (`services/jarvis/capabilities.py`). */
export interface JarvisCapabilities {
  read: string[];
  write: string[];
  never: string[];
}

/** Pozycja widoku rozmowy — i z historii (`GET …/conversations/{id}`), i ze strumienia. */
export type JarvisItem =
  | { kind: "message"; role: "user" | "assistant"; markdown: string; streaming?: boolean }
  | { kind: "link"; href: string; label: string; reason: string }
  | { kind: "action"; action: JarvisAction }
  | { kind: "steps"; steps: JarvisStep[] }
  | { kind: "sources"; items: JarvisSource[] }
  | { kind: "error"; message: string }
  /** Karta przewodnika ekranu — lokalnie, bez modelu. */
  | { kind: "guide"; guide: ScreenGuide }
  /** Element podświetlony na ekranie (show_on_screen albo „Pokaż na ekranie”). */
  | { kind: "highlight"; anchor: string; label: string; reason: string }
  /** Karta „Tego nie zrobię” (report_gap) z przyciskiem zgłoszenia potrzeby. */
  | { kind: "gap"; gap: JarvisGap };

/** Przewodnik ekranu (`GET /api/help/screens`, `backend/app/data/screen_guides`). */
export interface ScreenGuideTask {
  q: string;
  a: string;
  anchor?: string | null;
}

export interface ScreenGuideAnchor {
  id: string;
  label: string;
  describe: string;
}

export interface ScreenGuide {
  key: string;
  title: string;
  section?: string | null;
  roles: string[];
  what: string;
  tasks: ScreenGuideTask[];
  pitfalls: string[];
  anchors: ScreenGuideAnchor[];
  help_slug?: string | null;
}

export interface JarvisStep {
  tool: string;
  label: string;
  status: "running" | "done" | "error";
}

export interface JarvisConversationSummary {
  id: string;
  title: string;
  updated_at: string;
}

export interface JarvisConversationDetail {
  id: string;
  title: string;
  items: JarvisItem[];
}

export interface JarvisActionOutcome {
  action: JarvisAction;
  message: string;
  follow_up?: JarvisAction | null;
  invalidates: string[][];
}

export type JarvisStreamEvent =
  | { type: "conversation"; conversation_id: string }
  | { type: "thinking"; step: number }
  | { type: "step"; tool: string; label: string; status: JarvisStep["status"] }
  | { type: "message"; markdown: string; final?: boolean }
  /** Fragment odpowiedzi na żywo; `message` na końcu kroku go zastępuje. */
  | { type: "delta"; text: string }
  /** Ponowienie wywołania modelu — to, co pokazano, jest do wyrzucenia. */
  | { type: "delta_reset" }
  | { type: "highlight"; anchor: string; label: string; reason: string }
  | { type: "gap"; gap: JarvisGap }
  /** Przy zapisie wykonanym od razu niesie też komunikat i klucze do odświeżenia. */
  | { type: "action_proposed"; action: JarvisAction; message?: string; invalidates?: string[][] }
  | ({ type: "deep_link" } & JarvisLink)
  | { type: "sources"; items: JarvisSource[] }
  | { type: "error"; message: string; code?: string }
  | { type: "done" };

export interface JarvisScreen {
  path: string;
  entity?: { type: "candidate" | "job" | "client" | "contract"; id: number } | null;
  /** Klucz przewodnika ekranu (`lib/help/screen-key.ts`). */
  key?: string | null;
}

/** Stan maskotki — steruje animacją postaci. */
export type JarvisMood = "idle" | "listening" | "thinking" | "working" | "success" | "error";
