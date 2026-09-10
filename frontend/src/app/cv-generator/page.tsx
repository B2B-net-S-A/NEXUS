"use client";

import dynamic from "next/dynamic";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

/**
 * Standalone CV Generator — dynamic import with ssr:false eliminates the
 * "no available server" hydration error from Next 15 App Router. The
 * CVGeneratorStandaloneV2 component depends on browser-only APIs (TanStack
 * Query devtools, blob downloads) and shouldn't be SSR'd anyway.
 *
 * Per-route loading.tsx and error.tsx handle the suspense + crash states.
 */
const CVGeneratorStandaloneV2 = dynamic(
  () =>
    import("@/components/v2/pages/CVGeneratorStandaloneV2").then(
      (mod) => mod.CVGeneratorStandaloneV2,
    ),
  {
    ssr: false,
    loading: () => (
      <div className="p-8 text-sm text-muted-foreground">
        Ładowanie generatora CV…
      </div>
    ),
  },
);

function ContextualGenerator() {
  const params = useSearchParams();
  const positiveId = (value: string | null) => {
    if (!value || !/^[1-9]\d*$/.test(value)) return undefined;
    const id = Number(value);
    return Number.isSafeInteger(id) ? id : undefined;
  };
  const candidateId = positiveId(params.get("candidate_id"));
  return <CVGeneratorStandaloneV2 prefillCandidateId={candidateId}
    prefillJobId={candidateId ? positiveId(params.get("job_id")) : undefined} />;
}

export default function CVGeneratorPage() {
  return <Suspense fallback={<div className="p-8">Ładowanie generatora CV…</div>}>
    <ContextualGenerator />
  </Suspense>;
}
