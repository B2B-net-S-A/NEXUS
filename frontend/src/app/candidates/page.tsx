import { Suspense } from "react";
import { CandidatesListV2 } from "@/components/v2/pages/CandidatesListV2";

export default function CandidatesPage() {
  return (
    <Suspense>
      <CandidatesListV2 />
    </Suspense>
  );
}
