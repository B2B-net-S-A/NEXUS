"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Loader2, ShieldAlert } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { apiErrorMessage } from "@/lib/api-error";
import { dlPortalApi, type OrderDeletePreview } from "@/lib/api/dlPortal";
import {
  NO_SIDE_EFFECTS_TEXT,
  orderDeleteBlocked,
  orderDeleteConsequences,
} from "@/lib/order-delete-consequences";

interface DeleteOrderDialogProps {
  clientId: number;
  orderId: number;
  title: string;
  pending?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

/**
 * Potwierdzenie usunięcia zamówienia, które mówi PRAWDĘ.
 *
 * Zastępuje natywne `window.confirm` z obietnicą „umowa tej osoby nie zmieni
 * się” — nieprawdziwą, bo kasowanie zabiera przez CASCADE krok stawki klienta
 * i przecenia miesiące historyczne (audyt 18.09.2026). Przy okazji znika
 * natywny dialog, który ZAMRAŻA automatyzację przeglądarki i uniemożliwiał
 * testowanie tej ścieżki przez interfejs.
 *
 * Skutki liczy serwer (`GET …/delete-preview`, wyłącznie odczyt) — front nie
 * zgaduje, bo reguła wyboru stawki zastępczej żyje w modelu kontraktu.
 */
export function DeleteOrderDialog({
  clientId,
  orderId,
  title,
  pending = false,
  onConfirm,
  onClose,
}: DeleteOrderDialogProps) {
  const previewQuery = useQuery<OrderDeletePreview>({
    queryKey: ["order-delete-preview", clientId, orderId],
    queryFn: () =>
      dlPortalApi.previewOrderDeletion(clientId, orderId).then((r) => r.data),
    // Skutki mają być świeże w chwili pytania, nie z poprzedniego otwarcia.
    staleTime: 0,
  });

  const preview = previewQuery.data;
  const consequences = preview ? orderDeleteConsequences(preview) : [];
  const blocked = preview ? orderDeleteBlocked(preview) : false;
  // Dopóki nie wiemy, co się stanie, nie pozwalamy usunąć: „nie wiem” nie jest
  // tym samym co „nic się nie zmieni”, a to drugie właśnie naprawiamy.
  const canDelete = previewQuery.isSuccess && !blocked && !pending;

  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={`Usunąć zamówienie „${title}”?`}
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
      {previewQuery.isLoading ? (
        <p className="text-sm text-muted-foreground">Sprawdzam skutki…</p>
      ) : previewQuery.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Nie udało się sprawdzić skutków usunięcia:{" "}
          {apiErrorMessage(previewQuery.error, "nieznany błąd")}. Bez tego nie
          usuwamy — spróbuj ponownie.
        </p>
      ) : consequences.length === 0 ? (
        <p className="text-sm text-muted-foreground">{NO_SIDE_EFFECTS_TEXT}</p>
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
      {preview?.amounts_redacted ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Kwoty ukryte — nie masz dostępu do finansów tego klienta.
        </p>
      ) : null}
    </AppModal>
  );
}
