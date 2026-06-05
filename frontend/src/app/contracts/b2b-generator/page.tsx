"use client";

import { useEffect, useState } from "react";
import { B2BContractGeneratorV2 } from "@/components/v2/pages/B2BContractGeneratorV2";

/**
 * Client-only gate (wzorzec jak /contracts) — Next.js 15 + React 19 streaming
 * SSR wieszał hydrację komponentów z useQuery na skeletonie.
 */
export default function B2BGeneratorPage() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Ładowanie generatora…
      </div>
    );
  }
  return <B2BContractGeneratorV2 />;
}
