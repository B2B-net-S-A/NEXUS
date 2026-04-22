"use client";

import { useEffect, useState } from "react";
import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";

/**
 * Client-only gate: Next.js 15 + React 19 streaming SSR wieszało hydrację
 * ContractsListV2 na skeleton. `mounted` flag forsuje pierwszy render
 * dopiero po useEffect, co pomija SSR boundary i odblokowuje useQuery.
 * Ten sam pattern potrzebny też dla /jobs i /clients.
 */
export default function ContractsPage() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted) {
    return <div className="p-8 text-sm text-[hsl(var(--text-muted))]">Ładowanie kontraktów…</div>;
  }
  return <ContractsListV2 />;
}
