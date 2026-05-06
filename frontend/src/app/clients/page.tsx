"use client";

import { useEffect, useState } from"react";
import { ClientsListV2 } from"@/components/v2/pages/ClientsListV2";

/**
 * Client-only gate — patrz komentarz w /contracts/page.tsx.
 */
export default function ClientsPage() {
 const [mounted, setMounted] = useState(false);
 useEffect(() => {
 setMounted(true);
 }, []);
 if (!mounted) {
 return <div className="p-8 text-sm text-muted-foreground">Ładowanie klientów…</div>;
 }
 return <ClientsListV2 />;
}
