"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { useDeleteItem, useEquipmentItem, type EquipmentItem } from "@/lib/api/equipment";
import { resolveViewState } from "@/lib/view-state";
import { formatIsoDatePl } from "@/lib/date-pl";

import {
  CATEGORY_LABELS,
  CONDITION_LABELS,
  HOLDER_KIND_LABELS,
  ITEM_STATUS_LABELS,
  ITEM_STATUS_TONE,
  formatPln,
  itemIdentifier,
  itemNumber,
  secretHint,
} from "./equipment-format";
import { ItemFormDialog } from "./ItemFormDialog";

interface ItemDetailDialogProps {
  itemId: number;
  onClose: () => void;
  onOpenProtocol?: (protocolId: number) => void;
}

/** Szczegół egzemplarza: dane, posiadacz i historia wydań z numerami protokołów. */
export function ItemDetailDialog({ itemId, onClose, onOpenProtocol }: ItemDetailDialogProps) {
  const { showToast } = useToast();
  const detail = useEquipmentItem(itemId);
  const remove = useDeleteItem();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [editing, setEditing] = useState(false);
  const state = resolveViewState({
    isLoading: detail.isLoading,
    error: detail.error,
    isSuccess: detail.isSuccess,
  });
  const item = detail.data;

  const onDelete = async () => {
    if (!item) return;
    const ok = await askConfirm({
      title: "Usunąć pozycję z rejestru?",
      description:
        "Usunąć można tylko pozycję bez historii wydań. Sprzęt z historią oznacz jako wycofany.",
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(item.id, {
      onSuccess: () => {
        showToast("Pozycja usunięta", "success");
        onClose();
      },
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się usunąć pozycji."), "error"),
    });
  };

  return (
    <>
      <AppModal
        open
        onOpenChange={(next) => {
          if (!next) onClose();
        }}
        title={
          item ? `${CATEGORY_LABELS[item.category]} ${item.model.name}` : "Pozycja sprzętu"
        }
        description={item ? `Nr ${itemNumber(item)} · ${itemIdentifier(item)}` : undefined}
        size="lg"
        footer={
          item ? (
            <>
              <Button variant="quiet" onClick={onDelete} disabled={remove.isPending}>
                Usuń
              </Button>
              <Button variant="outline" onClick={() => setEditing(true)}>
                Edytuj
              </Button>
              <Button onClick={onClose}>Zamknij</Button>
            </>
          ) : null
        }
      >
        {state === "loading" ? (
          <p className="text-sm text-muted-foreground">Wczytywanie…</p>
        ) : state !== "ready" || !item ? (
          <QueryStateNotice
            state={state === "forbidden" || state === "not_found" ? state : "error"}
            onRetry={() => detail.refetch()}
          />
        ) : (
          <div className="space-y-4 text-sm">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
              <div>
                <dt className="text-xs text-muted-foreground">Stan</dt>
                <dd>
                  <StatusDot tone={ITEM_STATUS_TONE[item.status]}>
                    {ITEM_STATUS_LABELS[item.status]}
                  </StatusDot>
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">U kogo</dt>
                <dd>
                  {item.holder ? (
                    <>
                      {item.holder.name}
                      <span className="block text-xs text-muted-foreground">
                        {HOLDER_KIND_LABELS[item.holder.kind]}
                        {item.holder.client_name ? ` · ${item.holder.client_name}` : ""}
                      </span>
                    </>
                  ) : (
                    item.location ?? "—"
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Wartość z cennika</dt>
                <dd>{formatPln(item.model.price_pln)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Właściciel</dt>
                <dd>{item.ownership === "nasz" ? "Nasz" : "Klienta"}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Data zakupu</dt>
                <dd>{formatIsoDatePl(item.purchase_date)}</dd>
              </div>
              {item.notes ? (
                <div className="col-span-2 sm:col-span-3">
                  <dt className="text-xs text-muted-foreground">Notatka</dt>
                  <dd className="whitespace-pre-wrap">{item.notes}</dd>
                </div>
              ) : null}
            </dl>
            <SecretHintNote category={item.category} />
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Historia wydań
              </h3>
              {item.history.length === 0 ? (
                <p className="text-muted-foreground">Ta pozycja nie była jeszcze wydana.</p>
              ) : (
                <ol className="divide-y divide-border rounded-md border border-border">
                  {item.history.map((row) => (
                    <li key={row.assignment_id} className="flex flex-wrap items-baseline gap-x-3 px-3 py-2">
                      <span className="font-medium">{row.holder.name}</span>
                      <span className="text-xs text-muted-foreground">
                        {formatIsoDatePl(row.issued_at)} – {row.returned_at ? formatIsoDatePl(row.returned_at) : "teraz"}
                        {row.return_condition ? ` · ${CONDITION_LABELS[row.return_condition]}` : ""}
                      </span>
                      <span className="ml-auto flex gap-2 text-xs">
                        {row.issue_protocol && row.issue_protocol_id ? (
                          <button
                            type="button"
                            className="text-primary hover:underline"
                            onClick={() => onOpenProtocol?.(row.issue_protocol_id as number)}
                          >
                            {row.issue_protocol}
                          </button>
                        ) : (
                          <span className="text-muted-foreground">z importu</span>
                        )}
                        {row.return_protocol && row.return_protocol_id ? (
                          <button
                            type="button"
                            className="text-primary hover:underline"
                            onClick={() => onOpenProtocol?.(row.return_protocol_id as number)}
                          >
                            {row.return_protocol}
                          </button>
                        ) : null}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>
        )}
      </AppModal>
      {editing && item ? (
        <ItemFormDialog key={item.id} open item={item} onOpenChange={setEditing} />
      ) : null}
      {confirmDialog}
    </>
  );
}

function SecretHintNote({ category }: { category: EquipmentItem["category"] }) {
  const hint = secretHint(category);
  if (!hint) return null;
  return (
    <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
      <span className="font-medium text-foreground">{hint.label}:</span> NEXUS go nie
      przechowuje. {hint.text}
      {hint.href ? (
        <>
          {" "}
          <a
            href={hint.href}
            target="_blank"
            rel="noreferrer"
            className="text-primary hover:underline"
          >
            Otwórz Intune
          </a>
        </>
      ) : null}
    </p>
  );
}
