// Historia kontraktu po ludzku (przebudowa 19.11.2026, wariant A).
//
// Dawny „Timeline” pokazywał surowe pola („via sharepoint_import”, „size
// bytes”), JSON „new / old” wychodzący poza kartę i adres e-mail zamiast
// nazwiska, a zdarzenia z migracji i synchronizacji wyglądały jak zmiany
// człowieka. Tu: jedno zdanie na zdarzenie, rodzaj do filtrów, oznaczenie
// zdarzeń automatycznych i zwijanie serii (import kilku plików naraz).
import {
  contractActivityDetailRows,
  contractActivityLabel,
} from "@/components/contracts/contract-timeline-labels";

export interface ContractActivity {
  id: number;
  action: string;
  details: Record<string, unknown> | null;
  user_name: string | null;
  created_at: string;
}

export type HistoryKind = "contract" | "money" | "documents" | "automatic";

export interface HistoryEvent {
  id: number;
  at: string;
  /** „Artur Kowalski” z adresu e-mail; `null` = NEXUS (bez autora). */
  who: string | null;
  automatic: boolean;
  kind: HistoryKind;
  title: string;
  detail: string | null;
  action: string;
}

export interface HistoryGroup {
  key: string;
  events: HistoryEvent[];
}

const DOC_TYPE: Record<string, string> = {
  contract: "umowa",
  annex: "aneks",
  order: "zamówienie",
  nda: "NDA",
  other: "inny dokument",
};

const DIFF_LABEL: Record<string, string> = {
  rate_client: "stawka klienta",
  rate_candidate: "stawka kandydata",
  end_date: "koniec projektu",
  start_date: "start",
  status: "status",
  line_manager: "line manager",
  work_mode: "tryb pracy",
  team_name: "zespół",
  project_name: "projekt",
};

const AUTOMATIC_ACTIONS = new Set(["synced_with_orders", "status_auto_changed", "rate_unit_converted_to_hourly"]);

/** „jan.kowalski@firma.pl” → „Jan Kowalski”; wartość bez „@” zostaje. */
export function personFromEmail(value: string | null | undefined): string | null {
  if (!value) return null;
  if (!value.includes("@")) return value;
  return value
    .split("@")[0]
    .split(/[._-]+/)
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}

function fmtValue(key: string, v: unknown): string {
  if (v == null || v === "") return "—";
  if (key.endsWith("_date") && typeof v === "string") {
    const [y, m, d] = v.slice(0, 10).split("-");
    return `${d}.${m}.${y}`;
  }
  if (typeof v === "number") return v.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return String(v);
}

/** „stawka klienta 175,00 → 163,00 · stawka kandydata 135,00 → 125,00” — tylko pola, które się zmieniły. */
export function diffSentence(oldV: unknown, newV: unknown): string | null {
  if (!newV || typeof newV !== "object") return null;
  const o = (oldV && typeof oldV === "object" ? oldV : {}) as Record<string, unknown>;
  const parts = Object.entries(newV as Record<string, unknown>)
    .filter(([k, v]) => DIFF_LABEL[k] && o[k] !== v)
    .map(([k, v]) => `${DIFF_LABEL[k]} ${fmtValue(k, o[k])} → ${fmtValue(k, v)}`);
  return parts.length ? parts.join(" · ") : null;
}

function isMigrationSource(source: unknown): boolean {
  return typeof source === "string" && (/^\d{4}_/.test(source) || source.includes("backfill") || source.includes("sync"));
}

export function humanizeActivity(a: ContractActivity): HistoryEvent {
  const d = a.details ?? {};
  const automatic = !a.user_name || AUTOMATIC_ACTIONS.has(a.action) || isMigrationSource(d.source);
  const base = { id: a.id, at: a.created_at, who: personFromEmail(a.user_name), automatic, action: a.action };
  switch (a.action) {
    case "document_uploaded":
    case "document_deleted": {
      const type = DOC_TYPE[String(d.doc_type ?? "")];
      return {
        ...base,
        kind: automatic ? "automatic" : "documents",
        title: `${a.action === "document_uploaded" ? "Dodano" : "Usunięto"} dokument „${String(d.filename ?? "")}”`,
        detail: [type, d.via === "sharepoint_import" ? "z SharePointa" : null].filter(Boolean).join(" · ") || null,
      };
    }
    case "amendment_rate_change":
    case "amendment_extension":
    case "amendment_scope_change":
      return {
        ...base,
        kind: automatic ? "automatic" : "money",
        title: contractActivityLabel(a.action),
        detail: diffSentence(d.old, d.new),
      };
    case "updated":
      return {
        ...base,
        kind: automatic ? "automatic" : "contract",
        title: contractActivityLabel(a.action),
        detail: diffSentence(d.old, d.new),
      };
    default: {
      const rows = contractActivityDetailRows(a.details)
        .filter((r) => !["source", "via", "size_bytes"].includes(r.key) && r.value !== "—")
        .slice(0, 3);
      return {
        ...base,
        kind: automatic ? "automatic" : a.action.startsWith("amendment") ? "money" : "contract",
        title: contractActivityLabel(a.action),
        detail: rows.length ? rows.map((r) => `${r.label}: ${r.value}`).join(" · ") : null,
      };
    }
  }
}

/** Kolejne zdarzenia tego samego rodzaju, tej samej osoby, tego samego dnia — jedna grupa. */
export function groupHistory(events: HistoryEvent[]): HistoryGroup[] {
  const groups: HistoryGroup[] = [];
  for (const e of events) {
    const prev = groups[groups.length - 1];
    const head = prev?.events[0];
    if (head && head.action === e.action && head.who === e.who && head.at.slice(0, 10) === e.at.slice(0, 10)) {
      prev.events.push(e);
    } else {
      groups.push({ key: `${e.id}`, events: [e] });
    }
  }
  return groups;
}

/** Tytuł zwiniętej grupy: „Dodano 3 dokumenty”. */
export function groupTitle(group: HistoryGroup): string {
  const n = group.events.length;
  const first = group.events[0];
  if (n === 1) return first.title;
  const docs = n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? "dokumenty" : "dokumentów";
  if (first.action === "document_uploaded") return `Dodano ${n} ${docs}`;
  if (first.action === "document_deleted") return `Usunięto ${n} ${docs}`;
  return `${first.title} (${n}×)`;
}

export const HISTORY_FILTERS: { key: "all" | HistoryKind; label: string }[] = [
  { key: "all", label: "Wszystko" },
  { key: "contract", label: "Zmiany umowy" },
  { key: "money", label: "Stawki" },
  { key: "documents", label: "Dokumenty" },
  { key: "automatic", label: "Automatyczne" },
];
