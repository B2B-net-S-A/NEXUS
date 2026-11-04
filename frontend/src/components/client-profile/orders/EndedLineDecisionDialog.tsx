"use client";

import { AppModal } from "@/components/ds";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";
import {
  decisionLabel,
  endedUsage,
  hasPendingPoolDecision,
} from "@/lib/order-ended-line";
import { lineHasSettlements } from "@/lib/order-line-usage";
import { formatDate } from "@/types/client-profile";

import { formatMd } from "./MdBudgetBar";

const SETTLED_HINT =
  "Niedostępne — osoba ma rozliczenia (MD lub faktury), które zniknęłyby razem z nią.";

interface Props {
  group: OrderGroupRead | null;
  line: OrderLineRead | null;
  onClose: () => void;
  canManage: boolean;
  canManageLifecycle: boolean;
  onKeepHistory?: (group: OrderGroupRead, line: OrderLineRead) => void;
  onReplaceLine?: (group: OrderGroupRead, line: OrderLineRead) => void;
  onDeleteLine: (group: OrderGroupRead, line: OrderLineRead) => void;
  onResolveOffboarding: (group: OrderGroupRead, line: OrderLineRead) => void;
}

interface OptionProps {
  title: string;
  description: string;
  onSelect: () => void;
  disabled?: boolean;
  disabledReason?: string;
  destructive?: boolean;
}

function DecisionOption({
  title,
  description,
  onSelect,
  disabled = false,
  disabledReason,
  destructive = false,
}: OptionProps) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        disabled={disabled}
        className={
          destructive
            ? "w-full rounded-lg border border-destructive/40 px-3 py-2.5 text-left transition-colors hover:bg-destructive/5 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
            : "w-full rounded-lg border border-border px-3 py-2.5 text-left transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
        }
      >
        <span
          className={
            destructive
              ? "block text-sm font-medium text-destructive"
              : "block text-sm font-medium text-foreground"
          }
        >
          {title}
        </span>
        <span className="mt-0.5 block text-xs text-muted-foreground">
          {disabled && disabledReason ? disabledReason : description}
        </span>
      </button>
    </li>
  );
}

/** Jedno okno decyzji o osobie z sekcji „Zakończone" (ticket 6, 09.2026).
 *
 *  Czekająca sprawa puli MD ma swój formularz (`OffboardingDecisionModal`) —
 *  tu jest jedyną opcją, bo serwer odmawia „zostaw jako historię" do czasu jej
 *  rozstrzygnięcia, a rozstrzygnięcie jest decyzją także o osobie. */
export function EndedLineDecisionDialog({
  group,
  line,
  onClose,
  canManage,
  canManageLifecycle,
  onKeepHistory,
  onReplaceLine,
  onDeleteLine,
  onResolveOffboarding,
}: Props) {
  const open = group !== null && line !== null;
  const pendingPool = line ? hasPendingPoolDecision(line) : false;
  const usage = group && line ? endedUsage(group, line) : null;
  const current = line ? decisionLabel(line) : null;
  const settled = line ? lineHasSettlements(line) : false;
  const endedOn = line?.cooperation_ended_on ?? line?.end_date ?? null;

  const choose = (action: (g: OrderGroupRead, l: OrderLineRead) => void) => {
    if (!group || !line) return;
    onClose();
    action(group, line);
  };

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      size="md"
      title={current ? "Zmień decyzję o konsultancie" : "Decyzja o konsultancie"}
      description={
        group && line ? `Zamówienie nr ${group.order_number} · ${line.consultant_name}` : undefined
      }
      footer={
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-muted"
        >
          Anuluj
        </button>
      }
    >
      {group && line ? (
        <div className="flex flex-col gap-4 text-sm">
          <p className="text-muted-foreground">
            {endedOn
              ? `Współpraca na tym zamówieniu zakończyła się ${formatDate(endedOn)}.`
              : "Ta osoba nie pracuje już na tym zamówieniu."}
            {usage ? ` Wykorzystano ${usage}.` : ""}
            {current ? ` Obecna decyzja: ${current.toLowerCase()}.` : ""}
          </p>

          {pendingPool && line.offboarding_case ? (
            <>
              <p className="text-muted-foreground">
                {line.offboarding_case.uses_shared_md_pool
                  ? "Wspólna pula zamówienia pozostaje bez zmian — zdecyduj, czy osoba schodzi z zamówienia, czy wraca do pracy."
                  : line.offboarding_case.remaining_md_snapshot > 0
                    ? `Na osobie zostało ${formatMd(line.offboarding_case.remaining_md_snapshot)} MD. Zdecyduj, czy pula przepada, przechodzi na innego konsultanta, czy osoba wraca do pracy.`
                    : "Pula osoby jest wykorzystana w całości — zostaje zamknąć sprawę albo przywrócić osobę."}
              </p>
              <ul className="flex flex-col gap-2">
                {canManage ? (
                  <DecisionOption
                    title="Zdecyduj o pozostałej puli MD"
                    description="Zamknięcie puli, przeniesienie MD na innego konsultanta albo przywrócenie osoby."
                    onSelect={() => choose(onResolveOffboarding)}
                  />
                ) : (
                  <li className="text-xs font-medium text-destructive">
                    Decyzję o puli MD podejmuje Delivery Lead.
                  </li>
                )}
              </ul>
            </>
          ) : (
            <ul className="flex flex-col gap-2">
              {onKeepHistory ? (
                <DecisionOption
                  title="Zostaw jako historię"
                  description="Osoba zostaje w sekcji „Zakończone” razem z wykorzystaniem. Nic więcej się nie zmienia."
                  onSelect={() => choose(onKeepHistory)}
                  disabled={Boolean(line.history_kept_at)}
                  disabledReason="To jest obecna decyzja."
                />
              ) : null}
              {canManage && onReplaceLine && group.can_add_consultant ? (
                <DecisionOption
                  title="Zastąp kimś innym"
                  description="Nowa osoba dołącza do zamówienia za tę osobę."
                  onSelect={() => choose(onReplaceLine)}
                />
              ) : null}
              {canManageLifecycle ? (
                <DecisionOption
                  title="Usuń z zamówienia"
                  description="Osoba znika z zamówienia trwale."
                  onSelect={() => choose(onDeleteLine)}
                  disabled={settled}
                  disabledReason={SETTLED_HINT}
                  destructive
                />
              ) : null}
            </ul>
          )}
        </div>
      ) : null}
    </AppModal>
  );
}
