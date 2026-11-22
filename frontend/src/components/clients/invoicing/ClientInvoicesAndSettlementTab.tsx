"use client";

import { useState } from "react";

import { DeliverySettlementsSection } from "@/components/finance/settlements/DeliverySettlementsSection";

import { ClientInvoicingTab } from "./ClientInvoicingTab";
import { defaultPeriod } from "./invoicing-format";

/**
 * „Umowa i pieniądze › Faktury i rozliczenie”: jeden miesiąc dla całej zakładki.
 * Do 20.11.2026 sekcja marży i tabela faktur miały osobne strzałki, więc po
 * przejściu tabeli na wrzesień sekcja nad nią pokazywała dalej październik.
 * Klucze zapytań zostają (`settlementKeys.delivery`, `invoicingKeys.client`):
 * karta „Rozliczenie” w Przeglądzie czyta te same na domyślnym miesiącu.
 */
export function ClientInvoicesAndSettlementTab({
  clientId,
  initialPeriod,
}: {
  clientId: number;
  initialPeriod?: string;
}) {
  const [period, setPeriod] = useState(() => initialPeriod ?? defaultPeriod());
  return (
    <ClientInvoicingTab clientId={clientId} period={period} onPeriodChange={setPeriod}>
      {/* Najpierw rozliczenie z marżą: tu DL daje zgodę na koszty integracji,
          a tabela faktur pod spodem ma kilkadziesiąt wierszy. */}
      <DeliverySettlementsSection clientId={clientId} month={period} />
    </ClientInvoicingTab>
  );
}
