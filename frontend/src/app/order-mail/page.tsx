"use client";

import { Suspense } from "react";
import { OrderMailQueue } from "@/components/order-mail/OrderMailQueue";

/**
 * Dostęp: admin, finance oraz delivery_lead (wszyscy klienci) — zakres
 * wylicza BACKEND (`_visible_client_ids`), a
 * middleware pilnuje wejścia z paska adresu. „Zastosuj" jest osobno bramkowane
 * (`can_apply`): TCM widzi kolejkę bez przycisku.
 */
export default function OrderMailPage() {
  return (
    <Suspense fallback={<div className="p-6 text-muted-foreground">Ładowanie…</div>}>
      <OrderMailQueue />
    </Suspense>
  );
}
