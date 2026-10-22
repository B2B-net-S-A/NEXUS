"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { consentsRedirectHref } from "@/components/hr/approvals/consents-url";

// „Ludzie → Moje zgody” (20.10.2026) jest od 22.10.2026 zakładką „Zgody
// i wydatki” w „Moim czasie”. Stare linki z dzwonków i maili prowadzą tam
// z numerem zgody (`request`) i otwartym formularzem (`new=1`).
function RedirectToMyTime() {
  const router = useRouter();
  const search = useSearchParams()?.toString() ?? "";
  useEffect(() => {
    router.replace(consentsRedirectHref(search));
  }, [router, search]);
  return <p className="py-6 text-sm text-muted-foreground">Przenoszenie do Mojego czasu…</p>;
}

export default function PeopleConsentsPage() {
  return (
    <Suspense fallback={null}>
      <RedirectToMyTime />
    </Suspense>
  );
}
