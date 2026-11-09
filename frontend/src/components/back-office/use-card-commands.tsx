"use client";

import { useCallback, useState, type ReactNode } from "react";

import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCancelBonuses,
  useRefreshCard,
  useTakeCard,
  type BoCard,
  type BoCardDetail,
} from "@/lib/api/back-office";
import { useApproveBonuses } from "@/lib/api/hr-payroll";
import { useDecideTimesheet } from "@/lib/api/hr-time";

import { ReasonDialog } from "./ReasonDialog";

function conflictCode(error: unknown): string | null {
  const detail = (error as { response?: { data?: { detail?: { code?: string } } } })?.response?.data?.detail;
  return typeof detail === "object" && detail ? (detail.code ?? null) : null;
}

export interface CardCommands {
  take: (card: BoCard, options: { substitute: boolean }) => Promise<void>;
  runAction: (card: BoCard, action: string) => Promise<void>;
  /** Okna potwierdzeń i powodów: renderuj raz, obok listy kart. */
  dialogs: ReactNode;
  busy: boolean;
}

/**
 * „Biorę” i akcepty na karcie. Akcept woła istniejącą trasę z jej uprawnieniami
 * (raporty, premie, zmiany w zamówieniach), a potem przelicza karty tego rodzaju.
 */
export function useCardCommands(): CardCommands {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const takeCard = useTakeCard();
  const refresh = useRefreshCard();
  const decide = useDecideTimesheet();
  const approveBonuses = useApproveBonuses();
  const cancelBonuses = useCancelBonuses();
  const [returning, setReturning] = useState<BoCard | null>(null);
  const [cancelling, setCancelling] = useState<{ card: BoCard; ids: number[] } | null>(null);

  const fail = useCallback(
    (error: unknown, fallback: string) => showToast(apiErrorMessage(error, fallback), "error"),
    [showToast],
  );

  const take = useCallback(
    async (card: BoCard, { substitute }: { substitute: boolean }) => {
      const send = (overridePriority: boolean) =>
        takeCard.mutateAsync({
          id: card.id,
          substitute,
          override_priority: overridePriority,
          expected_updated_at: card.updated_at,
        });
      try {
        await send(false);
        showToast(substitute ? "Zastępujesz w tej sprawie" : "Karta jest Twoja", "success");
      } catch (error) {
        if (conflictCode(error) !== "priority") {
          fail(error, "Nie udało się wziąć karty.");
          return;
        }
        const ok = await askConfirm({
          title: "Ktoś ma pierwszeństwo",
          description: apiErrorMessage(error, "Pierwszeństwo ma inna osoba."),
          confirmLabel: "Biorę mimo to",
          cancelLabel: "Zostaw",
        });
        if (!ok) return;
        try {
          await send(true);
          showToast("Karta jest Twoja", "success");
        } catch (second) {
          fail(second, "Nie udało się wziąć karty.");
        }
      }
    },
    [askConfirm, fail, showToast, takeCard],
  );

  const bonusIds = useCallback(async (card: BoCard): Promise<number[]> => {
    const detail = (await api.get<BoCardDetail>(`/api/back-office/cards/${card.id}`)).data;
    return (detail.bonuses ?? []).map((row) => row.id);
  }, []);

  const runAction = useCallback(
    async (card: BoCard, action: string) => {
      try {
        if (action === "approve" && card.meta.timesheet_id) {
          await decide.mutateAsync({ id: card.meta.timesheet_id, decision: "approve" });
          showToast("Raport zaakceptowany", "success");
        } else if (action === "return") {
          setReturning(card);
          return;
        } else if (action === "mark_done" && card.meta.item_key) {
          await api.post("/api/finance/order-changes/checks", {
            year: card.meta.year,
            month: card.meta.month,
            item_key: card.meta.item_key,
            done: true,
          });
          showToast("Pozycja odhaczona", "success");
        } else if (action === "approve_all") {
          const ids = await bonusIds(card);
          const ok = await askConfirm({
            title: `Zatwierdzić premie: ${ids.length}?`,
            description: "Wszystko albo nic: pierwsza odmowa cofa całość i mówi, przy czyjej premii.",
            confirmLabel: "Zatwierdź wszystkie",
            cancelLabel: "Anuluj",
          });
          if (!ok) return;
          await approveBonuses.mutateAsync(ids);
          showToast("Premie zatwierdzone", "success");
        } else if (action === "cancel_all") {
          setCancelling({ card, ids: await bonusIds(card) });
          return;
        } else {
          return;
        }
        await refresh.mutateAsync({ id: card.id });
      } catch (error) {
        fail(error, "Nie udało się wykonać akcji.");
      }
    },
    [approveBonuses, askConfirm, bonusIds, decide, fail, refresh, showToast],
  );

  const dialogs = (
    <>
      {confirmDialog}
      {returning ? (
        <ReasonDialog
          title="Zwróć raport do poprawy"
          label="Co trzeba poprawić"
          confirmLabel="Zwróć"
          busy={decide.isPending}
          onCancel={() => setReturning(null)}
          onConfirm={async (note) => {
            try {
              await decide.mutateAsync({ id: returning.meta.timesheet_id ?? 0, decision: "return", note });
              await refresh.mutateAsync({ id: returning.id });
              showToast("Raport zwrócony", "success");
              setReturning(null);
            } catch (error) {
              fail(error, "Nie udało się zwrócić raportu.");
            }
          }}
        />
      ) : null}
      {cancelling ? (
        <ReasonDialog
          title={`Anuluj premie: ${cancelling.ids.length}`}
          label="Powód (opcjonalnie)"
          confirmLabel="Anuluj wszystkie"
          required={false}
          busy={cancelBonuses.isPending}
          onCancel={() => setCancelling(null)}
          onConfirm={async (note) => {
            try {
              await cancelBonuses.mutateAsync({ ids: cancelling.ids, note: note || null });
              await refresh.mutateAsync({ id: cancelling.card.id });
              showToast("Premie anulowane", "success");
              setCancelling(null);
            } catch (error) {
              fail(error, "Nie udało się anulować premii.");
            }
          }}
        />
      ) : null}
    </>
  );

  return {
    take,
    runAction,
    dialogs,
    busy: takeCard.isPending || decide.isPending || approveBonuses.isPending || cancelBonuses.isPending,
  };
}
