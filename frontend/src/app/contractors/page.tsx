"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Dawna lista kontraktorów. Od 18.11.2026 to szybki filtr jednej listy
 * `/contracts`; trasa zostaje jako przekierowanie, żeby stare linki i zakładki
 * (`/contractors?tab=`) działały. `tab` (draft/active/ending) idzie dalej jako
 * `?view=operations&tab=…`, a strona `/contracts` zamienia go na ten sam
 * zbiór listy (`legacyOperationsTarget`).
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
