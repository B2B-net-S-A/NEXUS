"use client";

import { usePathname } from "next/navigation";
import { CandidateTabsRail } from "@/components/v2/candidates/CandidateTabsRail";

/**
 * Wraps the /candidates section so the recently-viewed-candidates rail can sit
 * to the left of the list and detail pages — the candidate counterpart to the
 * "Rekrutacje" rail in app/jobs/layout.tsx. Replaces the horizontal open-tabs
 * strip (OpenTabsV2 hides the whole strip on these routes, mirroring the job
 * detail pages) so recently opened items live in one place, not two.
 *
 * Scoped to the list page (/candidates) and detail pages (/candidates/<id>).
 * The special-purpose sub-tools (search, compare, bulk-import) render bare so
 * the rail doesn't crowd their full-width layouts. The rail itself self-hides
 * when no candidate tabs are open and on small screens (where the list/detail
 * page is shown full-width without it).
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
    <div className="flex items-start gap-4 lg:gap-6">
      <CandidateTabsRail className="sticky top-0 hidden max-h-[calc(100vh-7rem)] self-start lg:flex" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
