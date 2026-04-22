"use client";

import { useEffect, useState } from "react";
import { ContractorsListV2 } from "@/components/v2/pages/ContractorsListV2";

/**
 * Client-only gate — same pattern as /contracts/page.tsx. Next.js 15 +
 * React 19 streaming SSR hangs hydrating useQuery-driven lists on the
 * initial skeleton; forcing the first render to wait until after
 * useEffect sidesteps the SSR boundary.
 */
export default function ContractorsPage() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted) {
    return (
      <div className="p-8 text-sm text-[hsl(var(--text-muted))]">
        Ładowanie kontraktorów…
      </div>
    );
  }
  return <ContractorsListV2 />;
}
