"use client";

import { useEffect, useState } from "react";
import { CVGeneratorStandaloneV2 } from "@/components/v2/pages/CVGeneratorStandaloneV2";

/**
 * Standalone CV Generator — 1:1 port of artur-t-96/CV-Generator wrapped around
 * NEXUS data (consultant + recruitment process pickers replace file uploads).
 */
export default function CVGeneratorPage() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Ładowanie generatora CV…
      </div>
    );
  }
  return <CVGeneratorStandaloneV2 />;
}
