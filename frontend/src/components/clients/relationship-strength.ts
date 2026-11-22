import type { StatusDotTone } from "@/components/ds/StatusDot";

/**
 * Siła relacji z osobą klienta — słownik etykiet i kolorów dla „Ludzie ›
 * Kontakty i relacje” w profilu klienta i znacznika „Wymaga uwagi” na liście
 * klientów (makieta 18.11.2026; dawniej w panelu „Kluczowe relacje”).
 */
export type RelationshipStrength = "cold" | "warm" | "strong" | "champion";

export const RELATIONSHIP_STRENGTH_COLORS: Record<RelationshipStrength, string> = {
  cold: "bg-muted text-muted-foreground",
  warm: "bg-warning-muted text-warning-muted-foreground",
  strong: "bg-primary/10 text-primary",
  champion: "bg-success-muted text-success-muted-foreground",
};

export const RELATIONSHIP_STRENGTH_LABELS: Record<RelationshipStrength, string> = {
  cold: "Chłodna",
  warm: "Ciepła",
  strong: "Mocna",
  champion: "Champion",
};

/** Ostatni osobisty kontakt: im dawniej, tym pilniej (> 30 dni ostrzeżenie, > 90 alarm). */
export function touchpointTone(days: number): StatusDotTone {
  if (days > 90) return "danger";
  if (days > 30) return "warning";
  return "success";
}
