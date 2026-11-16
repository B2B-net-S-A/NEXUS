"use client";

import { useParams } from "next/navigation";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { RequirePermission } from "@/components/RequirePermission";
import { IssuedInvoiceCardView } from "@/components/clients/invoicing/issue/IssuedInvoiceCardView";

/**
 * /finance/faktury/[id] — karta faktury sprzedaży wystawianej w NEXUSIE (E4, M5).
 * Lista szkiców i wysłanych jest w Finanse → Faktury do klientów; tu jedna
 * faktura od szkicu do przyjęcia w KSeF. `RequirePermission` to warstwa UX,
 * bramką jest API („Moduł Finanse”).
 */
export default function IssuedInvoicePage() {
  const params = useParams<{ id: string }>();
  const id = Number(params?.id);

  return (
    <RequirePermission
      permissions={["finance_module"]}
      fallback={
        <QueryStateNotice
          state="forbidden"
          description="Wystawianie faktur wymaga uprawnienia „Moduł Finanse”. Poproś administratora o dostęp."
        />
      }
    >
      <div className="space-y-3">
        <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="font-display text-xl font-semibold leading-tight tracking-tight">
            Faktura sprzedaży
          </h1>
          <a href="/finance?view=sales-invoices" className="text-[13px] text-primary hover:underline">
            ← Faktury do klientów
          </a>
        </header>
        {Number.isFinite(id) && id > 0 ? (
          <IssuedInvoiceCardView invoiceId={id} />
        ) : (
          <QueryStateNotice state="not_found" />
        )}
      </div>
    </RequirePermission>
  );
}
