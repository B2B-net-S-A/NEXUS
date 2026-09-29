"use client";

import { RequireRole } from "@/components/RequireRole";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { ContractDocsSharePointPanel } from "@/components/settings/ContractDocsSharePointPanel";

export default function ContractDocsSharePointPage() {
  // API jest `AdminUser` — ta bramka tylko chowa ekran.
  return (
    <RequireRole
      roles={["admin"]}
      fallback={
        <QueryStateNotice
          state="forbidden"
          description="Pobieranie dokumentów kontraktów z SharePointa prowadzi administrator."
        />
      }
    >
      <div className="mx-auto flex max-w-7xl flex-col gap-4">
        <h1 className="text-xl font-semibold">Dokumenty kontraktów z SharePointa</h1>
        <ContractDocsSharePointPanel />
      </div>
    </RequireRole>
  );
}
