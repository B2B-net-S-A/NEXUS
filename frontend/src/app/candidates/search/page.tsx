import { Suspense } from "react";
import { CandidateSearchView } from "@/components/v2/pages/CandidateSearchView";

export const metadata = {
  title: "Wyszukiwanie kandydatów – NEXUS",
};

export default function CandidatesSearchPage() {
  return (
    <Suspense>
      <CandidateSearchView backHref="/candidates" />
    </Suspense>
  );
}
