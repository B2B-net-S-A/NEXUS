"use client";

import dynamic from "next/dynamic";

/**
 * Standalone CV Generator – dynamic import with ssr:false eliminates the
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

export default function CVGeneratorPage() {
  return <CVGeneratorStandaloneV2 />;
}
