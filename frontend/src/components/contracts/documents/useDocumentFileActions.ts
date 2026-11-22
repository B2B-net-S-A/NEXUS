"use client";

import { useState } from "react";

import { downloadContractDocument, openContractDocument } from "@/lib/contract-documents";
import { downloadOrderDocument, openOrderDocument } from "@/lib/order-documents";

import type { DocItem } from "./document-groups";

/**
 * Podgląd i pobranie pliku z wiersza albo karty „Obowiązuje teraz”. Plik
 * kontraktu idzie trasą dokumentów kontraktu, PDF z zakładki Zamówienia —
 * trasą pliku zamówienia. Podgląd otwiera kartę synchronicznie w geście
 * kliknięcia (blokada wyskakujących okien), więc nie odkładaj go w czasie.
 */
export function useDocumentFileActions(contractId: number, onError: (message: string) => void) {
  const [busy, setBusy] = useState(false);

  const run = async (action: () => Promise<void>, failure: string) => {
    setBusy(true);
    try {
      await action();
    } catch {
      onError(failure);
    } finally {
      setBusy(false);
    }
  };

  const open = (item: DocItem) =>
    run(
      () =>
        item.row.kind === "doc"
          ? openContractDocument(contractId, item.row.doc)
          : openOrderDocument(item.row.order),
      `Nie udało się otworzyć pliku „${item.name}”.`,
    );

  const download = (item: DocItem) =>
    run(
      () =>
        item.row.kind === "doc"
          ? downloadContractDocument(contractId, item.row.doc)
          : downloadOrderDocument(item.row.order),
      `Nie udało się pobrać pliku „${item.name}”.`,
    );

  return { busy, open, download };
}
