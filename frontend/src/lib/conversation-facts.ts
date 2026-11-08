import type { ConversationFact } from "@/lib/api";

/** Etykieta źródła faktu w bloku „Z rozmów” i w panelu osoby. */
export function factSourceLabel(fact: Pick<ConversationFact, "source">): string {
  return fact.source === "sheet" ? "z arkusza" : "z notatek (AI)";
}

const KIND_LABEL: Record<ConversationFact["kind"], string> = {
  skill: "umiejętność",
  domain: "branża",
  certification: "certyfikat",
  regulation: "regulacja",
};

export function factKindLabel(fact: Pick<ConversationFact, "kind">): string {
  return KIND_LABEL[fact.kind];
}

/** Liczby do plakietki w panelu osoby; `null` = nie ma czego pokazać. */
export function factsSummary(facts: readonly ConversationFact[]): { confirmed: number; absent: number } | null {
  const absent = facts.filter((fact) => fact.status === "absent").length;
  const confirmed = facts.length - absent;
  return facts.length > 0 ? { confirmed, absent } : null;
}

/** Tekst plakietki: „3 potwierdzone · 1 nie ma”. */
export function factsSummaryText(summary: { confirmed: number; absent: number }): string {
  const parts: string[] = [];
  if (summary.confirmed) parts.push(`${summary.confirmed} ${pluralConfirmed(summary.confirmed)}`);
  if (summary.absent) parts.push(`${summary.absent} nie ma`);
  return parts.join(" · ");
}

function pluralConfirmed(count: number): string {
  const lastTwo = count % 100;
  const last = count % 10;
  const few = last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14);
  return count === 1 || few ? "potwierdzone" : "potwierdzonych";
}
