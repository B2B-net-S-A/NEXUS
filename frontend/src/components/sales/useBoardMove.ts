"use client";

import { useCallback, useState } from "react";

import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { useMoveOpportunity, type Opportunity, type Stage } from "@/lib/api/sales";

import { canUndoMove } from "./step";

interface UseBoardMoveArgs {
  stages: readonly Stage[];
  refetch: () => Promise<unknown>;
}

interface BoardMove {
  /** Etap szansy z uwzględnieniem ruchu, który właśnie się zapisuje. */
  stageOf: (item: Opportunity) => number;
  moveToStage: (item: Opportunity, target: Stage) => Promise<void>;
}

/** Karta od razu stoi w nowej kolumnie; po błędzie wraca, a komunikat mówi dlaczego. */
export function useBoardMove({ stages, refetch }: UseBoardMoveArgs): BoardMove {
  const move = useMoveOpportunity();
  const { showError, showSuccess, showActionToast } = useToast();
  const [pending, setPending] = useState<Readonly<Record<number, number>>>({});

  const stageOf = useCallback(
    (item: Opportunity) => pending[item.id] ?? item.stage.id,
    [pending],
  );

  const send = useCallback(
    async (itemId: number, stageId: number): Promise<boolean> => {
      setPending((current) => ({ ...current, [itemId]: stageId }));
      try {
        await move.mutateAsync({ id: itemId, stage_id: stageId });
        await refetch();
        return true;
      } catch (error) {
        showError(apiErrorMessage(error, "Nie udało się przenieść szansy."));
        return false;
      } finally {
        setPending(({ [itemId]: _done, ...rest }) => rest);
      }
    },
    [move, refetch, showError],
  );

  const moveToStage = useCallback(
    async (item: Opportunity, target: Stage) => {
      const from = item.stage.id;
      if (target.id === from) return;
      if (!(await send(item.id, target.id))) return;
      const message = `Szansa jest teraz na etapie „${target.name}”.`;
      if (!canUndoMove(item.stage, target, stages)) {
        showSuccess(message);
        return;
      }
      showActionToast(message, {
        actionLabel: "Cofnij",
        onAction: async () => {
          await send(item.id, from);
        },
      });
    },
    [send, showActionToast, showSuccess, stages],
  );

  return { stageOf, moveToStage };
}
