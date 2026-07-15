"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * The contractor roster is now the "Obsługa kontraktorów" mode inside the
 * unified /contracts workspace. This route is kept as a redirect so old
 * links, bookmarks and the historical `/contractors?tab=` deep-links keep
 * working — the `tab` (draft/active/ending) is preserved and consumed by
 * ContractorsListV2 on the target page.
 *
 * Reads window.location.search (not useSearchParams) to avoid the Next 15
 * streaming-SSR Suspense boundary requirement.
 */
export default function ContractorsRedirect() {
  const router = useRouter();

  useEffect(() => {
    const src = new URLSearchParams(window.location.search);
    const params = new URLSearchParams();
    params.set("view", "operations");
    const tab = src.get("tab");
    if (tab) params.set("tab", tab);
    router.replace(`/contracts?${params.toString()}`);
  }, [router]);

  return (
    <div className="p-8 text-sm text-muted-foreground">
      Przenoszenie do modułu Kontrakty…
    </div>
  );
}
