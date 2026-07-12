import { Suspense } from "react";
import { CortexView } from "@/components/cortex/CortexView";

export default function CortexPage() {
  return (
    <Suspense>
      <CortexView />
    </Suspense>
  );
}
