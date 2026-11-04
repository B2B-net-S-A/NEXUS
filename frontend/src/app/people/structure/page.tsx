"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { structureRedirectHref } from "@/components/hr/people/directory-url";

// „Ludzie → Struktura” (17.10.2026) jest od 22.10.2026 widokiem „Schemat”
// katalogu. Stare linki i zakładki przeglądarki prowadzą tam z resztą adresu.
function RedirectToSchema() {
  const router = useRouter();
  const search = useSearchParams()?.toString() ?? "";
  useEffect(() => {
    router.replace(structureRedirectHref(search));
  }, [router, search]);
  return <p className="py-6 text-sm text-muted-foreground">Przenoszenie do schematu…</p>;
}

export default function PeopleStructurePage() {
  return (
    <Suspense fallback={null}>
      <RedirectToSchema />
    </Suspense>
  );
}
