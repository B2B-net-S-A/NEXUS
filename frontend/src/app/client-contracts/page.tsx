"use client";

import { ClientContractsView } from "@/components/client-contracts/ClientContractsView";
import { RequirePermission } from "@/components/RequirePermission";
import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";

// Lustro `ClientContractsViewUser` w API. Ekran nie ma sekcji produktu, więc
// middleware go nie zamyka i o dostępie decyduje samo uprawnienie.
export default function ClientContractsPage() {
  return (
    <RequirePermission
      permissions={["client_contracts_view"]}
      fallback={
        <QueryStateNotice
          state="forbidden"
          description="Umowy klientów wymagają uprawnienia „Umowy klientów: lista i pliki”. Poproś administratora o dostęp."
        />
      }
    >
      <div className="mx-auto max-w-6xl space-y-4 p-4 md:p-6">
        <PageHeader
          title="Umowy klientów"
          description="Umowy ramowe i aneksy z plikami do pobrania."
          density="compact"
        />
        <ClientContractsView />
      </div>
    </RequirePermission>
  );
}
