"use client";

import { usePathname } from "next/navigation";
import { JobTabsRail } from "@/components/v2/jobs/JobTabsRail";

/**
 * Wraps the /jobs section so the "Otwarte rekrutacje" rail (Traffit-style open
 * tabs) can sit to the left of a recruitment detail page. Scoped to detail
 * routes (/jobs/<id>...) — on the list page the rail would only duplicate the
 * list, so we render children bare there. The rail itself self-hides when no
 * job tabs are open and on small screens (the top tab bar covers those cases).
 */
export default function JobsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isDetail = /^\/jobs\/\d+/.test(pathname ?? "");

  if (!isDetail) return <>{children}</>;

  return (
    <div className="flex items-start gap-4 lg:gap-6">
      <JobTabsRail className="sticky top-0 hidden max-h-[calc(100vh-7rem)] self-start lg:flex" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
