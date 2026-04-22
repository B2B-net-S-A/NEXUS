import { Suspense } from "react";
import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";

export default function ContractsPage() {
  return (
    <Suspense>
      <ContractsListV2 />
    </Suspense>
  );
}
