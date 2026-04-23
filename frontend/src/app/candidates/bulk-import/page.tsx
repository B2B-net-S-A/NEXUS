import { Suspense } from "react";
import { BulkImportCVsV2 } from "@/components/v2/pages/BulkImportCVsV2";

export default function BulkImportCVsPage() {
  return (
    <Suspense>
      <BulkImportCVsV2 />
    </Suspense>
  );
}
