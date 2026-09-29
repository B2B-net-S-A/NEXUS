"use client";

/**
 * Historia zmian roli z biblioteki i hasła słowniczka „Po ludzku”.
 * Wspólna dla obu ekranów Ustawień — kształt wpisu jest ten sam
 * (`{created_at, user_name, changes: {pole: {old, new}}}`).
 */

import type { ChangeHistoryEntry } from "@/lib/api/plainKnowledge";
import { formatDate } from "@/lib/utils";

export const PLAIN_FIELD_LABEL: Record<string, string> = {
  name: "Nazwa",
  display_name: "Nazwa",
  summary: "Po ludzku",
  example: "Przykład z codzienności",
  day_to_day: "Czym się zajmuje",
  candidate_questions: "O co pyta kandydat",
  typical_skills: "Typowe technologie",
  does: "Do czego służy",
  cv_hints: "W CV szukaj",
  confused_with: "Nie myl z",
  sources: "Źródła",
  origin: "Pochodzenie",
  status: "Stan",
};

function show(value: unknown): string {
  if (value == null || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.map((v) => show(v)).join(", ") : "—";
  if (typeof value === "object") {
    const maybe = value as { title?: unknown; url?: unknown };
    if (typeof maybe.url === "string") return String(maybe.title || maybe.url);
    return JSON.stringify(value);
  }
  return String(value);
}

export function PlainChangeHistory({ entries }: { entries: readonly ChangeHistoryEntry[] }) {
  if (entries.length === 0) {
    return <p className="text-xs text-muted-foreground">Bez zmian od dodania.</p>;
  }
  return (
    <ol className="space-y-2" aria-label="Historia zmian">
      {entries.map((entry, i) => (
        <li key={`${entry.created_at}-${i}`} className="rounded-md border border-border px-3 py-2 text-xs">
          <p className="text-muted-foreground">
            {formatDate(entry.created_at)} · {entry.user_name?.trim() || "system"}
          </p>
          <ul className="mt-1 space-y-0.5">
            {Object.entries(entry.changes ?? {}).map(([field, change]) => (
              <li key={field} className="break-words text-foreground">
                <span className="font-medium">{PLAIN_FIELD_LABEL[field] ?? field}:</span>{" "}
                <span className="text-muted-foreground line-through">{show(change?.old)}</span>{" "}
                → {show(change?.new)}
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ol>
  );
}
