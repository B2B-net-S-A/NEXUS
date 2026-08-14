"use client";

import { QueryStateNotice } from "@/components/ds";
import { RequireRole } from "@/components/RequireRole";
import { MdImportWorkspace } from "@/components/finance/MdImportWorkspace";

/**
 * Moduł Finanse — import miesięcznego zużycia MD.
 *
 * Role lustrzane wobec backendowego ``FinanceManageUser`` (capability
 * `manage_finance`): admin oraz rola Finanse. Middleware zawęża trasę
 * niezależnie od tej bramki — to defense in depth, nie jedyna kontrola.
 */
export default function FinancePage() {
  return (
    <RequireRole
      roles={["admin", "finance"]}
      fallback={
        <QueryStateNotice
          state="forbidden"
          description="Import zużycia MD wymaga uprawnień finansowych. Poproś administratora o dostęp."
        />
      }
    >
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-6">
        <header>
          <h1 className="text-xl font-semibold text-foreground">Finanse</h1>
          <p className="text-sm text-muted-foreground">
            Miesięczne raporty zużycia MD zasilające budżety zamówień klientów.
          </p>
        </header>
        <MdImportWorkspace />
      </div>
    </RequireRole>
  );
}
