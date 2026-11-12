import { formatIsoDatePl } from "@/lib/date-pl";

import type { DecisionMapEntry } from "@/lib/api/sales";

/** Podpisy pól mapy decyzyjnej: wspólne dla listy osób i okna poprawki. */
export const DECISION_LEVELS = ["Zarząd / C-level", "Dyrektorzy", "Kierownicy", "Zespół"];

/**
 * Skąd pochodzi wpis i od kiedy jest na mapie: tylko dla osoby z importu listy.
 * Wpisy z Atlasa i dodane ręcznie nie niosą źródła, więc nic nie pokazują.
 */
export function sourceLine(
  entry: Pick<DecisionMapEntry, "source_label" | "source_added_at" | "source_confidence" | "source_published_at">,
): string | null {
  const label = entry.source_label?.trim();
  if (!label) return null;
  return [
    `źródło: ${label}`,
    entry.source_published_at ? `opublikowane ${formatIsoDatePl(entry.source_published_at)}` : null,
    entry.source_added_at ? `na mapie od ${formatIsoDatePl(entry.source_added_at)}` : null,
    entry.source_confidence === "to_verify" ? "do weryfikacji" : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

export const OUR_ROLE_LABELS: Record<string, string> = {
  decision_maker: "Decydent",
  economic_buyer: "Budżet",
  champion: "Champion",
  influencer: "Wpływa",
  blocker: "Hamuje",
  end_user: "Użytkownik",
};

export const CONTACT_STATUS: Record<
  string,
  { label: string; variant: "neutral" | "info" | "success" | "warning" }
> = {
  not_contacted: { label: "bez kontaktu", variant: "warning" },
  in_progress: { label: "w toku", variant: "info" },
  first_contact: { label: "pierwszy kontakt", variant: "info" },
  regular_dialog: { label: "stały dialog", variant: "success" },
};
