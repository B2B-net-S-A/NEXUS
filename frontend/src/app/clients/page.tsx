import { Suspense } from "react";
import { ClientsListV2 } from "@/components/v2/pages/ClientsListV2";

export default function ClientsPage() {
  return (
    <Suspense>
      <ClientsListV2 />
    </Suspense>
  );
}
