"use client";

import { useEffect, useState } from"react";
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
 return <div className="p-8 text-sm text-muted-foreground">Ładowanie ofert…</div>;
 }
 return <JobsListV2 />;
}
