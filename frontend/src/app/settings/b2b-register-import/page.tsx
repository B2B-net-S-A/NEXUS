"use client";

import { RequireRole } from "@/components/RequireRole";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { B2BRegisterImportPanel } from "@/components/settings/B2BRegisterImportPanel";

export default function B2BRegisterImportPage() {
  // API importu jest `AdminUser` — ta bramka tylko chowa ekran.
  return (
    <RequireRole
      roles={["admin"]}
      fallback={
        <QueryStateNotice
          state="forbidden"
          description="Import rejestru umów z Excela prowadzi administrator."
        />
      }
    >
      <div className="mx-auto flex max-w-7xl flex-col gap-4">
        <h1 className="text-xl font-semibold">Rejestr umów z Excela</h1>
        <B2BRegisterImportPanel />
      </div>
    </RequireRole>
  );
}
