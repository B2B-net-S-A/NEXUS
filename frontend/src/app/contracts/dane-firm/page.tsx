"use client";

// Dane firm z umów — do potwierdzenia (E5a, decyzja Artura 22.11.2026).
// Propozycje danych firmy Partnera odczytane z podpisanej umowy, przed nową
// umową B2B dla kontraktorów. Reguła: docs/claude/kontrakty/dane-firm-z-umow-do-potwierdzenia.md.

import { PartnerReadsList } from "@/components/contracts/partner-reads/PartnerReadsList";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { RequirePermission } from "@/components/RequirePermission";

export default function PartnerDataPage() {
  return (
    // Lustro backendu: każda trasa stoi za „Kontrakty i zamówienia: tworzenie
    // i edycja” — bez niego jeden komunikat zamiast karty błędu 403.
    <RequirePermission
      permissions={["contracts_orders_edit"]}
      fallback={
        <QueryStateNotice
          state="forbidden"
          description="Dane firm z umów wymagają uprawnienia „Kontrakty i zamówienia: tworzenie i edycja”. Poproś administratora o dostęp."
        />
      }
    >
      <PartnerReadsList />
    </RequirePermission>
  );
}
