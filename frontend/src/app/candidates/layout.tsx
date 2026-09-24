"use client";

import { usePathname } from "next/navigation";
import { CandidateTabsRail } from "@/components/v2/candidates/CandidateTabsRail";

/**
 * Wraps the /candidates section so the recently-viewed-candidates rail can sit
 * to the left of the list and detail pages — the candidate counterpart to the
 * "Rekrutacje" rail in app/jobs/layout.tsx. It replaces the former horizontal
 * open-tabs strip so recently opened candidates live in this rail.
 *
 * Scoped to the list page (/candidates) and detail pages (/candidates/<id>).
 * The special-purpose sub-tools (search, compare, bulk-import) render bare so
 * the rail doesn't crowd their full-width layouts. The rail itself self-hides
 * when no candidate tabs are open and below 2xl (where the list/detail page
 * needs the full width).
 */
export default function CandidatesLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const showRail =
    pathname === "/candidates" || /^\/candidates\/\d+/.test(pathname ?? "");

  if (!showRail) return <>{children}</>;

  return (
    <div className="flex items-start gap-4 2xl:gap-6">
      {/* Szyna od 2xl: na 1024–1535 px (z paskiem bocznym) zabierała liście
          i profilowi połowę szerokości — ucięte kolumny, ściśnięty profil. */}
      <CandidateTabsRail className="sticky top-0 hidden max-h-[calc(100dvh-7rem)] self-start 2xl:flex" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
