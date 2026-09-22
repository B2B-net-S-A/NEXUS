import { Suspense } from "react";
import { CandidatesWorkspace } from "@/components/v2/candidates/CandidatesWorkspace";

export default function CandidatesPage() {
  return (
    <Suspense>
      <CandidatesWorkspace />
    </Suspense>
  );
}
