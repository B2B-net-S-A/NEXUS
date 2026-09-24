"use client";

import { useQueries } from "@tanstack/react-query";
import { AlertTriangle, Loader2, ShieldAlert } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { apiErrorMessage } from "@/lib/api-error";
import { dlPortalApi, type OrderDeletePreview } from "@/lib/api/dlPortal";
import {
  orderDeleteBlocked,
  orderDeleteConsequences,
  type OrderDeleteConsequence,
} from "@/lib/order-delete-consequences";

export interface DeleteOrderGroupLine {
  id: number;
  consultant_name: string;
}

interface DeleteOrderGroupDialogProps {
  clientId: number;
  orderNumber: string;
  lines: DeleteOrderGroupLine[];
  hasFile: boolean;
  pending?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

/**
 * Potwierdzenie usunięcia CAŁEGO zamówienia MD/kosztowego (audyt 22.09 r2,
 * FE-N02).
 *
 * Zastępuje `window.confirm`, który mówił wyłącznie „nie można cofnąć” — a
 * usunięcie każdej linii zabiera przez CASCADE jej krok stawki klienta
 * i potrafi zostawić kontrakt bez przychodu. Skutki liczy serwer dla każdej
 * linii osobno (`delete-preview?context=group_line`, wyłącznie odczyt), bo
 * trasa kasowania grupy usuwa linie tą samą funkcją co kosz pojedynczej linii.
 */
export function DeleteOrderGroupDialog({
  clientId,
  orderNumber,
  lines,
  hasFile,
  pending = false,
  onConfirm,
  onClose,
}: DeleteOrderGroupDialogProps) {
  const previews = useQueries({
    queries: lines.map((line) => ({
      queryKey: ["order-delete-preview", clientId, line.id, "group_line"],
      queryFn: () =>
        dlPortalApi
          .previewOrderDeletion(clientId, line.id, "group_line")
          .then((r) => r.data as OrderDeletePreview),
      staleTime: 0,
    })),
  });

  const failed = previews.find((q) => q.isError);
  const allLoaded = previews.every((q) => q.isSuccess);
  const blocked = previews.some(
    (q) => q.data !== undefined && orderDeleteBlocked(q.data),
  );
  const consequences: OrderDeleteConsequence[] = [];
  previews.forEach((q, index) => {
    if (!q.data) return;
    for (const item of orderDeleteConsequences(q.data)) {
      consequences.push({
        tone: item.tone,
        text: `${lines[index].consultant_name}: ${item.text}`,
      });
    }
  });
  if (hasFile) {
    consequences.push({
      tone: "info",
      text: "Dokument PDF zamówienia zostanie skasowany.",
    });
  }
  const redacted = previews.some((q) => q.data?.amounts_redacted);
  // Dopóki nie znamy skutków dla KAŻDEJ linii, nie pozwalamy usunąć.
  const canDelete = allLoaded && !blocked && !pending;

  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={`Usunąć całe zamówienie nr ${orderNumber}?`}
      size="md"
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm border border-border rounded hover:bg-muted"
          >
            Anuluj
          </button>
          <button
            type="button"
            disabled={!canDelete}
            onClick={onConfirm}
            className="inline-flex items-center gap-2 px-3 py-1.5 text-sm rounded bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
          >
            {pending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
            Usuń zamówienie
          </button>
        </>
      }
    >
      <p className="mb-3 text-sm text-muted-foreground">
        {`Zamówienie zostanie usunięte razem ze wszystkimi konsultantami (${lines.length}). Tej operacji nie można cofnąć.`}
      </p>
      {failed ? (
        <p role="alert" className="text-sm text-destructive">
          Nie udało się sprawdzić skutków usunięcia:{" "}
          {apiErrorMessage(failed.error, "nieznany błąd")}. Bez tego nie usuwamy
          — spróbuj ponownie.
        </p>
      ) : !allLoaded ? (
        // `!allLoaded` (każde `isSuccess`), nie `isLoading`: zapytanie
        // wstrzymane pisało „bez zmian", zanim cokolwiek było wiadomo (N4).
        <p className="text-sm text-muted-foreground">Sprawdzam skutki…</p>
      ) : consequences.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Umowy konsultantów i ich pozostałe zamówienia zostają bez zmian.
        </p>
      ) : (
        <ul className="space-y-2 text-sm">
          {consequences.map((item, index) => (
            <li key={index} className="flex items-start gap-2">
              {item.tone === "blocked" ? (
                <ShieldAlert
                  className="mt-0.5 w-4 h-4 shrink-0 text-destructive"
                  aria-hidden="true"
                />
              ) : item.tone === "warning" ? (
                <AlertTriangle
                  className="mt-0.5 w-4 h-4 shrink-0 text-amber-500"
                  aria-hidden="true"
                />
              ) : (
                <span
                  className="mt-1.5 w-1.5 h-1.5 shrink-0 rounded-full bg-muted-foreground"
                  aria-hidden="true"
                />
              )}
              <span>{item.text}</span>
            </li>
          ))}
        </ul>
      )}
      {redacted ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Kwoty ukryte — nie masz dostępu do finansów tego klienta.
        </p>
      ) : null}
    </AppModal>
  );
}
