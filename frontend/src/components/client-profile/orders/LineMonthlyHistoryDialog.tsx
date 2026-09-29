"use client";

import { AppModal } from "@/components/ds";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";

import { LineConsumptionTable, useLineConsumptions } from "./LineConsumptionTable";

// Pomocniki tabeli żyją obok niej; eksport stąd zostaje dla dotychczasowych
// importów (karty zamówień, harnessy podglądu, testy).
export {
  CONSUMPTION_STATUS_LABEL,
  correctionText,
  formatPeriodMonthPl,
  lineConsumptionsQueryKey,
} from "./LineConsumptionTable";

interface Props {
  clientId: number;
  group: OrderGroupRead;
  line: OrderLineRead;
  /** Bez uprawnień do obsady dialog jest samym podglądem. */
  canEdit: boolean;
  open: boolean;
  onClose: () => void;
}

/**
 * „Zużycie MD" jednej osoby w oknie — cienka rama wokół
 * `LineConsumptionTable` (ta sama tabela stoi w panelu bocznym listy).
 * Numer zamówienia w opisie bierze z tego samego zapytania co tabela.
 */
export function LineMonthlyHistoryDialog({
  clientId,
  group,
  line,
  canEdit,
  open,
  onClose,
}: Props) {
  const rows = useLineConsumptions(clientId, group.id, line.id, open);

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      size="xl"
      title={`Zużycie MD — ${line.consultant_name}`}
      description={`Zamówienie nr ${rows.data?.order_number ?? group.order_number}`}
      footer={
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-muted"
        >
          Zamknij
        </button>
      }
    >
      <LineConsumptionTable
        clientId={clientId}
        group={group}
        line={line}
        canEdit={canEdit}
        enabled={open}
      />
    </AppModal>
  );
}
