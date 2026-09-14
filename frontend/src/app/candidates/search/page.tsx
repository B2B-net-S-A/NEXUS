import { Suspense } from "react";
import { CandidateSearchView } from "@/components/v2/pages/CandidateSearchView";

export const metadata = {
  title: "Wyszukiwanie kandydatów — NEXUS",
};

export default function CandidatesSearchPage() {
  return (
    <Suspense>
      {/* syncUrl: filtry i strona w `?s=` — Wstecz z profilu wraca na to samo
          wyszukiwanie zamiast na pustą wyszukiwarkę (UAT B29). */}
      <CandidateSearchView backHref="/candidates" syncUrl />
    </Suspense>
  );
}
