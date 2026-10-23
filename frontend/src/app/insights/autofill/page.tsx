import { Suspense } from "react";
import { AutofillQualityView } from "@/components/insights/AutofillQualityView";

/** „Jakość podpowiedzi systemu” — silnik „Nowi na 20” (23.10.2026). */
export default function AutofillQualityPage() {
  return (
    <Suspense>
      <AutofillQualityView />
    </Suspense>
  );
}
