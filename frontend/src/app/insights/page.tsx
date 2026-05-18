import { Suspense } from "react";
import { InsightsView } from "@/components/insights/InsightsView";

export default function InsightsPage() {
  return (
    <Suspense>
      <InsightsView />
    </Suspense>
  );
}
