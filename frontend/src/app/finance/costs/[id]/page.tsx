"use client";

import { useParams } from "next/navigation";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { RequirePermission } from "@/components/RequirePermission";
import { CostCard } from "@/components/finance/ledger/CostCard";

// Finanse → Koszty → karta faktury kosztowej (makieta M2, bez dekretu).
// Bramka: uprawnienie „Moduł Finanse” i moduł „Księgowość” (API daje 404,
// gdy moduł wyłączony — karta pokazuje wtedy „nie znaleziono”).
export default function CostCardPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params?.id);
  return (
    <RequirePermission
      permissions={["finance_module"]}
      fallback={
        <QueryStateNotice
          state="forbidden"
          description="Karta faktury wymaga uprawnienia do Modułu Finanse."
        />
      }
    >
      {Number.isInteger(id) && id > 0 ? (
        <CostCard id={id} />
      ) : (
        <QueryStateNotice state="not_found" />
      )}
    </RequirePermission>
  );
}
