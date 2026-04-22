import { Suspense } from "react";
import { JobsListV2 } from "@/components/v2/pages/JobsListV2";

export default function JobsPage() {
  return (
    <Suspense>
      <JobsListV2 />
    </Suspense>
  );
}
