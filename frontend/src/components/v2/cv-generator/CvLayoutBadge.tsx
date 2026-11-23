"use client";

/**
 * Odznaka układu CV tam, gdzie ktoś ocenia CV przed wysyłką (przegląd DL,
 * panel osoby, QC): „Nowe CV · PDF” albo „Klasyczne · Word” — żeby było
 * widać, jaki plik dostanie klient (22.11.2026). Bez flagi i bez CV — nic.
 */

import { Badge } from "@/components/ui/badge";
import type { CVBrandedState, CvLayout } from "@/lib/api";

import { cvLayoutFact } from "./LayoutChoice";

export function CvLayoutBadge({
  branded,
  className,
}: {
  branded: CVBrandedState | null | undefined;
  className?: string;
}) {
  if (branded?.new_layout_enabled !== true || branded.status === "none") return null;
  return <LayoutBadge isNew={branded.cv_layout === "new"} className={className} />;
}

function LayoutBadge({ isNew, className }: { isNew: boolean; className?: string }) {
  return (
    <Badge
      size="sm"
      variant={isNew ? "info" : "neutral"}
      className={className}
      data-testid="cv-layout-badge"
      title={isNew ? "Do klienta idzie PDF w układzie Nowe CV." : "Do klienta idzie klasyczny plik Word."}
    >
      {cvLayoutFact(isNew ? "new" : "classic")}
    </Badge>
  );
}

/** Odznaka w oknie QC — układ przychodzi z wyniku QC (bez osobnego żądania). */
export function QcLayoutBadge({ layout, className }: { layout: CvLayout | null | undefined; className?: string }) {
  if (layout !== "new" && layout !== "classic") return null;
  return <LayoutBadge isNew={layout === "new"} className={className} />;
}
