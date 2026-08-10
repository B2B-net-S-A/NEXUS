"use client";

import { Suspense, useEffect, useState } from"react";
import { JobsListV2 } from"@/components/v2/pages/JobsListV2";

/**
 * Client-only gate — patrz komentarz w /contracts/page.tsx.
 */
export default function JobsPage() {
 const [mounted, setMounted] = useState(false);
 useEffect(() => {
 setMounted(true);
 }, []);
 if (!mounted) {
 return <div className="p-8 text-sm text-muted-foreground">Ładowanie rekrutacji…</div>;
 }
 // `JobsListV2` czyta `useSearchParams` (deep-linki z pulpitu), a Next
 // wymaga dla niego granicy Suspense — bez niej build wywala się na
 // prerenderze, mimo że strona i tak renderuje się tylko po stronie klienta.
 return (
 <Suspense
 fallback={
 <div className="p-8 text-sm text-muted-foreground">Ładowanie rekrutacji…</div>
 }
 >
 <JobsListV2 />
 </Suspense>
 );
}
