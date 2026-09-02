"use client";

import { Suspense } from "react";
import { OrderMailQueue } from "@/components/order-mail/OrderMailQueue";

/**
 * Dostęp: admin, head_of_recruitment, finance (cała firma) oraz delivery_lead
 * (własny portfel) — zakres wylicza BACKEND (`_visible_client_ids`), a
 * middleware pilnuje wejścia z paska adresu. „Zastosuj" jest osobno bramkowane
 * (`can_apply`): HoR widzi kolejkę bez przycisku.
 */
export default function OrderMailPage() {
  return (
    <Suspense fallback={<div className="p-6 text-muted-foreground">Ładowanie…</div>}>
      <OrderMailQueue />
    </Suspense>
  );
}
